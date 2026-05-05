"""GitHub comment writing helpers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


COMMENT_MARKER = "<!-- ai-pr-review:build-release-mcp -->"


class GitHubWriteError(Exception):
    """A user-facing GitHub write failure."""


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
        raise GitHubWriteError(completed.stderr.strip() or completed.stdout.strip())
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

