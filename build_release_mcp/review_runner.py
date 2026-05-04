"""Run an AI pull request review by calling this package's MCP server."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMMENT_MARKER = "<!-- ai-pr-review:build-release-mcp -->"


class RunnerError(Exception):
    """A user-facing runner failure."""


class McpClient:
    def __init__(self) -> None:
        env = os.environ.copy()
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


def collect_pr_context(pr: str, max_diff_bytes: int) -> dict[str, Any]:
    client = McpClient()
    try:
        client.request("initialize")
        return {
            "overview": client.call_tool("pr_overview", {"pr": pr}),
            "files": client.call_tool("pr_files", {"pr": pr}),
            "review_threads": client.call_tool(
                "pr_review_threads", {"pr": pr, "unresolved_only": True}
            ),
            "diff": client.call_tool(
                "pr_diff", {"pr": pr, "max_bytes": max_diff_bytes}
            ),
        }
    finally:
        client.close()


def build_review_prompt(context: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            "Review this GitHub pull request.",
            "Prioritize correctness bugs, regressions, security issues, data loss, race conditions, missing migrations, and missing tests.",
            "Do not lead with style preferences or broad refactors.",
            "Return Markdown. If you find issues, use severity-ordered bullets with file paths and line references when possible.",
            "If you do not find blocking issues, say that clearly and mention residual risk.",
            f"PR overview:\n```json\n{json.dumps(context['overview'], indent=2, sort_keys=True)}\n```",
            f"Changed files:\n```json\n{json.dumps(context['files'], indent=2, sort_keys=True)}\n```",
            f"Unresolved review threads:\n```json\n{json.dumps(context['review_threads'], indent=2, sort_keys=True)}\n```",
            f"Diff:\n```diff\n{context['diff'].get('text', '')}\n```",
        ]
    )


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


def call_openai(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RunnerError("OPENAI_API_KEY is required")

    model = os.environ.get("OPENAI_MODEL", "gpt-5")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    max_output_tokens = int(os.environ.get("AI_REVIEW_MAX_OUTPUT_TOKENS", "1800"))
    payload = {
        "model": model,
        "instructions": "You are a senior engineer performing a concise, bug-focused pull request review.",
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


def post_comment(pr: str, body: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write(body)
        path = file.name

    try:
        subprocess.run(
            ["gh", "pr", "comment", pr, "--body-file", path],
            cwd=os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT") or os.getcwd(),
            check=True,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def run_review(pr: str, post: bool = False, max_diff_bytes: int = 180_000) -> str:
    context = collect_pr_context(pr, max_diff_bytes)
    review = call_openai(build_review_prompt(context))
    body = f"{COMMENT_MARKER}\n\n## AI PR Review\n\n{review}\n"
    if post:
        post_comment(pr, body)
    return body


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
