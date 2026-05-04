"""GitHub token resolution for hosted service jobs."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class GitHubAuthError(Exception):
    """GitHub authentication could not be resolved."""


@dataclass
class CachedToken:
    token: str
    expires_at: float


_token_cache: dict[int, CachedToken] = {}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _private_key_text() -> str:
    if value := os.environ.get("GITHUB_APP_PRIVATE_KEY"):
        return value.replace("\\n", "\n")
    if path := os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE"):
        return Path(path).read_text(encoding="utf-8")
    raise GitHubAuthError("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_FILE is required")


def _sign_rs256(message: str, private_key: str) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as key_file:
        key_file.write(private_key)
        key_path = key_file.name
    try:
        completed = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=message.encode("utf-8"),
            capture_output=True,
            check=False,
        )
    finally:
        Path(key_path).unlink(missing_ok=True)
    if completed.returncode != 0:
        raise GitHubAuthError(completed.stderr.decode("utf-8", errors="replace"))
    return _b64url(completed.stdout)


def github_app_jwt() -> str:
    app_id = os.environ.get("GITHUB_APP_ID")
    if not app_id:
        raise GitHubAuthError("GITHUB_APP_ID is required")

    issued_at = int(time.time()) - 60
    payload = {"iat": issued_at, "exp": issued_at + 540, "iss": app_id}
    header = {"alg": "RS256", "typ": "JWT"}
    message = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    return f"{message}.{_sign_rs256(message, _private_key_text())}"


def _api_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "build-release-mcp-server",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GitHubAuthError(f"GitHub API failed with {exc.code}: {detail}") from exc


def installation_token(installation_id: int) -> str:
    cached = _token_cache.get(installation_id)
    if cached and cached.expires_at - time.time() > 120:
        return cached.token

    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    data = _api_json(
        "POST",
        f"{api_base}/app/installations/{installation_id}/access_tokens",
        github_app_jwt(),
        {},
    )
    token = data["token"]
    # GitHub returns ISO expiry; cache conservatively for 50 minutes.
    _token_cache[installation_id] = CachedToken(token=token, expires_at=time.time() + 3000)
    return token


def has_github_app_config() -> bool:
    return bool(
        os.environ.get("GITHUB_APP_ID")
        and (os.environ.get("GITHUB_APP_PRIVATE_KEY") or os.environ.get("GITHUB_APP_PRIVATE_KEY_FILE"))
    )


def resolve_token(installation_id: int | None = None) -> str:
    if token := os.environ.get("GH_TOKEN"):
        return token
    if token := os.environ.get("GITHUB_TOKEN"):
        return token
    if installation_id is not None and has_github_app_config():
        return installation_token(installation_id)
    raise GitHubAuthError("Set GH_TOKEN/GITHUB_TOKEN or GitHub App credentials")
