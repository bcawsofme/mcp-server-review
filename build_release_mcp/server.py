#!/usr/bin/env python3
"""Small stdio MCP server for reviewing GitHub pull requests with gh."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import fnmatch
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from .findings import FINDING_STATUSES, RESOLVED
    from .job_store import JobStore
    from .ops_tools import OPS_TOOLS, OpsToolError
except ImportError:
    from findings import FINDING_STATUSES, RESOLVED
    from job_store import JobStore
    from ops_tools import OPS_TOOLS, OpsToolError


SERVER_NAME = "build-release"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_DIFF_LIMIT_BYTES = 200_000
MAX_DIFF_LIMIT_BYTES = 1_000_000


class ToolError(Exception):
    """A user-facing tool failure."""


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class PullRequestRef:
    pr: str
    repo: str | None
    number: int | None


def repo_root() -> Path:
    configured = os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd()


def run_command(args: list[str], timeout: int = 30) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(repo_root()),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(
            f"Command not found: {args[0]}. Install and authenticate GitHub CLI (`gh`)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command timed out after {timeout}s: {' '.join(args)}") from exc

    result = CommandResult(completed.stdout, completed.stderr, completed.returncode)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise ToolError(f"{' '.join(args)} failed: {message}")
    return result


def parse_json(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"GitHub CLI returned invalid JSON: {exc}") from exc


def normalize_repo(repo: Any) -> str | None:
    if repo is None:
        return None
    if not isinstance(repo, str) or not repo.strip():
        raise ToolError("repo must be an owner/name string")
    value = repo.strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        raise ToolError("repo must look like owner/name")
    return value


def normalize_string(value: Any, name: str, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise ToolError(f"{name} is required")
        return default
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{name} must be a non-empty string")
    return value.strip()


def parse_pr_url(value: str) -> PullRequestRef | None:
    match = re.fullmatch(
        r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/([0-9]+)(?:[/?#].*)?",
        value.strip(),
    )
    if not match:
        return None
    owner, repo, number = match.groups()
    return PullRequestRef(pr=number, repo=f"{owner}/{repo}", number=int(number))


def normalize_pr_ref(raw_pr: Any, raw_repo: Any = None) -> PullRequestRef:
    repo = normalize_repo(raw_repo)
    if isinstance(raw_pr, int):
        if raw_pr <= 0:
            raise ToolError("pr must be a positive integer")
        return PullRequestRef(pr=str(raw_pr), repo=repo, number=raw_pr)

    if isinstance(raw_pr, str) and raw_pr.strip():
        parsed = parse_pr_url(raw_pr)
        if parsed:
            return PullRequestRef(
                pr=parsed.pr,
                repo=repo or parsed.repo,
                number=parsed.number,
            )
        stripped = raw_pr.strip()
        number = int(stripped) if stripped.isdigit() else None
        return PullRequestRef(pr=stripped, repo=repo, number=number)

    raise ToolError("pr is required")


def repo_args(repo: str | None) -> list[str]:
    return ["--repo", repo] if repo else []


def current_repo() -> tuple[str, str]:
    remote = run_command(["git", "config", "--get", "remote.origin.url"]).stdout.strip()
    patterns = [
        r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$",
        r"^https://github\.com/([^/]+)/(.+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group(1), match.group(2)
    raise ToolError("Could not infer GitHub owner/name from remote.origin.url; pass repo")


def truncate_text(text: str, limit_bytes: int) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit_bytes:
        return {"text": text, "truncated": False, "bytes": len(encoded)}

    clipped = encoded[:limit_bytes].decode("utf-8", errors="ignore")
    return {
        "text": clipped,
        "truncated": True,
        "bytes": len(encoded),
        "returnedBytes": len(clipped.encode("utf-8")),
    }


def text_response(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def json_response(value: Any) -> dict[str, Any]:
    return text_response(json.dumps(value, indent=2, sort_keys=True))


def safe_repo_path(raw_path: Any) -> Path:
    path = safe_repo_target(raw_path)
    if not path.is_file():
        raise ToolError(f"file not found: {raw_path}")
    return path


def safe_repo_target(raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ToolError("path must be a non-empty string")
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ToolError("path must stay inside the repository")
    root = repo_root().resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ToolError("path must stay inside the repository") from exc
    return path


def read_repo_file(path: Path, limit_bytes: int) -> dict[str, Any]:
    limit = min(max(limit_bytes, 1), MAX_DIFF_LIMIT_BYTES)
    text = path.read_text(encoding="utf-8", errors="replace")
    payload = truncate_text(text, limit)
    payload["path"] = str(path.relative_to(repo_root()))
    payload["limitBytes"] = limit
    return payload


def codeowners_candidates() -> list[Path]:
    root = repo_root()
    return [
        root / ".github" / "CODEOWNERS",
        root / "CODEOWNERS",
        root / "docs" / "CODEOWNERS",
    ]


def read_codeowners_rules() -> tuple[str | None, list[dict[str, Any]]]:
    codeowners = next((path for path in codeowners_candidates() if path.exists()), None)
    if codeowners is None:
        return None, []
    rules = []
    for line_number, line in enumerate(codeowners.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        rules.append({"line": line_number, "pattern": parts[0], "owners": parts[1:]})
    return str(codeowners.relative_to(repo_root())), rules


def codeowners_pattern_matches(pattern: str, path: str) -> bool:
    normalized = pattern.strip()
    if not normalized:
        return False
    normalized = normalized.rstrip("/")
    if normalized.startswith("/"):
        return fnmatch.fnmatch(path, normalized.lstrip("/"))
    if "/" not in normalized:
        return fnmatch.fnmatch(Path(path).name, normalized) or fnmatch.fnmatch(path, f"**/{normalized}")
    return fnmatch.fnmatch(path, normalized) or fnmatch.fnmatch(path, f"**/{normalized}")


def tool_pr_overview(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    fields = [
        "number",
        "title",
        "state",
        "author",
        "url",
        "baseRefName",
        "headRefName",
        "isDraft",
        "mergeable",
        "mergeStateStatus",
        "reviewDecision",
        "additions",
        "deletions",
        "changedFiles",
        "labels",
        "assignees",
        "reviewRequests",
        "latestReviews",
        "statusCheckRollup",
        "body",
    ]
    result = run_command(
        [
            "gh",
            "pr",
            "view",
            pr_ref.pr,
            *repo_args(pr_ref.repo),
            "--json",
            ",".join(fields),
        ],
        timeout=45,
    )
    return json_response(parse_json(result.stdout))


def tool_pr_files(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    result = run_command(
        ["gh", "pr", "view", pr_ref.pr, *repo_args(pr_ref.repo), "--json", "files"],
        timeout=45,
    )
    return json_response(parse_json(result.stdout).get("files", []))


def tool_pr_diff(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    limit = arguments.get("max_bytes", DEFAULT_DIFF_LIMIT_BYTES)
    if not isinstance(limit, int) or limit < 1:
        raise ToolError("max_bytes must be a positive integer")
    limit = min(limit, MAX_DIFF_LIMIT_BYTES)

    result = run_command(["gh", "pr", "diff", pr_ref.pr, *repo_args(pr_ref.repo)], timeout=60)
    payload = truncate_text(result.stdout, limit)
    payload["limitBytes"] = limit
    return json_response(payload)


def tool_pr_review_threads(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    if pr_ref.number is None:
        raise ToolError("pr_review_threads requires a PR number or GitHub PR URL")

    owner, name = pr_ref.repo.split("/", 1) if pr_ref.repo else current_repo()
    unresolved_only = arguments.get("unresolved_only", True)
    if not isinstance(unresolved_only, bool):
        raise ToolError("unresolved_only must be a boolean")

    query = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          isCollapsed
          path
          line
          startLine
          originalLine
          originalStartLine
          comments(first: 20) {
            nodes {
              databaseId
              author { login }
              body
              createdAt
              diffHunk
              url
            }
          }
        }
      }
    }
  }
}
""".strip()
    result = run_command(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr_ref.number}",
        ],
        timeout=45,
    )
    data = parse_json(result.stdout)
    threads = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    if unresolved_only:
        threads = [thread for thread in threads if not thread.get("isResolved")]
    return json_response(threads)


def tool_pr_check_runs(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    result = run_command(
        [
            "gh",
            "pr",
            "view",
            pr_ref.pr,
            *repo_args(pr_ref.repo),
            "--json",
            "headRefName,headRefOid,statusCheckRollup",
        ],
        timeout=45,
    )
    return json_response(parse_json(result.stdout))


def pr_head_sha(pr_ref: PullRequestRef) -> str:
    result = run_command(
        [
            "gh",
            "pr",
            "view",
            pr_ref.pr,
            *repo_args(pr_ref.repo),
            "--json",
            "headRefOid",
        ],
        timeout=45,
    )
    sha = parse_json(result.stdout).get("headRefOid")
    if not sha:
        raise ToolError("Could not determine PR head SHA")
    return str(sha)


def tool_pr_test_results(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    owner, name = pr_ref.repo.split("/", 1) if pr_ref.repo else current_repo()
    sha = pr_head_sha(pr_ref)
    result = run_command(
        [
            "gh",
            "api",
            *repo_args(f"{owner}/{name}"),
            f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
        ],
        timeout=45,
    )
    data = parse_json(result.stdout)
    check_runs = []
    for item in data.get("check_runs", []):
        output = item.get("output") or {}
        check_runs.append(
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "html_url": item.get("html_url"),
                "details_url": item.get("details_url"),
                "summary": output.get("summary"),
                "text": truncate_text(output.get("text") or "", 20_000),
            }
        )
    return json_response({"headSha": sha, "checkRuns": check_runs})


def tool_pr_codeowners(arguments: dict[str, Any]) -> dict[str, Any]:
    paths = arguments.get("paths")
    if paths is None and arguments.get("pr") is not None:
        files = parse_json(
            run_command(
                [
                    "gh",
                    "pr",
                    "view",
                    normalize_pr_ref(arguments.get("pr"), arguments.get("repo")).pr,
                    *repo_args(normalize_pr_ref(arguments.get("pr"), arguments.get("repo")).repo),
                    "--json",
                    "files",
                ],
                timeout=45,
            ).stdout
        ).get("files", [])
        paths = [item.get("path") for item in files if isinstance(item, dict) and item.get("path")]
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise ToolError("paths must be an array of strings, or provide pr")

    codeowners_file, rules = read_codeowners_rules()
    matches = []
    for path in paths:
        matching_rules = [
            rule
            for rule in rules
            if codeowners_pattern_matches(str(rule["pattern"]), path)
        ]
        matches.append({"path": path, "matchingRules": matching_rules})
    return json_response({"codeownersFile": codeowners_file, "matches": matches})


def tool_pr_file(arguments: dict[str, Any]) -> dict[str, Any]:
    limit = arguments.get("max_bytes", DEFAULT_DIFF_LIMIT_BYTES)
    if not isinstance(limit, int) or limit < 1:
        raise ToolError("max_bytes must be a positive integer")
    return json_response(read_repo_file(safe_repo_path(arguments.get("path")), limit))


def tool_create_branch(arguments: dict[str, Any]) -> dict[str, Any]:
    branch = normalize_string(arguments.get("branch"), "branch")
    from_ref = normalize_string(arguments.get("from_ref"), "from_ref", "HEAD")
    if not re.fullmatch(r"[\w./-]+", branch):
        raise ToolError("branch contains unsupported characters")
    run_command(["git", "branch", branch, from_ref])
    sha = run_command(["git", "rev-parse", branch]).stdout.strip()
    return json_response({"branch": branch, "fromRef": from_ref, "sha": sha})


def tool_commit_file_change(arguments: dict[str, Any]) -> dict[str, Any]:
    path = safe_repo_target(arguments.get("path"))
    content = arguments.get("content")
    if not isinstance(content, str):
        raise ToolError("content must be a string")
    message = normalize_string(arguments.get("message"), "message")
    branch = None
    if arguments.get("branch") is not None:
        branch = normalize_string(arguments.get("branch"), "branch")
        run_command(["git", "switch", branch])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    relative = str(path.relative_to(repo_root()))
    run_command(["git", "add", relative])
    run_command(["git", "commit", "-m", message], timeout=120)
    sha = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    return json_response({"branch": branch, "path": relative, "commit": sha})


def tool_post_review_comment(arguments: dict[str, Any]) -> dict[str, Any]:
    pr_ref = normalize_pr_ref(arguments.get("pr"), arguments.get("repo"))
    body = normalize_string(arguments.get("body"), "body")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write(body)
        path = file.name
    try:
        run_command(["gh", "pr", "comment", pr_ref.pr, *repo_args(pr_ref.repo), "--body-file", path])
    finally:
        Path(path).unlink(missing_ok=True)
    return json_response({"pr": pr_ref.pr, "commented": True})


def tool_mark_finding_resolved(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    if repo is None:
        owner, name = current_repo()
        repo = f"{owner}/{name}"
    pr_number = arguments.get("pr_number")
    if not isinstance(pr_number, int) or pr_number <= 0:
        raise ToolError("pr_number must be a positive integer")
    finding_id = normalize_string(arguments.get("finding_id"), "finding_id")
    status = normalize_string(arguments.get("status"), "status", RESOLVED).lower()
    if status not in FINDING_STATUSES:
        raise ToolError("status must be open, resolved, or ignored")
    db_path = os.environ.get("HOSTED_SERVICE_DB", "/tmp/build-release-mcp/jobs.sqlite3")
    JobStore(db_path).set_finding_status(repo, pr_number, finding_id, status)
    return json_response(
        {"repo": repo, "pr_number": pr_number, "finding_id": finding_id, "status": status}
    )


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

TOOLS: dict[str, dict[str, Any]] = {
    "pr_overview": {
        "description": "Fetch pull request metadata, review state, checks, and body using GitHub CLI.",
        "handler": tool_pr_overview,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
            },
            "required": ["pr"],
            "additionalProperties": False,
        },
    },
    "pr_files": {
        "description": "List files changed by a pull request with additions and deletions.",
        "handler": tool_pr_files,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
            },
            "required": ["pr"],
            "additionalProperties": False,
        },
    },
    "pr_diff": {
        "description": "Fetch a pull request diff, truncated to a configurable byte limit.",
        "handler": tool_pr_diff,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_DIFF_LIMIT_BYTES,
                    "default": DEFAULT_DIFF_LIMIT_BYTES,
                },
            },
            "required": ["pr"],
            "additionalProperties": False,
        },
    },
    "pr_review_threads": {
        "description": "Fetch GitHub review threads for a pull request, including unresolved inline comments.",
        "handler": tool_pr_review_threads,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
                "unresolved_only": {"type": "boolean", "default": True},
            },
            "required": ["pr"],
            "additionalProperties": False,
        },
    },
    "pr_check_runs": {
        "description": "Fetch PR head ref and GitHub check run rollup context.",
        "handler": tool_pr_check_runs,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
            },
            "required": ["pr"],
            "additionalProperties": False,
        },
    },
    "pr_test_results": {
        "description": "Fetch PR check-run output summaries for test and CI context.",
        "handler": tool_pr_test_results,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
            },
            "required": ["pr"],
            "additionalProperties": False,
        },
    },
    "pr_codeowners": {
        "description": "Match changed or provided paths against CODEOWNERS rules.",
        "handler": tool_pr_codeowners,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Optional pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
                "paths": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    },
    "pr_file": {
        "description": "Read a repository file safely, truncated to a byte limit.",
        "handler": tool_pr_file,
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_DIFF_LIMIT_BYTES,
                    "default": DEFAULT_DIFF_LIMIT_BYTES,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "create_branch": {
        "description": "Create a local git branch from a ref.",
        "handler": tool_create_branch,
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string"},
                "from_ref": {"type": "string", "default": "HEAD"},
            },
            "required": ["branch"],
            "additionalProperties": False,
        },
    },
    "commit_file_change": {
        "description": "Write one repository file and commit the change on the current or requested branch.",
        "handler": tool_commit_file_change,
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["path", "content", "message"],
            "additionalProperties": False,
        },
    },
    "post_review_comment": {
        "description": "Post a pull request comment through GitHub CLI.",
        "handler": tool_post_review_comment,
        "inputSchema": {
            "type": "object",
            "properties": {
                "pr": {"type": ["integer", "string"], "description": "Pull request number or URL."},
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
                "body": {"type": "string"},
            },
            "required": ["pr", "body"],
            "additionalProperties": False,
        },
    },
    "mark_finding_resolved": {
        "description": "Update a stored finding status to resolved, ignored, or open.",
        "handler": tool_mark_finding_resolved,
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Optional GitHub repo as owner/name."},
                "pr_number": {"type": "integer"},
                "finding_id": {"type": "string"},
                "status": {"type": "string", "enum": ["open", "resolved", "ignored"], "default": "resolved"},
            },
            "required": ["pr_number", "finding_id"],
            "additionalProperties": False,
        },
    },
}
TOOLS.update(OPS_TOOLS)


def tool_list() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
            for name, tool in TOOLS.items()
        ]
    }


def prompt_list() -> dict[str, Any]:
    return {
        "prompts": [
            {
                "name": "review_pr",
                "description": "Bug-focused pull request review workflow.",
                "arguments": [
                    {"name": "pr", "description": "Pull request number or URL.", "required": True},
                    {"name": "repo", "description": "Optional GitHub repo as owner/name.", "required": False},
                ],
            },
            {
                "name": "release_readiness",
                "description": "Build and release readiness workflow.",
                "arguments": [
                    {"name": "base", "description": "Base ref for comparison.", "required": False},
                    {"name": "repo", "description": "Optional GitHub repo as owner/name.", "required": False},
                ],
            }
        ]
    }


def prompt_get(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name == "review_pr":
        pr = arguments.get("pr", "<PR number or URL>")
        repo = arguments.get("repo")
        repo_text = f" in {repo}" if repo else ""
        text = f"""
Review pull request {pr}{repo_text}.

Use the PR review MCP tools in this order:
1. pr_overview for scope, checks, review state, and PR intent.
2. pr_files to identify risky areas and decide which diffs need close reading.
3. pr_check_runs and pr_test_results for CI and test context.
4. pr_codeowners for ownership context on changed paths.
5. pr_review_threads to avoid duplicating unresolved feedback.
6. pr_diff with a focused max_bytes value. Request smaller repo context with pr_file if the full diff is too large.

Review stance:
- Prioritize correctness bugs, regressions, security issues, data loss, race conditions, missing migrations, and missing tests.
- Do not lead with style preferences or broad refactors.
- Include a concise suggested fix for each actionable issue when the fix is clear.
- Cite exact files and lines when possible.
- If no blocking issues are found, say that and mention residual risk or unverified tests.
""".strip()
        return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    if name == "release_readiness":
        base = arguments.get("base", "origin/main")
        repo = arguments.get("repo")
        repo_text = f" against {repo}" if repo else ""
        text = f"""
Run a release readiness review{repo_text} using base ref {base}.

Use the build and release MCP tools in this order:
1. release_generate_risk_summary with base={base}.
2. release_check_migrations with base={base}.
3. deps_inspect_lockfile_changes and deps_check_changed_manifests with base={base}.
4. actions_detect_unpinned_actions and actions_get_workflow_permissions.
5. flags_scan_repo.
6. db_detect_destructive_migrations.
7. release_check_ci_status for HEAD if GitHub access is configured.

Review stance:
- Prioritize release blockers, rollback risk, migration risk, supply-chain risk, CI gaps, and missing verification.
- Separate hard blockers from follow-up recommendations.
- Mention which tools were unavailable or unconfigured.
""".strip()
        return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    raise ToolError(f"Unknown prompt: {name}")


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if request_id is None:
        return None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "prompts": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "tools/list":
            result = tool_list()
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if tool_name not in TOOLS:
                raise ToolError(f"Unknown tool: {tool_name}")
            if not isinstance(arguments, dict):
                raise ToolError("arguments must be an object")
            handler: ToolHandler = TOOLS[tool_name]["handler"]
            result = handler(arguments)
        elif method == "prompts/list":
            result = prompt_list()
        elif method == "prompts/get":
            result = prompt_get(params)
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ToolError, OpsToolError) as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": f"Internal error: {exc}"},
        }


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            write_message(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
            )
            continue
        response = handle_request(message)
        if response is not None:
            write_message(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
