"""Hosted GitHub webhook service for automated PR reviews."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .review_runner import RunnerError, run_review


MAX_BODY_BYTES = 5 * 1024 * 1024
DEFAULT_PORT = 8080
PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


@dataclass
class ReviewJob:
    id: str
    pr_url: str
    repo: str
    action: str
    status: str
    created_at: float
    updated_at: float
    error: str | None = None


jobs: dict[str, ReviewJob] = {}
work_queue: "queue.Queue[str]" = queue.Queue()
jobs_lock = threading.Lock()


def now() -> float:
    return time.time()


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


def required_env_missing() -> list[str]:
    names = ["GITHUB_WEBHOOK_SECRET", "OPENAI_API_KEY", "GH_TOKEN"]
    return [name for name in names if not os.environ.get(name)]


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature)


def enqueue_review(pr_url: str, repo: str, action: str) -> ReviewJob:
    job = ReviewJob(
        id=str(uuid.uuid4()),
        pr_url=pr_url,
        repo=repo,
        action=action,
        status="queued",
        created_at=now(),
        updated_at=now(),
    )
    with jobs_lock:
        jobs[job.id] = job
    work_queue.put(job.id)
    return job


def update_job(job_id: str, status: str, error: str | None = None) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.status = status
        job.error = error
        job.updated_at = now()


def worker() -> None:
    while True:
        job_id = work_queue.get()
        with jobs_lock:
            job = jobs[job_id]
        try:
            update_job(job_id, "running")
            run_review(job.pr_url, post=True, max_diff_bytes=max_diff_bytes())
            update_job(job_id, "completed")
        except (RunnerError, Exception) as exc:
            update_job(job_id, "failed", str(exc))
            print(f"review job {job_id} failed: {exc}", file=sys.stderr)
        finally:
            work_queue.task_done()


class HostedServiceHandler(BaseHTTPRequestHandler):
    server_version = "BuildReleaseMCPHostedService/0.1"

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
            self.write_json(status, {"status": "ok" if not missing else "not_ready", "missing": missing})
            return
        if path.startswith("/jobs/"):
            job_id = path.removeprefix("/jobs/")
            with jobs_lock:
                job = jobs.get(job_id)
            if job is None:
                self.write_json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
                return
            self.write_json(HTTPStatus.OK, asdict(job))
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
            self.write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "GITHUB_WEBHOOK_SECRET is not configured"})
            return
        if not verify_signature(secret, body, self.headers.get("X-Hub-Signature-256")):
            self.write_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid signature"})
            return

        event = self.headers.get("X-GitHub-Event")
        if event == "ping":
            self.write_json(HTTPStatus.OK, {"status": "pong"})
            return
        if event != "pull_request":
            self.write_json(HTTPStatus.ACCEPTED, {"status": "ignored", "reason": "unsupported event"})
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return

        response = handle_pull_request_event(payload)
        self.write_json(response[0], response[1])


def handle_pull_request_event(payload: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}
    repo = (payload.get("repository") or {}).get("full_name")

    if action not in PR_ACTIONS:
        return HTTPStatus.ACCEPTED, {"status": "ignored", "reason": "unsupported action", "action": action}
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
    if not repo or not pr_url:
        return HTTPStatus.BAD_REQUEST, {"error": "missing repository or pull request URL"}

    missing = required_env_missing()
    if missing:
        return HTTPStatus.SERVICE_UNAVAILABLE, {"error": "service is not configured", "missing": missing}

    job = enqueue_review(pr_url=pr_url, repo=repo, action=action)
    return HTTPStatus.ACCEPTED, {"status": "queued", "job": asdict(job)}


def main() -> int:
    host = os.environ.get("HOSTED_SERVICE_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    workers = int(os.environ.get("HOSTED_SERVICE_WORKERS", "1"))

    for _ in range(max(1, workers)):
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    server = ThreadingHTTPServer((host, port), HostedServiceHandler)
    print(f"Hosted build-release MCP service listening on {host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
