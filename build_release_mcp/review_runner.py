"""Run an AI pull request review by calling this package's MCP server."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .findings import Finding, coerce_findings, extract_json_object
from .config import (
    load_local_config,
    review_enabled,
    review_ignored_paths,
    review_max_diff_bytes,
    review_model,
)


ROOT = Path(__file__).resolve().parents[1]
COMMENT_MARKER = "<!-- ai-pr-review:build-release-mcp -->"


class RunnerError(Exception):
    """A user-facing runner failure."""


@dataclass
class ReviewResult:
    body: str
    findings: list[Finding]
    residual_risk: str


class McpClient:
    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        python_path = str(ROOT)
        if env.get("PYTHONPATH"):
            python_path = f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
        env["PYTHONPATH"] = python_path
        self.process = subprocess.Popen(
            [sys.executable, "-m", "build_release_mcp"],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.next_id = 1

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RunnerError("MCP server pipes are unavailable")

        request_id = self.next_id
        self.next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RunnerError(f"MCP server exited without a response. {stderr.strip()}")

        response = json.loads(line)
        if "error" in response:
            raise RunnerError(response["error"].get("message", "Unknown MCP error"))

        result = response.get("result")
        if isinstance(result, dict) and result.get("isError"):
            text = "\n".join(
                item.get("text", "")
                for item in result.get("content", [])
                if item.get("type") == "text"
            )
            raise RunnerError(text or "MCP tool call failed")

        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments,
            },
        )
        text = "\n".join(
            item.get("text", "")
            for item in result.get("content", [])
            if item.get("type") == "text"
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


def collect_pr_context(
    pr: str, max_diff_bytes: int, extra_env: dict[str, str] | None = None
) -> dict[str, Any]:
    client = McpClient(extra_env=extra_env)
    try:
        client.request("initialize")
        files = client.call_tool("pr_files", {"pr": pr})
        paths = [
            item.get("path") or item.get("filename")
            for item in files
            if isinstance(item, dict) and (item.get("path") or item.get("filename"))
        ]
        return {
            "overview": client.call_tool("pr_overview", {"pr": pr}),
            "files": files,
            "check_runs": client.call_tool("pr_check_runs", {"pr": pr}),
            "test_results": client.call_tool("pr_test_results", {"pr": pr}),
            "codeowners": client.call_tool("pr_codeowners", {"paths": paths}),
            "review_threads": client.call_tool(
                "pr_review_threads", {"pr": pr, "unresolved_only": True}
            ),
            "diff": client.call_tool(
                "pr_diff", {"pr": pr, "max_bytes": max_diff_bytes}
            ),
        }
    finally:
        client.close()


def _path_ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def apply_review_config(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    ignored = review_ignored_paths(config)
    if not ignored:
        return context

    files = context.get("files", [])
    kept = []
    ignored_files = []
    for item in files if isinstance(files, list) else []:
        filename = item.get("path") or item.get("filename") if isinstance(item, dict) else None
        if filename and _path_ignored(filename, ignored):
            ignored_files.append(item)
        else:
            kept.append(item)

    updated = dict(context)
    updated["files"] = kept
    updated["ignored_files"] = ignored_files
    updated["ignored_path_patterns"] = ignored
    return updated


def build_review_prompt(context: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    config = config or {}
    return "\n\n".join(
        [
            "Review this GitHub pull request.",
            "Prioritize correctness bugs, regressions, security issues, data loss, race conditions, missing migrations, and missing tests.",
            "Do not lead with style preferences or broad refactors.",
            "Return Markdown. If you find issues, use severity-ordered bullets with file paths and line references when possible.",
            "For each actionable issue, include a concise suggested fix when the fix is clear.",
            "If you do not find blocking issues, say that clearly and mention residual risk.",
            f"PR overview:\n```json\n{json.dumps(context['overview'], indent=2, sort_keys=True)}\n```",
            f"Changed files:\n```json\n{json.dumps(context['files'], indent=2, sort_keys=True)}\n```",
            f"Check runs:\n```json\n{json.dumps(context.get('check_runs', {}), indent=2, sort_keys=True)}\n```",
            f"Test results:\n```json\n{json.dumps(context.get('test_results', {}), indent=2, sort_keys=True)}\n```",
            f"CODEOWNERS matches:\n```json\n{json.dumps(context.get('codeowners', {}), indent=2, sort_keys=True)}\n```",
            f"Ignored files from config:\n```json\n{json.dumps(context.get('ignored_files', []), indent=2, sort_keys=True)}\n```",
            f"Review config:\n```json\n{json.dumps(config, indent=2, sort_keys=True)}\n```",
            f"Unresolved review threads:\n```json\n{json.dumps(context['review_threads'], indent=2, sort_keys=True)}\n```",
            f"Diff:\n```diff\n{context['diff'].get('text', '')}\n```",
        ]
    )


def build_structured_review_prompt(
    context: dict[str, Any], config: dict[str, Any] | None = None
) -> str:
    config = config or {}
    return "\n\n".join(
        [
            "Review this GitHub pull request and return structured JSON only.",
            "Find only real issues: correctness bugs, regressions, security issues, data loss, race conditions, missing migrations, broken CI, ownership gaps, deployment or release risk, and missing tests.",
            "Do not include style preferences, speculative broad refactors, or praise.",
            "Return this JSON shape exactly:",
            '{"findings":[{"severity":"critical|high|medium|low","path":"path or null","line":123,"summary":"short issue","details":"why this matters","suggested_fix":"clear fix or null"}],"residual_risk":"short note when no blocking issues or remaining uncertainty"}',
            "Use an empty findings array when no actionable issues are found.",
            "Do not wrap the JSON in Markdown.",
            f"PR overview:\n```json\n{json.dumps(context['overview'], indent=2, sort_keys=True)}\n```",
            f"Changed files:\n```json\n{json.dumps(context['files'], indent=2, sort_keys=True)}\n```",
            f"Check runs:\n```json\n{json.dumps(context.get('check_runs', {}), indent=2, sort_keys=True)}\n```",
            f"Test results:\n```json\n{json.dumps(context.get('test_results', {}), indent=2, sort_keys=True)}\n```",
            f"CODEOWNERS matches:\n```json\n{json.dumps(context.get('codeowners', {}), indent=2, sort_keys=True)}\n```",
            f"Ignored files from config:\n```json\n{json.dumps(context.get('ignored_files', []), indent=2, sort_keys=True)}\n```",
            f"Review config:\n```json\n{json.dumps(config, indent=2, sort_keys=True)}\n```",
            f"Unresolved review threads:\n```json\n{json.dumps(context['review_threads'], indent=2, sort_keys=True)}\n```",
            f"Diff:\n```diff\n{context['diff'].get('text', '')}\n```",
        ]
    )


def parse_structured_review(text: str) -> tuple[list[Finding], str]:
    try:
        payload = extract_json_object(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RunnerError(f"OpenAI response did not contain valid review JSON: {exc}") from exc
    findings = coerce_findings(payload.get("findings"))
    residual_risk = str(payload.get("residual_risk") or "").strip()
    return findings, residual_risk


def render_findings_markdown(findings: list[Finding], residual_risk: str = "") -> str:
    if not findings:
        risk = residual_risk or "No blocking issues found from the provided PR context."
        return f"No blocking issues found.\n\nResidual risk: {risk}"

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(findings, key=lambda item: severity_order.get(item.severity, 99))
    lines = ["Findings:"]
    for finding in ordered:
        location = finding.path or "unknown file"
        if finding.line:
            location = f"{location}:{finding.line}"
        lines.append(f"- **{finding.severity.upper()}** `{location}` - {finding.summary}")
        if finding.details:
            lines.append(f"  {finding.details}")
        if finding.suggested_fix:
            lines.append(f"  Suggested fix: {finding.suggested_fix}")
    if residual_risk:
        lines.extend(["", f"Residual risk: {residual_risk}"])
    return "\n".join(lines)


def extract_output_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    if not parts:
        raise RunnerError("OpenAI response did not contain output text")
    return "\n".join(parts).strip()


def call_openai(
    prompt: str,
    extra_env: dict[str, str] | None = None,
    model_override: str | None = None,
    system_instructions: str = "You are a senior engineer performing a concise, bug-focused pull request review.",
) -> str:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        raise RunnerError("OPENAI_API_KEY is required")

    model = model_override or env.get("OPENAI_MODEL", "gpt-5")
    base_url = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    max_output_tokens = int(env.get("AI_REVIEW_MAX_OUTPUT_TOKENS", "1800"))
    payload = {
        "model": model,
        "instructions": system_instructions,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
    }
    request = urllib.request.Request(
        f"{base_url}/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RunnerError(f"OpenAI API request failed with {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RunnerError(f"OpenAI API request failed: {exc}") from exc

    return extract_output_text(json.loads(body))


def parse_pr_url(pr: str) -> tuple[str, str, int] | None:
    marker = "https://github.com/"
    if not pr.startswith(marker):
        return None
    parts = pr.removeprefix(marker).split("/")
    if len(parts) >= 4 and parts[2] == "pull" and parts[3].isdigit():
        return parts[0], parts[1], int(parts[3])
    return None


def _gh_json(args: list[str], extra_env: dict[str, str] | None = None) -> Any:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(args, env=env, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RunnerError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout or "null")


def _find_existing_comment(
    owner: str,
    repo: str,
    number: int,
    extra_env: dict[str, str] | None,
    marker: str = COMMENT_MARKER,
) -> int | None:
    comments = _gh_json(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{owner}/{repo}/issues/{number}/comments",
        ],
        extra_env=extra_env,
    )
    if not isinstance(comments, list):
        return None
    for comment in comments:
        if marker in str(comment.get("body", "")):
            return int(comment["id"])
    return None


def post_comment(
    pr: str,
    body: str,
    extra_env: dict[str, str] | None = None,
    marker: str = COMMENT_MARKER,
) -> None:
    parsed = parse_pr_url(pr)
    if parsed:
        owner, repo, number = parsed
        existing = _find_existing_comment(owner, repo, number, extra_env, marker=marker)
        if existing is not None:
            env = os.environ.copy()
            if extra_env:
                env.update(extra_env)
            subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    f"repos/{owner}/{repo}/issues/comments/{existing}",
                    "-f",
                    f"body={body}",
                ],
                env=env,
                cwd=os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT") or os.getcwd(),
                check=True,
            )
            return

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write(body)
        path = file.name

    try:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        subprocess.run(
            ["gh", "pr", "comment", pr, "--body-file", path],
            env=env,
            cwd=os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT") or os.getcwd(),
            check=True,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def run_review(
    pr: str,
    post: bool = False,
    max_diff_bytes: int = 180_000,
    extra_env: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    return run_structured_review(
        pr,
        post=post,
        max_diff_bytes=max_diff_bytes,
        extra_env=extra_env,
        config=config,
    ).body


def run_structured_review(
    pr: str,
    post: bool = False,
    max_diff_bytes: int = 180_000,
    extra_env: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> ReviewResult:
    config = config if config is not None else load_local_config()
    if not review_enabled(config):
        raise RunnerError("PR review is disabled by configuration")

    max_diff_bytes = review_max_diff_bytes(config, max_diff_bytes)
    context = apply_review_config(collect_pr_context(pr, max_diff_bytes, extra_env), config)
    raw_review = call_openai(
        build_structured_review_prompt(context, config),
        extra_env=extra_env,
        model_override=review_model(config),
        system_instructions=(
            "You are a senior engineer performing a concise, bug-focused pull request review. "
            "Return only valid JSON for the requested schema."
        ),
    )
    findings, residual_risk = parse_structured_review(raw_review)
    review = render_findings_markdown(findings, residual_risk)
    body = f"{COMMENT_MARKER}\n\n## AI PR Review\n\n{review}\n"
    if post:
        post_comment(pr, body, extra_env=extra_env)
    return ReviewResult(body=body, findings=findings, residual_risk=residual_risk)


def review_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an AI PR review.")
    parser.add_argument("pr", nargs="?", default=os.environ.get("PR_URL"))
    parser.add_argument("--post-comment", action="store_true")
    parser.add_argument(
        "--max-diff-bytes",
        type=int,
        default=int(os.environ.get("AI_REVIEW_MAX_DIFF_BYTES", "180000")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.pr:
        raise RunnerError("Provide a PR number or URL, or set PR_URL")

    body = run_review(args.pr, post=args.post_comment, max_diff_bytes=args.max_diff_bytes)
    print(body)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        Path(step_summary).write_text(body, encoding="utf-8")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
