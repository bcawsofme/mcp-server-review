"""Finding lifecycle reconciliation."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

try:
    from .findings import IGNORED, OPEN, RESOLVED, Finding
except ImportError:
    from findings import IGNORED, OPEN, RESOLVED, Finding


@dataclass
class StoredFinding:
    id: str
    repo: str
    pr_number: int
    finding_id: str
    first_seen_sha: str
    last_seen_sha: str
    status: str
    severity: str
    path: str | None
    line: int | None
    summary: str
    details: str
    suggested_fix: str | None
    fix_commit: str | None
    created_at: float
    updated_at: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FindingReconciliation:
    open_findings: list[StoredFinding]
    new_findings: list[StoredFinding]
    resolved_findings: list[StoredFinding]
    ignored_findings: list[StoredFinding]


def reconcile_findings(
    store: Any,
    *,
    repo: str,
    pr_number: int,
    head_sha: str,
    findings: list[Finding],
) -> FindingReconciliation:
    timestamp = time.time()
    current_by_id = {finding.finding_id: finding for finding in findings}
    existing = {
        item.finding_id: item
        for item in store.list_findings(repo, pr_number)
    }
    new_findings: list[StoredFinding] = []
    resolved_findings: list[StoredFinding] = []

    with store.connect() as conn:
        for finding_id, finding in current_by_id.items():
            stored = existing.get(finding_id)
            if stored is None:
                row_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO findings (
                      id, repo, pr_number, finding_id, first_seen_sha, last_seen_sha,
                      status, severity, path, line, summary, details, suggested_fix,
                      fix_commit, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        repo,
                        pr_number,
                        finding_id,
                        head_sha,
                        head_sha,
                        OPEN,
                        finding.severity,
                        finding.path,
                        finding.line,
                        finding.summary,
                        finding.details,
                        finding.suggested_fix,
                        None,
                        timestamp,
                        timestamp,
                    ),
                )
                new_findings.append(
                    StoredFinding(
                        id=row_id,
                        repo=repo,
                        pr_number=pr_number,
                        finding_id=finding_id,
                        first_seen_sha=head_sha,
                        last_seen_sha=head_sha,
                        status=OPEN,
                        severity=finding.severity,
                        path=finding.path,
                        line=finding.line,
                        summary=finding.summary,
                        details=finding.details,
                        suggested_fix=finding.suggested_fix,
                        fix_commit=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                continue

            if stored.status == IGNORED:
                continue

            status = OPEN if stored.status == RESOLVED else stored.status
            conn.execute(
                """
                UPDATE findings
                SET last_seen_sha = ?, status = ?, severity = ?, path = ?, line = ?,
                    summary = ?, details = ?, suggested_fix = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    head_sha,
                    status,
                    finding.severity,
                    finding.path,
                    finding.line,
                    finding.summary,
                    finding.details,
                    finding.suggested_fix,
                    timestamp,
                    stored.id,
                ),
            )

        for finding_id, stored in existing.items():
            if stored.status != OPEN or finding_id in current_by_id:
                continue
            conn.execute(
                """
                UPDATE findings
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (RESOLVED, timestamp, stored.id),
            )
            stored.status = RESOLVED
            stored.updated_at = timestamp
            resolved_findings.append(stored)

    open_findings = store.list_findings(repo, pr_number, {OPEN})
    ignored_findings = store.list_findings(repo, pr_number, {IGNORED})
    return FindingReconciliation(
        open_findings=open_findings,
        new_findings=new_findings,
        resolved_findings=resolved_findings,
        ignored_findings=ignored_findings,
    )
