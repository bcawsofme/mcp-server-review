import os
import tempfile
import unittest
from http import HTTPStatus
from unittest.mock import patch

from build_release_mcp import hosted_service
from build_release_mcp.findings import Finding
from build_release_mcp.job_store import JobStore


def payload(**overrides):
    base = {
        "action": "opened",
        "installation": {"id": 123},
        "repository": {"full_name": "owner/repo"},
        "pull_request": {
            "html_url": "https://github.com/owner/repo/pull/7",
            "number": 7,
            "draft": False,
            "head": {
                "sha": "abc123",
                "repo": {"full_name": "owner/repo"},
            },
        },
    }
    base.update(overrides)
    return base


class HostedServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        hosted_service.store = JobStore(os.path.join(self.tmp.name, "jobs.sqlite3"))

    def test_verify_signature(self) -> None:
        body = b'{"ok":true}'
        secret = "secret"
        import hashlib
        import hmac

        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        self.assertTrue(hosted_service.verify_signature(secret, body, f"sha256={digest}"))
        self.assertFalse(hosted_service.verify_signature(secret, body, "sha256=bad"))

    def test_ignores_unsupported_action(self) -> None:
        status, body = hosted_service.handle_pull_request_event(payload(action="edited"))

        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertEqual(body["status"], "ignored")

    def test_ignores_fork_by_default(self) -> None:
        item = payload()
        item["pull_request"]["head"]["repo"]["full_name"] = "someone/fork"

        status, body = hosted_service.handle_pull_request_event(item)

        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertEqual(body["reason"], "fork pull request")

    @patch.dict(
        os.environ,
        {
            "GITHUB_WEBHOOK_SECRET": "secret",
            "OPENAI_API_KEY": "key",
            "GH_TOKEN": "token",
            "HOSTED_SERVICE_ALLOWED_REPOS": "owner/repo",
        },
        clear=False,
    )
    def test_enqueues_and_deduplicates_by_delivery(self) -> None:
        first_status, first_body = hosted_service.handle_pull_request_event(
            payload(), delivery_id="delivery-1"
        )
        second_status, second_body = hosted_service.handle_pull_request_event(
            payload(), delivery_id="delivery-1"
        )

        self.assertEqual(first_status, HTTPStatus.ACCEPTED)
        self.assertEqual(first_body["status"], "queued")
        self.assertEqual(second_status, HTTPStatus.ACCEPTED)
        self.assertEqual(second_body["status"], "duplicate")
        self.assertEqual(first_body["job"]["id"], second_body["job"]["id"])

    @patch.dict(
        os.environ,
        {
            "GITHUB_WEBHOOK_SECRET": "secret",
            "OPENAI_API_KEY": "key",
            "GH_TOKEN": "token",
            "HOSTED_SERVICE_ALLOWED_REPOS": "other/repo",
        },
        clear=False,
    )
    def test_blocks_unallowed_repo(self) -> None:
        status, body = hosted_service.handle_pull_request_event(payload(), delivery_id="delivery-2")

        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(body["error"], "repository is not allowed")

    def test_build_reconciled_review_body_reports_new_and_resolved(self) -> None:
        first = hosted_service.store.reconcile_findings(
            repo="owner/repo",
            pr_number=7,
            head_sha="abc123",
            findings=[
                Finding(
                    finding_id="one",
                    severity="high",
                    path="app.py",
                    line=3,
                    summary="Bug",
                    details="Breaks prod.",
                    suggested_fix="Guard it.",
                )
            ],
        )
        body = hosted_service.build_reconciled_review_body(first, "tests not run", "abc123")

        self.assertIn("New findings on this commit", body)
        self.assertIn("app.py:3", body)
        self.assertIn("Reviewed commit: `abc123`", body)

        second = hosted_service.store.reconcile_findings(
            repo="owner/repo",
            pr_number=7,
            head_sha="def456",
            findings=[],
        )
        body = hosted_service.build_reconciled_review_body(second, "", "def456")

        self.assertIn("No new findings", body)
        self.assertIn("Resolved findings", body)

    @patch.dict(os.environ, {"HOSTED_SERVICE_ENABLE_MINOR_FIXES": "true"}, clear=False)
    def test_minor_fixes_require_env_and_repo_opt_in(self) -> None:
        self.assertFalse(hosted_service.minor_fixes_enabled({}))
        self.assertTrue(
            hosted_service.minor_fixes_enabled(
                {"pr_review": {"minor_fixes_enabled": True}}
            )
        )


if __name__ == "__main__":
    unittest.main()
