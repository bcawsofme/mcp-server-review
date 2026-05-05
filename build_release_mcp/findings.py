"""Structured PR review findings and reconciliation helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any


OPEN = "open"
RESOLVED = "resolved"
IGNORED = "ignored"
FINDING_STATUSES = {OPEN, RESOLVED, IGNORED}
FINDING_SEVERITIES = {"critical", "high", "medium", "low"}


@dataclass
class Finding:
    finding_id: str
    severity: str
    path: str | None
    line: int | None
    summary: str
    details: str
    suggested_fix: str | None = None
    status: str = OPEN

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_path(value: Any) -> str | None:
    if value is None:
        return None
    text = normalize_text(value)
    return text or None


def normalize_line(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        line = int(value)
    except (TypeError, ValueError):
        return None
    return line if line > 0 else None


def normalize_severity(value: Any) -> str:
    severity = normalize_text(value).lower()
    return severity if severity in FINDING_SEVERITIES else "medium"


def finding_fingerprint(
    *,
    path: str | None,
    line: int | None,
    summary: str,
    details: str = "",
) -> str:
    basis = {
        "path": path or "",
        "line": line or 0,
        "summary": normalize_text(summary).lower(),
        "details": normalize_text(details).lower()[:240],
    }
    encoded = json.dumps(basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def coerce_finding(item: dict[str, Any]) -> Finding | None:
    summary = normalize_text(item.get("summary"))
    details = normalize_text(item.get("details"))
    if not summary:
        return None

    path = normalize_path(item.get("path") or item.get("file"))
    line = normalize_line(item.get("line"))
    finding_id = normalize_text(item.get("finding_id") or item.get("id"))
    if not finding_id:
        finding_id = finding_fingerprint(path=path, line=line, summary=summary, details=details)

    status = normalize_text(item.get("status") or OPEN).lower()
    if status not in FINDING_STATUSES:
        status = OPEN

    suggested_fix = normalize_text(item.get("suggested_fix") or item.get("fix"))
    return Finding(
        finding_id=finding_id,
        severity=normalize_severity(item.get("severity")),
        path=path,
        line=line,
        summary=summary,
        details=details,
        suggested_fix=suggested_fix or None,
        status=status,
    )


def coerce_findings(items: Any) -> list[Finding]:
    if not isinstance(items, list):
        return []

    findings: list[Finding] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        finding = coerce_finding(item)
        if finding is None or finding.finding_id in seen:
            continue
        seen.add(finding.finding_id)
        findings.append(finding)
    return findings


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        blocks = stripped.split("```")
        for block in blocks[1::2]:
            candidate = block.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                return json.loads(candidate)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    return json.loads(stripped)

