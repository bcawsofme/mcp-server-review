"""SQLite-backed hosted service job store."""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ReviewJob:
    id: str
    delivery_id: str
    repo: str
    pr_url: str
    pr_number: int
    head_sha: str
    action: str
    installation_id: int | None
    status: str
    created_at: float
    updated_at: float
    error: str | None = None
    review_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  delivery_id TEXT UNIQUE NOT NULL,
                  repo TEXT NOT NULL,
                  pr_url TEXT NOT NULL,
                  pr_number INTEGER NOT NULL,
                  head_sha TEXT NOT NULL,
                  action TEXT NOT NULL,
                  installation_id INTEGER,
                  status TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  error TEXT,
                  review_hash TEXT,
                  UNIQUE(repo, pr_number, head_sha)
                )
                """
            )

    def _row_to_job(self, row: sqlite3.Row) -> ReviewJob:
        return ReviewJob(**dict(row))

    def enqueue(
        self,
        *,
        delivery_id: str,
        repo: str,
        pr_url: str,
        pr_number: int,
        head_sha: str,
        action: str,
        installation_id: int | None,
    ) -> tuple[ReviewJob, bool]:
        existing = self.get_by_delivery(delivery_id) or self.get_by_pr_head(repo, pr_number, head_sha)
        if existing is not None:
            return existing, False

        timestamp = time.time()
        job = ReviewJob(
            id=str(uuid.uuid4()),
            delivery_id=delivery_id,
            repo=repo,
            pr_url=pr_url,
            pr_number=pr_number,
            head_sha=head_sha,
            action=action,
            installation_id=installation_id,
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                  id, delivery_id, repo, pr_url, pr_number, head_sha, action,
                  installation_id, status, created_at, updated_at, error, review_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.delivery_id,
                    job.repo,
                    job.pr_url,
                    job.pr_number,
                    job.head_sha,
                    job.action,
                    job.installation_id,
                    job.status,
                    job.created_at,
                    job.updated_at,
                    job.error,
                    job.review_hash,
                ),
            )
        return job, True

    def get(self, job_id: str) -> ReviewJob | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def get_by_delivery(self, delivery_id: str) -> ReviewJob | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE delivery_id = ?", (delivery_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def get_by_pr_head(self, repo: str, pr_number: int, head_sha: str) -> ReviewJob | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE repo = ? AND pr_number = ? AND head_sha = ?",
                (repo, pr_number, head_sha),
            ).fetchone()
        return self._row_to_job(row) if row else None

    def update(self, job_id: str, status: str, error: str | None = None, review_hash: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, review_hash = COALESCE(?, review_hash), updated_at = ?
                WHERE id = ?
                """,
                (status, error, review_hash, time.time(), job_id),
            )
