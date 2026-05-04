"""Repository configuration loading for build-release MCP."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any


CONFIG_FILENAMES = (".build-release-mcp.yml", ".build-release-mcp.yaml", ".build-release-mcp.json")


class ConfigError(Exception):
    """Configuration could not be loaded or parsed."""


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if value.isdigit():
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse a small YAML subset used by this project without external deps."""
    result: dict[str, Any] = {}
    current_section: str | None = None
    current_list_key: str | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if not line.startswith(" "):
            current_list_key = None
            if ":" not in line:
                raise ConfigError(f"Invalid config line: {raw}")
            key, value = line.split(":", 1)
            key = key.strip()
            if value.strip():
                result[key] = _parse_scalar(value)
                current_section = None
            else:
                result[key] = {}
                current_section = key
            continue

        if current_section is None:
            raise ConfigError(f"Nested config line has no section: {raw}")

        stripped = line.strip()
        section = result.setdefault(current_section, {})
        if not isinstance(section, dict):
            raise ConfigError(f"Config section is not an object: {current_section}")

        if stripped.startswith("- "):
            if current_list_key is None:
                raise ConfigError(f"List item has no key: {raw}")
            section.setdefault(current_list_key, []).append(_parse_scalar(stripped[2:]))
            continue

        if ":" not in stripped:
            raise ConfigError(f"Invalid nested config line: {raw}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if value.strip():
            section[key] = _parse_scalar(value)
            current_list_key = None
        else:
            section[key] = []
            current_list_key = key

    return result


def parse_config(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        return json.loads(stripped)
    return parse_simple_yaml(stripped)


def load_local_config(root: Path | None = None) -> dict[str, Any]:
    root = root or Path(os.environ.get("BUILD_RELEASE_MCP_REPO_ROOT", os.getcwd()))
    for filename in CONFIG_FILENAMES:
        path = root / filename
        if path.exists():
            return parse_config(path.read_text(encoding="utf-8"))
    return {}


def load_repo_config(repo: str, ref: str | None, env: dict[str, str] | None = None) -> dict[str, Any]:
    for filename in CONFIG_FILENAMES:
        endpoint = f"repos/{repo}/contents/{filename}"
        args = ["gh", "api", endpoint]
        if ref:
            args.extend(["-F", f"ref={ref}"])
        completed = subprocess.run(
            args,
            env=env or os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            continue
        data = json.loads(completed.stdout)
        content = base64.b64decode(data["content"]).decode("utf-8")
        return parse_config(content)
    return {}


def get_path(config: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = config
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def review_enabled(config: dict[str, Any]) -> bool:
    return bool(get_path(config, ("pr_review", "enabled"), True))


def review_max_diff_bytes(config: dict[str, Any], fallback: int) -> int:
    value = get_path(config, ("pr_review", "max_diff_bytes"), fallback)
    return int(value)


def review_ignored_paths(config: dict[str, Any]) -> list[str]:
    value = get_path(config, ("pr_review", "ignored_paths"), [])
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def review_model(config: dict[str, Any]) -> str | None:
    value = get_path(config, ("pr_review", "model"), None) or config.get("model")
    return str(value) if value else None
