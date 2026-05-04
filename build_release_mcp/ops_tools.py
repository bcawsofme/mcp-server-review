"""Build and release MCP tools.

The tools in this module are intentionally read-only. They wrap common local
CLIs and repository scans so a model can inspect release state without getting
arbitrary shell access.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_TEXT_LIMIT_BYTES = 120_000
MAX_TEXT_LIMIT_BYTES = 1_000_000


class OpsToolError(Exception):
    """A user-facing operational tool failure."""


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def repo_root() -> Path:
    configured = os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd()


def json_response(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(value, indent=2, sort_keys=True)}
        ]
    }


def run_command(args: list[str], timeout: int = 45) -> CommandResult:
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
        raise OpsToolError(f"Command not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise OpsToolError(f"Command timed out after {timeout}s: {' '.join(args)}") from exc

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise OpsToolError(f"{' '.join(args)} failed: {message}")
    return CommandResult(completed.stdout, completed.stderr, completed.returncode)


def parse_json(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OpsToolError(f"Command returned invalid JSON: {exc}") from exc


def truncate_text(text: str, limit_bytes: int = DEFAULT_TEXT_LIMIT_BYTES) -> dict[str, Any]:
    limit = max(1, min(limit_bytes, MAX_TEXT_LIMIT_BYTES))
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return {"text": text, "truncated": False, "bytes": len(encoded)}
    clipped = encoded[:limit].decode("utf-8", errors="ignore")
    return {
        "text": clipped,
        "truncated": True,
        "bytes": len(encoded),
        "returnedBytes": len(clipped.encode("utf-8")),
        "limitBytes": limit,
    }


def normalize_repo(repo: Any) -> str | None:
    if repo is None:
        return None
    if not isinstance(repo, str) or not repo.strip():
        raise OpsToolError("repo must be an owner/name string")
    value = repo.strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        raise OpsToolError("repo must look like owner/name")
    return value


def repo_args(repo: str | None) -> list[str]:
    return ["--repo", repo] if repo else []


def normalize_int(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int):
        raise OpsToolError(f"{name} must be an integer")
    return max(minimum, min(value, maximum))


def normalize_string(value: Any, name: str, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise OpsToolError(f"{name} is required")
        return default
    if not isinstance(value, str) or not value.strip():
        raise OpsToolError(f"{name} must be a non-empty string")
    return value.strip()


def optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return normalize_string(value, name)


def changed_files(base: str, head: str = "HEAD") -> list[str]:
    result = run_command(["git", "diff", "--name-only", f"{base}...{head}"])
    return [line for line in result.stdout.splitlines() if line.strip()]


def list_files(patterns: tuple[str, ...]) -> list[Path]:
    root = repo_root()
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in root.rglob(pattern) if path.is_file())
    return sorted(set(files))


def rel(path: Path) -> str:
    return str(path.relative_to(repo_root()))


def read_file(path: Path, limit_bytes: int = DEFAULT_TEXT_LIMIT_BYTES) -> str:
    return truncate_text(path.read_text(encoding="utf-8", errors="replace"), limit_bytes)[
        "text"
    ]


def tool_ci_list_failed_runs(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    limit = normalize_int(arguments.get("limit"), "limit", 20, 1, 100)
    branch = optional_string(arguments.get("branch"), "branch")
    args = [
        "gh",
        "run",
        "list",
        *repo_args(repo),
        "--status",
        "failure",
        "--limit",
        str(limit),
        "--json",
        "databaseId,displayTitle,event,headBranch,headSha,name,status,conclusion,createdAt,updatedAt,url,workflowName",
    ]
    if branch:
        args.extend(["--branch", branch])
    return json_response(parse_json(run_command(args).stdout))


def tool_ci_get_run_jobs(arguments: dict[str, Any]) -> dict[str, Any]:
    run_id = normalize_string(arguments.get("run_id"), "run_id")
    repo = normalize_repo(arguments.get("repo"))
    result = run_command(
        ["gh", "run", "view", run_id, *repo_args(repo), "--json", "jobs,conclusion,status,url"]
    )
    return json_response(parse_json(result.stdout))


def tool_ci_get_job_logs(arguments: dict[str, Any]) -> dict[str, Any]:
    run_id = normalize_string(arguments.get("run_id"), "run_id")
    repo = normalize_repo(arguments.get("repo"))
    limit = normalize_int(
        arguments.get("max_bytes"), "max_bytes", DEFAULT_TEXT_LIMIT_BYTES, 1, MAX_TEXT_LIMIT_BYTES
    )
    result = run_command(["gh", "run", "view", run_id, *repo_args(repo), "--log"], timeout=120)
    return json_response(truncate_text(result.stdout, limit))


def tool_ci_compare_last_green_run(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    workflow = optional_string(arguments.get("workflow"), "workflow")
    branch = optional_string(arguments.get("branch"), "branch")
    args = [
        "gh",
        "run",
        "list",
        *repo_args(repo),
        "--status",
        "success",
        "--limit",
        "1",
        "--json",
        "databaseId,displayTitle,headBranch,headSha,createdAt,url,workflowName",
    ]
    if workflow:
        args.extend(["--workflow", workflow])
    if branch:
        args.extend(["--branch", branch])
    runs = parse_json(run_command(args).stdout)
    if not runs:
        return json_response({"lastGreenRun": None, "changedFilesSinceLastGreen": []})
    last_green = runs[0]
    files = changed_files(last_green["headSha"], "HEAD")
    return json_response({"lastGreenRun": last_green, "changedFilesSinceLastGreen": files})


def tool_ci_find_flaky_tests(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    workflow = optional_string(arguments.get("workflow"), "workflow")
    limit = normalize_int(arguments.get("limit"), "limit", 30, 1, 100)
    args = [
        "gh",
        "run",
        "list",
        *repo_args(repo),
        "--limit",
        str(limit),
        "--json",
        "databaseId,conclusion,displayTitle,headBranch,headSha,url,workflowName",
    ]
    if workflow:
        args.extend(["--workflow", workflow])
    runs = parse_json(run_command(args).stdout)
    by_title: dict[str, dict[str, Any]] = {}
    for run in runs:
        key = f"{run.get('workflowName')}::{run.get('displayTitle')}"
        entry = by_title.setdefault(key, {"runs": [], "successes": 0, "failures": 0})
        entry["runs"].append(run)
        if run.get("conclusion") == "success":
            entry["successes"] += 1
        if run.get("conclusion") == "failure":
            entry["failures"] += 1
    candidates = [
        {"key": key, **value}
        for key, value in by_title.items()
        if value["successes"] > 0 and value["failures"] > 0
    ]
    return json_response({"candidates": candidates, "sampleSize": len(runs)})


def tool_release_prs_since_last_release(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    base = optional_string(arguments.get("base"), "base")
    limit = normalize_int(arguments.get("limit"), "limit", 100, 1, 200)
    if not base:
        tags = run_command(["git", "tag", "--sort=-creatordate"]).stdout.splitlines()
        base = tags[0] if tags else None
    if not base:
        raise OpsToolError("No base was provided and no git tags exist")
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            *repo_args(repo),
            "--state",
            "merged",
            "--limit",
            str(limit),
            "--json",
            "number,title,author,labels,mergedAt,url,baseRefName,headRefName",
        ]
    )
    return json_response({"base": base, "mergedPullRequests": parse_json(result.stdout)})


def tool_release_check_required_labels(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    label_value = arguments.get("required_labels", ["release-notes"])
    if not isinstance(label_value, list) or not all(isinstance(item, str) for item in label_value):
        raise OpsToolError("required_labels must be an array of strings")
    prs = parse_json(
        run_command(
            [
                "gh",
                "pr",
                "list",
                *repo_args(repo),
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,title,labels,url",
            ]
        ).stdout
    )
    missing = []
    for pr in prs:
        labels = {label.get("name") for label in pr.get("labels", [])}
        missing_labels = [label for label in label_value if label not in labels]
        if missing_labels:
            missing.append({**pr, "missingLabels": missing_labels})
    return json_response({"requiredLabels": label_value, "missing": missing})


def tool_release_check_ci_status(arguments: dict[str, Any]) -> dict[str, Any]:
    ref = normalize_string(arguments.get("ref"), "ref", "HEAD")
    repo = normalize_repo(arguments.get("repo"))
    sha = run_command(["git", "rev-parse", ref]).stdout.strip()
    result = run_command(
        [
            "gh",
            "api",
            *repo_args(repo),
            f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
        ]
    )
    return json_response({"ref": ref, "sha": sha, "checkRuns": parse_json(result.stdout)})


def tool_release_check_migrations(arguments: dict[str, Any]) -> dict[str, Any]:
    base = normalize_string(arguments.get("base"), "base", "origin/main")
    files = changed_files(base)
    migration_patterns = (
        "migration",
        "migrations",
        "flyway",
        "liquibase",
        "schema",
        ".sql",
    )
    migrations = [
        file
        for file in files
        if any(pattern in file.lower() for pattern in migration_patterns)
    ]
    return json_response({"base": base, "changedMigrationFiles": migrations})


def tool_release_generate_risk_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    base = normalize_string(arguments.get("base"), "base", "origin/main")
    files = changed_files(base)
    risk_rules = {
        "database": ("migration", "migrations", ".sql", "schema"),
        "ci": (".github/workflows", "Jenkinsfile", "buildkite", "circleci"),
        "dependencies": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"),
        "infra": ("infra/", "k8s", "helm", "terraform", "Dockerfile"),
        "security": ("auth", "permission", "jwt", "secret", "security"),
    }
    categories: dict[str, list[str]] = {key: [] for key in risk_rules}
    for file in files:
        lower = file.lower()
        for category, needles in risk_rules.items():
            if any(needle.lower() in lower for needle in needles):
                categories[category].append(file)
    return json_response({"base": base, "changedFiles": files, "riskCategories": categories})


def tool_deploy_get_environment_versions(arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = optional_string(arguments.get("namespace"), "namespace")
    selector = optional_string(arguments.get("selector"), "selector")
    args = ["kubectl", "get", "deployments", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    if selector:
        args.extend(["-l", selector])
    deployments = parse_json(run_command(args).stdout)
    versions = []
    for item in deployments.get("items", []):
        containers = item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        versions.append(
            {
                "namespace": item.get("metadata", {}).get("namespace"),
                "name": item.get("metadata", {}).get("name"),
                "images": [container.get("image") for container in containers],
            }
        )
    return json_response(versions)


def tool_deploy_get_current_image_tags(arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = optional_string(arguments.get("namespace"), "namespace")
    args = ["kubectl", "get", "pods", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    pods = parse_json(run_command(args).stdout)
    images = sorted(
        {
            container.get("image")
            for item in pods.get("items", [])
            for container in item.get("spec", {}).get("containers", [])
            if container.get("image")
        }
    )
    return json_response({"namespace": namespace or "current", "images": images})


def tool_deploy_get_recent_deployments(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    limit = normalize_int(arguments.get("limit"), "limit", 20, 1, 100)
    env = optional_string(arguments.get("environment"), "environment")
    args = ["gh", "api", *repo_args(repo), "repos/{owner}/{repo}/deployments", "-F", f"per_page={limit}"]
    if env:
        args.extend(["-F", f"environment={env}"])
    return json_response(parse_json(run_command(args).stdout))


def tool_deploy_compare_deployed_vs_main(arguments: dict[str, Any]) -> dict[str, Any]:
    deployed_ref = normalize_string(arguments.get("deployed_ref"), "deployed_ref")
    target_ref = normalize_string(arguments.get("target_ref"), "target_ref", "origin/main")
    files = changed_files(deployed_ref, target_ref)
    ahead = run_command(["git", "rev-list", "--count", f"{deployed_ref}..{target_ref}"]).stdout.strip()
    behind = run_command(["git", "rev-list", "--count", f"{target_ref}..{deployed_ref}"]).stdout.strip()
    return json_response(
        {
            "deployedRef": deployed_ref,
            "targetRef": target_ref,
            "commitsAhead": int(ahead),
            "commitsBehind": int(behind),
            "changedFiles": files,
        }
    )


def tool_actions_list_workflows(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    result = run_command(
        ["gh", "workflow", "list", *repo_args(repo), "--all", "--json", "id,name,path,state"]
    )
    return json_response(parse_json(result.stdout))


def tool_actions_get_workflow_permissions(arguments: dict[str, Any]) -> dict[str, Any]:
    workflows = []
    for path in list_files(("*.yml", "*.yaml")):
        relative = rel(path)
        if ".github/workflows/" not in relative:
            continue
        text = read_file(path)
        permissions = []
        capture = False
        for line in text.splitlines():
            if line.startswith("permissions:"):
                capture = True
                permissions.append(line)
                continue
            if capture:
                if line and not line.startswith((" ", "-")):
                    break
                permissions.append(line)
        workflows.append({"path": relative, "permissionsBlock": "\n".join(permissions)})
    return json_response(workflows)


def tool_actions_detect_unpinned_actions(arguments: dict[str, Any]) -> dict[str, Any]:
    findings = []
    action_pattern = re.compile(r"uses:\s*([^@\s]+)@([^\s#]+)")
    for path in list_files(("*.yml", "*.yaml")):
        relative = rel(path)
        if ".github/workflows/" not in relative:
            continue
        for index, line in enumerate(read_file(path).splitlines(), start=1):
            match = action_pattern.search(line)
            if not match:
                continue
            ref = match.group(2)
            pinned = bool(re.fullmatch(r"[a-f0-9]{40}", ref))
            if not pinned:
                findings.append(
                    {
                        "path": relative,
                        "line": index,
                        "action": match.group(1),
                        "ref": ref,
                        "reason": "Action is not pinned to a full commit SHA.",
                    }
                )
    return json_response({"unpinnedActions": findings})


def tool_deps_inspect_lockfile_changes(arguments: dict[str, Any]) -> dict[str, Any]:
    base = normalize_string(arguments.get("base"), "base", "origin/main")
    lock_names = (
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "go.sum",
        "Cargo.lock",
    )
    files = [file for file in changed_files(base) if file.endswith(lock_names)]
    return json_response({"base": base, "changedLockfiles": files})


def tool_deps_check_changed_manifests(arguments: dict[str, Any]) -> dict[str, Any]:
    base = normalize_string(arguments.get("base"), "base", "origin/main")
    manifest_names = (
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "pom.xml",
        "build.gradle",
        "go.mod",
        "Cargo.toml",
    )
    files = [file for file in changed_files(base) if file.endswith(manifest_names)]
    return json_response({"base": base, "changedDependencyManifests": files})


def tool_deps_find_unpinned_container_images(arguments: dict[str, Any]) -> dict[str, Any]:
    findings = []
    image_pattern = re.compile(r"\bimage:\s*['\"]?([^'\"\s]+)")
    for path in list_files(("*.yaml", "*.yml", "Dockerfile")):
        relative = rel(path)
        text = read_file(path)
        for index, line in enumerate(text.splitlines(), start=1):
            match = image_pattern.search(line)
            if not match:
                continue
            image = match.group(1)
            if "@sha256:" not in image:
                findings.append({"path": relative, "line": index, "image": image})
    return json_response({"unpinnedImages": findings})


def tool_image_inspect(arguments: dict[str, Any]) -> dict[str, Any]:
    image = normalize_string(arguments.get("image"), "image")
    result = run_command(["docker", "image", "inspect", image])
    return json_response(parse_json(result.stdout))


def tool_image_get_digest(arguments: dict[str, Any]) -> dict[str, Any]:
    image = normalize_string(arguments.get("image"), "image")
    result = run_command(["docker", "manifest", "inspect", image], timeout=60)
    manifest = parse_json(result.stdout)
    return json_response({"image": image, "manifest": manifest})


def tool_k8s_get_deployments(arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = optional_string(arguments.get("namespace"), "namespace")
    args = ["kubectl", "get", "deployments", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    return json_response(parse_json(run_command(args).stdout))


def tool_k8s_get_pods(arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = optional_string(arguments.get("namespace"), "namespace")
    selector = optional_string(arguments.get("selector"), "selector")
    args = ["kubectl", "get", "pods", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    if selector:
        args.extend(["-l", selector])
    return json_response(parse_json(run_command(args).stdout))


def tool_k8s_get_events(arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = optional_string(arguments.get("namespace"), "namespace")
    args = ["kubectl", "get", "events", "--sort-by=.lastTimestamp", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    return json_response(parse_json(run_command(args).stdout))


def tool_k8s_rollout_status(arguments: dict[str, Any]) -> dict[str, Any]:
    deployment = normalize_string(arguments.get("deployment"), "deployment")
    namespace = optional_string(arguments.get("namespace"), "namespace")
    args = ["kubectl", "rollout", "status", f"deployment/{deployment}", "--timeout=10s"]
    if namespace:
        args.extend(["-n", namespace])
    result = run_command(args, timeout=15)
    return json_response({"deployment": deployment, "namespace": namespace, "status": result.stdout.strip()})


def tool_flags_scan_repo(arguments: dict[str, Any]) -> dict[str, Any]:
    patterns = [
        re.compile(r"AVANTI_FEATURE_[A-Z0-9_]+"),
        re.compile(r"feature(?:Flag|_flag)?[\"']?\s*[:=]\s*[\"']([^\"']+)"),
    ]
    findings = []
    for path in list_files(("*.ts", "*.tsx", "*.js", "*.jsx", "*.py", "*.java", "*.properties", "*.env", "*.yaml", "*.yml")):
        if ".git/" in str(path):
            continue
        text = read_file(path, 300_000)
        for index, line in enumerate(text.splitlines(), start=1):
            matches = []
            for pattern in patterns:
                matches.extend(match.group(0) for match in pattern.finditer(line))
            if matches:
                findings.append({"path": rel(path), "line": index, "matches": matches})
    return json_response({"featureFlagReferences": findings})


def tool_flags_compare_env_files(arguments: dict[str, Any]) -> dict[str, Any]:
    left = repo_root() / normalize_string(arguments.get("left"), "left")
    right = repo_root() / normalize_string(arguments.get("right"), "right")
    if not left.exists() or not right.exists():
        raise OpsToolError("Both env files must exist")
    key_pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
    left_keys = {match.group(1) for line in read_file(left).splitlines() if (match := key_pattern.match(line))}
    right_keys = {match.group(1) for line in read_file(right).splitlines() if (match := key_pattern.match(line))}
    return json_response(
        {
            "left": rel(left),
            "right": rel(right),
            "onlyLeft": sorted(left_keys - right_keys),
            "onlyRight": sorted(right_keys - left_keys),
            "common": sorted(left_keys & right_keys),
        }
    )


def tool_db_list_migration_files(arguments: dict[str, Any]) -> dict[str, Any]:
    patterns = ("*.sql", "*migration*", "*migrations*", "*changelog*")
    files = [rel(path) for path in list_files(patterns)]
    return json_response({"migrationFiles": sorted(set(files))})


def tool_db_detect_destructive_migrations(arguments: dict[str, Any]) -> dict[str, Any]:
    destructive = re.compile(
        r"\b(drop\s+table|drop\s+column|truncate\s+table|delete\s+from|alter\s+table\s+.*\s+drop)\b",
        re.IGNORECASE,
    )
    findings = []
    for path in list_files(("*.sql",)):
        for index, line in enumerate(read_file(path).splitlines(), start=1):
            if destructive.search(line):
                findings.append({"path": rel(path), "line": index, "statement": line.strip()})
    return json_response({"destructiveMigrationFindings": findings})


def tool_db_changed_migrations(arguments: dict[str, Any]) -> dict[str, Any]:
    base = normalize_string(arguments.get("base"), "base", "origin/main")
    migrations = [
        file
        for file in changed_files(base)
        if file.endswith(".sql") or "migration" in file.lower() or "changelog" in file.lower()
    ]
    return json_response({"base": base, "changedMigrations": migrations})


def tool_obs_query_prometheus(arguments: dict[str, Any]) -> dict[str, Any]:
    base_url = normalize_string(
        arguments.get("base_url") or os.environ.get("PROMETHEUS_BASE_URL"),
        "base_url",
    ).rstrip("/")
    query = normalize_string(arguments.get("query"), "query")
    url = f"{base_url}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json_response(json.loads(response.read().decode("utf-8")))


def tool_obs_recent_k8s_warnings(arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = optional_string(arguments.get("namespace"), "namespace")
    args = ["kubectl", "get", "events", "--field-selector", "type=Warning", "--sort-by=.lastTimestamp", "-o", "json"]
    if namespace:
        args.extend(["-n", namespace])
    return json_response(parse_json(run_command(args).stdout))


def tool_release_notes_collect_merged_prs(arguments: dict[str, Any]) -> dict[str, Any]:
    repo = normalize_repo(arguments.get("repo"))
    limit = normalize_int(arguments.get("limit"), "limit", 100, 1, 200)
    search = optional_string(arguments.get("search"), "search")
    query = search or "is:pr is:merged sort:updated-desc"
    result = run_command(
        [
            "gh",
            "search",
            "prs",
            query,
            *repo_args(repo),
            "--limit",
            str(limit),
            "--json",
            "number,title,author,labels,mergedAt,url",
        ]
    )
    return json_response(parse_json(result.stdout))


def tool_release_notes_group_by_label(arguments: dict[str, Any]) -> dict[str, Any]:
    prs = arguments.get("pull_requests")
    if not isinstance(prs, list):
        raise OpsToolError("pull_requests must be an array of PR objects")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        labels = pr.get("labels") or [{"name": "unlabeled"}]
        for label in labels:
            name = label.get("name") if isinstance(label, dict) else str(label)
            grouped.setdefault(name or "unlabeled", []).append(pr)
    return json_response(grouped)


def tool_codeowners_for_paths(arguments: dict[str, Any]) -> dict[str, Any]:
    paths = arguments.get("paths")
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise OpsToolError("paths must be an array of strings")
    candidates = [
        repo_root() / ".github" / "CODEOWNERS",
        repo_root() / "CODEOWNERS",
        repo_root() / "docs" / "CODEOWNERS",
    ]
    codeowners = next((path for path in candidates if path.exists()), None)
    if codeowners is None:
        return json_response({"codeownersFile": None, "matches": []})
    rules = []
    for line in read_file(codeowners).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            rules.append({"pattern": parts[0], "owners": parts[1:]})
    matches = []
    for target in paths:
        owners = [rule for rule in rules if rule["pattern"].strip("/") in target]
        matches.append({"path": target, "matchingRules": owners})
    return json_response({"codeownersFile": rel(codeowners), "matches": matches})


def tool_docs_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = normalize_string(arguments.get("query"), "query").lower()
    limit = normalize_int(arguments.get("limit"), "limit", 20, 1, 100)
    findings = []
    for path in list_files(("*.md", "*.mdx", "*.rst", "*.txt")):
        text = read_file(path, 300_000)
        for index, line in enumerate(text.splitlines(), start=1):
            if query in line.lower():
                findings.append({"path": rel(path), "line": index, "text": line.strip()})
                if len(findings) >= limit:
                    return json_response({"query": query, "matches": findings})
    return json_response({"query": query, "matches": findings})


def tool_project_extract_ticket_refs(arguments: dict[str, Any]) -> dict[str, Any]:
    base = normalize_string(arguments.get("base"), "base", "origin/main")
    pattern = re.compile(normalize_string(arguments.get("pattern"), "pattern", r"[A-Z]+-\d+"))
    commits = run_command(["git", "log", "--format=%s", f"{base}..HEAD"]).stdout.splitlines()
    refs = sorted({match.group(0) for commit in commits for match in pattern.finditer(commit)})
    return json_response({"base": base, "ticketRefs": refs, "commitSubjects": commits})


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def tool(
    description: str,
    handler: ToolHandler,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "handler": handler,
        "inputSchema": schema(properties, required),
    }


REPO_PROP = {"type": "string", "description": "Optional GitHub repo as owner/name."}
BASE_PROP = {"type": "string", "description": "Base ref for git comparisons."}
NAMESPACE_PROP = {"type": "string", "description": "Optional Kubernetes namespace."}


OPS_TOOLS: dict[str, dict[str, Any]] = {
    "ci_list_failed_runs": tool(
        "List recent failed GitHub Actions workflow runs.",
        tool_ci_list_failed_runs,
        {"repo": REPO_PROP, "branch": {"type": "string"}, "limit": {"type": "integer"}},
    ),
    "ci_get_run_jobs": tool(
        "Get jobs for a GitHub Actions run.",
        tool_ci_get_run_jobs,
        {"repo": REPO_PROP, "run_id": {"type": "string"}},
        ["run_id"],
    ),
    "ci_get_job_logs": tool(
        "Fetch GitHub Actions logs for a run, truncated to max_bytes.",
        tool_ci_get_job_logs,
        {"repo": REPO_PROP, "run_id": {"type": "string"}, "max_bytes": {"type": "integer"}},
        ["run_id"],
    ),
    "ci_compare_last_green_run": tool(
        "Compare HEAD with the latest successful run for a workflow or branch.",
        tool_ci_compare_last_green_run,
        {"repo": REPO_PROP, "workflow": {"type": "string"}, "branch": {"type": "string"}},
    ),
    "ci_find_flaky_tests": tool(
        "Find workflow run titles that have both succeeded and failed in recent history.",
        tool_ci_find_flaky_tests,
        {"repo": REPO_PROP, "workflow": {"type": "string"}, "limit": {"type": "integer"}},
    ),
    "release_prs_since_last_release": tool(
        "Collect merged PRs, defaulting the base to the latest git tag.",
        tool_release_prs_since_last_release,
        {"repo": REPO_PROP, "base": {"type": "string"}, "limit": {"type": "integer"}},
    ),
    "release_check_required_labels": tool(
        "Check open PRs for required labels.",
        tool_release_check_required_labels,
        {"repo": REPO_PROP, "required_labels": {"type": "array", "items": {"type": "string"}}},
    ),
    "release_check_ci_status": tool(
        "Read GitHub check runs for a git ref.",
        tool_release_check_ci_status,
        {"repo": REPO_PROP, "ref": {"type": "string"}},
    ),
    "release_check_migrations": tool(
        "List changed migration-like files since a base ref.",
        tool_release_check_migrations,
        {"base": BASE_PROP},
    ),
    "release_generate_risk_summary": tool(
        "Categorize changed files into release risk buckets.",
        tool_release_generate_risk_summary,
        {"base": BASE_PROP},
    ),
    "deploy_get_environment_versions": tool(
        "Read Kubernetes deployments and their container images.",
        tool_deploy_get_environment_versions,
        {"namespace": NAMESPACE_PROP, "selector": {"type": "string"}},
    ),
    "deploy_get_current_image_tags": tool(
        "Read unique container images currently running in Kubernetes pods.",
        tool_deploy_get_current_image_tags,
        {"namespace": NAMESPACE_PROP},
    ),
    "deploy_get_recent_deployments": tool(
        "Read recent GitHub deployments.",
        tool_deploy_get_recent_deployments,
        {"repo": REPO_PROP, "environment": {"type": "string"}, "limit": {"type": "integer"}},
    ),
    "deploy_compare_deployed_vs_main": tool(
        "Compare a deployed ref with a target ref.",
        tool_deploy_compare_deployed_vs_main,
        {"deployed_ref": {"type": "string"}, "target_ref": {"type": "string"}},
        ["deployed_ref"],
    ),
    "actions_list_workflows": tool(
        "List GitHub Actions workflows.",
        tool_actions_list_workflows,
        {"repo": REPO_PROP},
    ),
    "actions_get_workflow_permissions": tool(
        "Extract permissions blocks from local GitHub Actions workflows.",
        tool_actions_get_workflow_permissions,
        {},
    ),
    "actions_detect_unpinned_actions": tool(
        "Find workflow actions not pinned to full commit SHAs.",
        tool_actions_detect_unpinned_actions,
        {},
    ),
    "deps_inspect_lockfile_changes": tool(
        "List lockfiles changed since a base ref.",
        tool_deps_inspect_lockfile_changes,
        {"base": BASE_PROP},
    ),
    "deps_check_changed_manifests": tool(
        "List dependency manifest files changed since a base ref.",
        tool_deps_check_changed_manifests,
        {"base": BASE_PROP},
    ),
    "deps_find_unpinned_container_images": tool(
        "Find Kubernetes image references not pinned by digest.",
        tool_deps_find_unpinned_container_images,
        {},
    ),
    "image_inspect": tool(
        "Inspect a local Docker image.",
        tool_image_inspect,
        {"image": {"type": "string"}},
        ["image"],
    ),
    "image_get_digest": tool(
        "Inspect an image manifest through Docker.",
        tool_image_get_digest,
        {"image": {"type": "string"}},
        ["image"],
    ),
    "k8s_get_deployments": tool(
        "Read Kubernetes deployments.",
        tool_k8s_get_deployments,
        {"namespace": NAMESPACE_PROP},
    ),
    "k8s_get_pods": tool(
        "Read Kubernetes pods.",
        tool_k8s_get_pods,
        {"namespace": NAMESPACE_PROP, "selector": {"type": "string"}},
    ),
    "k8s_get_events": tool(
        "Read Kubernetes events sorted by timestamp.",
        tool_k8s_get_events,
        {"namespace": NAMESPACE_PROP},
    ),
    "k8s_rollout_status": tool(
        "Read rollout status for a Kubernetes deployment.",
        tool_k8s_rollout_status,
        {"namespace": NAMESPACE_PROP, "deployment": {"type": "string"}},
        ["deployment"],
    ),
    "flags_scan_repo": tool(
        "Scan the repository for feature flag references.",
        tool_flags_scan_repo,
        {},
    ),
    "flags_compare_env_files": tool(
        "Compare keys present in two env-style files.",
        tool_flags_compare_env_files,
        {"left": {"type": "string"}, "right": {"type": "string"}},
        ["left", "right"],
    ),
    "db_list_migration_files": tool(
        "List migration-like files in the repository.",
        tool_db_list_migration_files,
        {},
    ),
    "db_detect_destructive_migrations": tool(
        "Scan SQL migrations for destructive statements.",
        tool_db_detect_destructive_migrations,
        {},
    ),
    "db_changed_migrations": tool(
        "List changed migration files since a base ref.",
        tool_db_changed_migrations,
        {"base": BASE_PROP},
    ),
    "obs_query_prometheus": tool(
        "Run a Prometheus instant query against PROMETHEUS_BASE_URL or base_url.",
        tool_obs_query_prometheus,
        {"base_url": {"type": "string"}, "query": {"type": "string"}},
        ["query"],
    ),
    "obs_recent_k8s_warnings": tool(
        "Read recent Kubernetes warning events.",
        tool_obs_recent_k8s_warnings,
        {"namespace": NAMESPACE_PROP},
    ),
    "release_notes_collect_merged_prs": tool(
        "Collect merged PRs for release notes through GitHub search.",
        tool_release_notes_collect_merged_prs,
        {"repo": REPO_PROP, "search": {"type": "string"}, "limit": {"type": "integer"}},
    ),
    "release_notes_group_by_label": tool(
        "Group PR objects by label for release notes.",
        tool_release_notes_group_by_label,
        {"pull_requests": {"type": "array"}},
        ["pull_requests"],
    ),
    "codeowners_for_paths": tool(
        "Find CODEOWNERS rules that match paths.",
        tool_codeowners_for_paths,
        {"paths": {"type": "array", "items": {"type": "string"}}},
        ["paths"],
    ),
    "docs_search": tool(
        "Search local documentation files for text.",
        tool_docs_search,
        {"query": {"type": "string"}, "limit": {"type": "integer"}},
        ["query"],
    ),
    "project_extract_ticket_refs": tool(
        "Extract ticket references from commit subjects since a base ref.",
        tool_project_extract_ticket_refs,
        {"base": BASE_PROP, "pattern": {"type": "string"}},
    ),
}
