import tempfile
import unittest
from pathlib import Path

from build_release_mcp.findings import Finding, IGNORED, OPEN, RESOLVED
from build_release_mcp.job_store import JobStore


class JobStoreTests(unittest.TestCase):
    def test_enqueue_deduplicates_delivery_and_head_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")

            first, created_first = store.enqueue(
                delivery_id="delivery",
                repo="owner/repo",
                pr_url="https://github.com/owner/repo/pull/1",
                pr_number=1,
                head_sha="abc",
                action="opened",
                installation_id=123,
            )
            second, created_second = store.enqueue(
                delivery_id="delivery",
                repo="owner/repo",
                pr_url="https://github.com/owner/repo/pull/1",
                pr_number=1,
                head_sha="abc",
                action="opened",
                installation_id=123,
            )

            self.assertTrue(created_first)
            self.assertFalse(created_second)
            self.assertEqual(first.id, second.id)

            store.update(first.id, "completed", review_hash="hash")
            updated = store.get(first.id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated.status, "completed")
            self.assertEqual(updated.review_hash, "hash")

    def test_reconcile_findings_tracks_new_resolved_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")

            first = store.reconcile_findings(
                repo="owner/repo",
                pr_number=1,
                head_sha="sha1",
                findings=[
                    Finding(
                        finding_id="bug-1",
                        severity="high",
                        path="app.py",
                        line=10,
                        summary="Bug one",
                        details="This is bad.",
                    ),
                    Finding(
                        finding_id="bug-2",
                        severity="medium",
                        path="test_app.py",
                        line=20,
                        summary="Missing test",
                        details="This needs coverage.",
                    ),
                ],
            )

            self.assertEqual({item.finding_id for item in first.new_findings}, {"bug-1", "bug-2"})
            self.assertEqual(len(first.open_findings), 2)

            store.set_finding_status("owner/repo", 1, "bug-2", IGNORED)
            second = store.reconcile_findings(
                repo="owner/repo",
                pr_number=1,
                head_sha="sha2",
                findings=[
                    Finding(
                        finding_id="bug-1",
                        severity="high",
                        path="app.py",
                        line=10,
                        summary="Bug one",
                        details="Still bad.",
                    ),
                    Finding(
                        finding_id="bug-3",
                        severity="low",
                        path="docs.md",
                        line=None,
                        summary="Docs missing",
                        details="Needs notes.",
                    ),
                ],
            )

            self.assertEqual({item.finding_id for item in second.new_findings}, {"bug-3"})
            self.assertEqual({item.finding_id for item in second.open_findings}, {"bug-1", "bug-3"})
            self.assertEqual({item.finding_id for item in second.ignored_findings}, {"bug-2"})

            third = store.reconcile_findings(
                repo="owner/repo",
                pr_number=1,
                head_sha="sha3",
                findings=[],
            )

            self.assertEqual({item.finding_id for item in third.resolved_findings}, {"bug-1", "bug-3"})
            self.assertEqual(store.list_findings("owner/repo", 1, {OPEN}), [])
            self.assertEqual(
                {item.finding_id for item in store.list_findings("owner/repo", 1, {RESOLVED})},
                {"bug-1", "bug-3"},
            )


if __name__ == "__main__":
    unittest.main()
