import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
