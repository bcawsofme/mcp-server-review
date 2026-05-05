"""Apply minor AI-suggested fixes to a pull request branch."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import load_local_config, review_enabled, review_max_diff_bytes, review_model
from .github_writer import post_comment
from .review_runner import RunnerError, apply_review_config, call_openai, collect_pr_context


FIX_COMMENT_MARKER = "<!-- ai-pr-minor-fixes:build-release-mcp -->"
DEFAULT_FIX_INSTRUCTIONS = "Apply only minor, safe fixes for clear PR review findings."
BLOCKED_PATCH_PATTERNS = (".github/workflows/*",)


def run_command(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        cwd=os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT") or os.getcwd(),
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RunnerError(f"{' '.join(args)} failed: {message}")
    return completed


def build_fix_prompt(
    context: dict[str, Any],
    instructions: str = DEFAULT_FIX_INSTRUCTIONS,
    config: dict[str, Any] | None = None,
) -> str:
    config = config or {}
    return "\n\n".join(
        [
            "You are preparing a small patch for this pull request branch.",
            f"User instructions: {instructions}",
            "Only fix issues that are obvious from the diff and can be changed safely without broad refactors.",
            "Good candidates: typo-level bugs, missing null checks, wrong constants, simple test expectation updates, small lint/type errors, or directly actionable review feedback.",
            "Do not change workflows, dependency lockfiles, generated files, secrets, credentials, vendored code, or unrelated files.",
            "If no safe minor fix is appropriate, return exactly NO_CHANGES.",
            "Otherwise return only a valid unified diff that can be applied with git apply. Do not include prose or Markdown fences.",
            f"PR overview:\n```json\n{json.dumps(context['overview'], indent=2, sort_keys=True)}\n```",
            f"Changed files:\n```json\n{json.dumps(context['files'], indent=2, sort_keys=True)}\n```",
            f"Review config:\n```json\n{json.dumps(config, indent=2, sort_keys=True)}\n```",
            f"Unresolved review threads:\n```json\n{json.dumps(context['review_threads'], indent=2, sort_keys=True)}\n```",
            f"Diff:\n```diff\n{context['diff'].get('text', '')}\n```",
        ]
    )


def extract_unified_diff(text: str) -> str | None:
    stripped = text.strip()
    if not stripped or stripped == "NO_CHANGES":
        return None

    if "```" in stripped:
        blocks = stripped.split("```")
        for block in blocks[1::2]:
            lines = block.strip().splitlines()
            if lines and not lines[0].startswith(("diff --git ", "--- ")):
                lines = lines[1:]
            candidate = "\n".join(lines).strip()
            if candidate.startswith(("diff --git ", "--- ")):
                stripped = candidate
                break

    markers = ["diff --git ", "--- "]
    starts = [stripped.find(marker) for marker in markers if stripped.find(marker) >= 0]
    if starts:
        stripped = stripped[min(starts) :].strip()

    if not (stripped.startswith("diff --git ") or stripped.startswith("--- ")):
        raise RunnerError("Model response did not contain a unified diff or NO_CHANGES")
    return stripped + "\n"


def paths_from_unified_diff(diff: str) -> set[str]:
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            for item in parts[2:4]:
                if item.startswith(("a/", "b/")):
                    paths.add(item[2:])
            continue
        if line.startswith(("--- a/", "+++ b/")):
            paths.add(line[6:].split("\t", 1)[0])
    return paths


def validate_patch_paths(diff: str) -> None:
    for path in paths_from_unified_diff(diff):
        if any(fnmatch.fnmatch(path, pattern) for pattern in BLOCKED_PATCH_PATTERNS):
            raise RunnerError(f"Refusing to apply AI patch to blocked path: {path}")


def ensure_clean_worktree() -> None:
    status = run_command(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        raise RunnerError("Working tree has uncommitted changes; refusing to apply AI fixes")


def apply_unified_diff(diff: str) -> None:
    validate_patch_paths(diff)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write(diff)
        path = file.name
    try:
        run_command(["git", "apply", "--check", path])
        run_command(["git", "apply", "--whitespace=fix", path])
    finally:
        Path(path).unlink(missing_ok=True)


def changed_files() -> list[str]:
    output = run_command(["git", "status", "--porcelain"]).stdout.splitlines()
    return [line[3:] for line in output if len(line) > 3]


def commit_changes(message: str) -> str:
    run_command(["git", "add", "--all"])
    run_command(["git", "commit", "-m", message], timeout=120)
    return run_command(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()


def run_minor_fix(
    pr: str,
    instructions: str = DEFAULT_FIX_INSTRUCTIONS,
    max_diff_bytes: int = 180_000,
    post: bool = False,
    push: bool = False,
    extra_env: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    config = config if config is not None else load_local_config()
    if not review_enabled(config):
        raise RunnerError("PR review is disabled by configuration")

    ensure_clean_worktree()
    max_diff_bytes = review_max_diff_bytes(config, max_diff_bytes)
    context = apply_review_config(collect_pr_context(pr, max_diff_bytes, extra_env), config)
    response = call_openai(
        build_fix_prompt(context, instructions=instructions, config=config),
        extra_env=extra_env,
        model_override=review_model(config),
        system_instructions=(
            "You are a senior engineer producing minimal, safe pull request fixes. "
            "Return only NO_CHANGES or a unified diff."
        ),
    )
    diff = extract_unified_diff(response)
    if diff is None:
        body = f"{FIX_COMMENT_MARKER}\n\n## AI Minor Fixes\n\nNo safe minor fixes were identified.\n"
        if post:
            post_comment(pr, body, extra_env=extra_env, marker=FIX_COMMENT_MARKER)
        return body

    apply_unified_diff(diff)
    files = changed_files()
    if not files:
        body = f"{FIX_COMMENT_MARKER}\n\n## AI Minor Fixes\n\nPatch applied cleanly but produced no file changes.\n"
        if post:
            post_comment(pr, body, extra_env=extra_env, marker=FIX_COMMENT_MARKER)
        return body

    commit = commit_changes("Apply AI minor fixes")
    if push:
        run_command(["git", "push"], timeout=120)

    pushed = " and pushed" if push else ""
    file_list = "\n".join(f"- `{path}`" for path in files)
    body = (
        f"{FIX_COMMENT_MARKER}\n\n"
        "## AI Minor Fixes\n\n"
        f"Applied{pushed} commit `{commit}`.\n\n"
        f"Changed files:\n{file_list}\n"
    )
    if post:
        post_comment(pr, body, extra_env=extra_env, marker=FIX_COMMENT_MARKER)
    return body


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply minor AI fixes to a PR branch.")
    parser.add_argument("pr", nargs="?", default=os.environ.get("PR_URL"))
    parser.add_argument(
        "--instructions",
        default=os.environ.get("AI_FIX_INSTRUCTIONS", DEFAULT_FIX_INSTRUCTIONS),
    )
    parser.add_argument("--post-comment", action="store_true")
    parser.add_argument("--push", action="store_true")
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

    body = run_minor_fix(
        str(args.pr),
        instructions=args.instructions,
        max_diff_bytes=args.max_diff_bytes,
        post=args.post_comment,
        push=args.push,
    )
    print(body)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
