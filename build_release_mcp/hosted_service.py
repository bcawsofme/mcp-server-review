"""Hosted GitHub webhook service for automated PR reviews."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import sys
import threading
import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import ConfigError, get_path, load_repo_config, review_max_diff_bytes
from .findings import Finding
from .fix_runner import run_minor_fix
from .github_auth import GitHubAuthError, has_github_app_config, resolve_token
from .job_store import FindingReconciliation, JobStore, StoredFinding
from .review_runner import (
    COMMENT_MARKER,
    RunnerError,
    post_comment,
    render_findings_markdown,
    review_hash,
    run_structured_review,
)


MAX_BODY_BYTES = 5 * 1024 * 1024
DEFAULT_PORT = 8080
PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


work_queue: "queue.Queue[str]" = queue.Queue()
store = JobStore(os.environ.get("HOSTED_SERVICE_DB", "/tmp/build-release-mcp/jobs.sqlite3"))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def allowed_repos() -> set[str]:
    raw = os.environ.get("HOSTED_SERVICE_ALLOWED_REPOS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def max_diff_bytes() -> int:
    return int(os.environ.get("AI_REVIEW_MAX_DIFF_BYTES", "180000"))


def minor_fixes_enabled(config: dict[str, Any]) -> bool:
    return env_bool("HOSTED_SERVICE_ENABLE_MINOR_FIXES", False) and bool(
        get_path(config, ("pr_review", "minor_fixes_enabled"), False)
    )


def has_github_auth_config() -> bool:
    return bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or has_github_app_config())


def required_env_missing() -> list[str]:
    missing = []
    if not os.environ.get("GITHUB_WEBHOOK_SECRET"):
        missing.append("GITHUB_WEBHOOK_SECRET")
    if not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not has_github_auth_config():
        missing.append("GH_TOKEN or GitHub App credentials")
    return missing


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature)


def _job_env(token: str) -> dict[str, str]:
    env = {"GH_TOKEN": token, "GITHUB_TOKEN": token}
    if repo_root := os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT"):
        env["BUILD_RELEASE_MCP_REPO_ROOT"] = repo_root
    return env


def _stored_to_finding(item: StoredFinding) -> Finding:
    return Finding(
        finding_id=item.finding_id,
        severity=item.severity,
        path=item.path,
        line=item.line,
        summary=item.summary,
        details=item.details,
        suggested_fix=item.suggested_fix,
        status=item.status,
    )


def build_reconciled_review_body(
    reconciliation: FindingReconciliation,
    residual_risk: str,
    head_sha: str,
) -> str:
    lines = [COMMENT_MARKER, "", "## AI PR Review", ""]
    if reconciliation.new_findings:
        lines.append("New findings on this commit:")
        lines.append("")
        lines.append(
            render_findings_markdown(
                [_stored_to_finding(item) for item in reconciliation.new_findings],
                residual_risk="",
            )
        )
    else:
        lines.append("No new findings on this commit.")

    if reconciliation.resolved_findings:
        lines.extend(["", "Resolved findings:"])
        for item in reconciliation.resolved_findings:
            location = item.path or "unknown file"
            if item.line:
                location = f"{location}:{item.line}"
            lines.append(f"- `{location}` - {item.summary}")

    remaining = [
        item
        for item in reconciliation.open_findings
        if item.finding_id not in {finding.finding_id for finding in reconciliation.new_findings}
    ]
    if remaining:
        lines.extend(["", f"Still open: {len(remaining)} finding(s)."])

    if reconciliation.ignored_findings:
        lines.extend(["", f"Ignored: {len(reconciliation.ignored_findings)} finding(s)."])

    risk = residual_risk.strip()
    if risk:
        lines.extend(["", f"Residual risk: {risk}"])

    lines.extend(["", f"Reviewed commit: `{head_sha}`", ""])
    return "\n".join(lines)


def worker() -> None:
    while True:
        job_id = work_queue.get()
        job = store.get(job_id)
        if job is None:
            work_queue.task_done()
            continue
        try:
            store.update(job.id, "running")
            token = resolve_token(job.installation_id)
            env = _job_env(token)
            config = load_repo_config(job.repo, job.head_sha, env=env)
            result = run_structured_review(
                job.pr_url,
                post=False,
                max_diff_bytes=review_max_diff_bytes(config, max_diff_bytes()),
                extra_env=env,
                config=config,
            )
            reconciliation = store.reconcile_findings(
                repo=job.repo,
                pr_number=job.pr_number,
                head_sha=job.head_sha,
                findings=result.findings,
            )
            body = build_reconciled_review_body(
                reconciliation,
                residual_risk=result.residual_risk,
                head_sha=job.head_sha,
            )
            post_comment(job.pr_url, body, extra_env=env)
            if minor_fixes_enabled(config) and reconciliation.new_findings:
                try:
                    run_minor_fix(
                        job.pr_url,
                        instructions=(
                            "Apply only minor, safe fixes for the new structured PR review findings."
                        ),
                        post=True,
                        push=True,
                        extra_env=env,
                        config=config,
                    )
                except RunnerError as exc:
                    print(f"minor fix job {job_id} skipped or failed: {exc}", file=sys.stderr)
            store.update(job.id, "completed", review_hash=review_hash(body))
        except (ConfigError, GitHubAuthError, RunnerError, Exception) as exc:
            store.update(job.id, "failed", str(exc))
            print(f"review job {job_id} failed: {exc}", file=sys.stderr)
        finally:
            work_queue.task_done()


class HostedServiceHandler(BaseHTTPRequestHandler):
    server_version = "BuildReleaseMCPHostedService/0.2"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}", file=sys.stderr)

    def write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body too large")
        return self.rfile.read(length)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health/live":
            self.write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/health/ready":
            missing = required_env_missing()
            status = HTTPStatus.OK if not missing else HTTPStatus.SERVICE_UNAVAILABLE
            self.write_json(
                status,
                {"status": "ok" if not missing else "not_ready", "missing": missing},
            )
            return
        if path.startswith("/jobs/"):
            job_id = path.removeprefix("/jobs/")
            job = store.get(job_id)
            if job is None:
                self.write_json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
                return
            self.write_json(HTTPStatus.OK, job.as_dict())
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/webhooks/github":
            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            body = self.read_body()
        except ValueError as exc:
            self.write_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": str(exc)})
            return

        secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        if not secret:
            self.write_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "GITHUB_WEBHOOK_SECRET is not configured"},
            )
            return
        if not verify_signature(secret, body, self.headers.get("X-Hub-Signature-256")):
            self.write_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid signature"})
            return

        event = self.headers.get("X-GitHub-Event")
        delivery_id = self.headers.get("X-GitHub-Delivery", "")
        if event == "ping":
            self.write_json(HTTPStatus.OK, {"status": "pong"})
            return
        if event != "pull_request":
            self.write_json(
                HTTPStatus.ACCEPTED,
                {"status": "ignored", "reason": "unsupported event"},
            )
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return

        response = handle_pull_request_event(payload, delivery_id=delivery_id)
        self.write_json(response[0], response[1])


def handle_pull_request_event(
    payload: dict[str, Any], delivery_id: str = ""
) -> tuple[HTTPStatus, dict[str, Any]]:
    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name")
    installation_id = (payload.get("installation") or {}).get("id")

    if action not in PR_ACTIONS:
        return HTTPStatus.ACCEPTED, {
            "status": "ignored",
            "reason": "unsupported action",
            "action": action,
        }
    if pull_request.get("draft"):
        return HTTPStatus.ACCEPTED, {"status": "ignored", "reason": "draft pull request"}
    if not env_bool("HOSTED_SERVICE_ALLOW_FORKS", False):
        head_repo = (pull_request.get("head") or {}).get("repo") or {}
        if head_repo.get("full_name") and head_repo.get("full_name") != repo:
            return HTTPStatus.ACCEPTED, {"status": "ignored", "reason": "fork pull request"}

    allowed = allowed_repos()
    if allowed and repo not in allowed:
        return HTTPStatus.FORBIDDEN, {"error": "repository is not allowed", "repo": repo}

    pr_url = pull_request.get("html_url")
    pr_number = pull_request.get("number")
    head_sha = ((pull_request.get("head") or {}).get("sha")) or ""
    if not repo or not pr_url or not pr_number or not head_sha:
        return HTTPStatus.BAD_REQUEST, {"error": "missing repository, PR URL, number, or head SHA"}

    missing = required_env_missing()
    if missing:
        return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service is not configured", "missing": missing}

    job, created = store.enqueue(
        delivery_id=delivery_id or f"{repo}:{pr_number}:{head_sha}",
        repo=repo,
        pr_url=pr_url,
        pr_number=int(pr_number),
        head_sha=head_sha,
        action=str(action),
        installation_id=int(installation_id) if installation_id else None,
    )
    if created:
        work_queue.put(job.id)
        return HTTPStatus.ACCEPTED, {"status": "queued", "job": job.as_dict()}
    return HTTPStatus.ACCEPTED, {"status": "duplicate", "job": job.as_dict()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the hosted build-release MCP webhook service.")
    parser.add_argument("--host", default=os.environ.get("HOSTED_SERVICE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", str(DEFAULT_PORT))))
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("HOSTED_SERVICE_WORKERS", "1")),
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("HOSTED_SERVICE_DB", "/tmp/build-release-mcp/jobs.sqlite3"),
    )
    return parser.parse_args()


def main() -> int:
    global store
    args = parse_args()
    store = JobStore(args.db)

    for _ in range(max(1, args.workers)):
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), HostedServiceHandler)
    print(f"Hosted build-release MCP service listening on {args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
