import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_release_mcp.server import (
    CommandResult,
    ToolError,
    tool_commit_file_change,
    tool_create_branch,
    tool_mark_finding_resolved,
    tool_pr_codeowners,
    tool_pr_file,
    tool_pr_test_results,
)
from build_release_mcp.findings import Finding, RESOLVED
from build_release_mcp.job_store import JobStore


def response_json(response):
    return json.loads(response["content"][0]["text"])


class ServerToolTests(unittest.TestCase):
    def test_pr_file_reads_repo_relative_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")

            with patch.dict(os.environ, {"BUILD_RELEASE_MCP_REPO_ROOT": tmp}):
                payload = response_json(tool_pr_file({"path": "app.py", "max_bytes": 100}))

        self.assertEqual(payload["path"], "app.py")
        self.assertEqual(payload["text"], "print('ok')\n")
        self.assertFalse(payload["truncated"])

    def test_pr_file_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"BUILD_RELEASE_MCP_REPO_ROOT": tmp}):
                with self.assertRaises(ToolError):
                    tool_pr_file({"path": "../secret"})

    def test_pr_codeowners_matches_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github").mkdir()
            (root / ".github" / "CODEOWNERS").write_text(
                "*.py @python-team\n/docs/* @docs-team\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"BUILD_RELEASE_MCP_REPO_ROOT": tmp}):
                payload = response_json(
                    tool_pr_codeowners({"paths": ["src/app.py", "docs/readme.md"]})
                )

        self.assertEqual(payload["codeownersFile"], ".github/CODEOWNERS")
        self.assertEqual(payload["matches"][0]["matchingRules"][0]["owners"], ["@python-team"])
        self.assertEqual(payload["matches"][1]["matchingRules"][0]["owners"], ["@docs-team"])

    def test_pr_test_results_fetches_check_run_outputs(self) -> None:
        def fake_run_command(args, timeout=45):
            if args[:3] == ["gh", "pr", "view"]:
                return CommandResult('{"headRefOid":"abc123"}', "", 0)
            return CommandResult(
                """
{
  "check_runs": [
    {
      "name": "tests",
      "status": "completed",
      "conclusion": "failure",
      "html_url": "https://example.test/check",
      "details_url": "https://example.test/details",
      "output": {
        "summary": "1 failed",
        "text": "test_error"
      }
    }
  ]
}
""",
                "",
                0,
            )

        with patch("build_release_mcp.server.run_command", side_effect=fake_run_command):
            payload = response_json(
                tool_pr_test_results({"pr": "https://github.com/owner/repo/pull/1"})
            )

        self.assertEqual(payload["headSha"], "abc123")
        self.assertEqual(payload["checkRuns"][0]["name"], "tests")
        self.assertEqual(payload["checkRuns"][0]["conclusion"], "failure")
        self.assertEqual(payload["checkRuns"][0]["text"]["text"], "test_error")

    def test_create_branch_and_commit_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=tmp,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
            Path(tmp, "README.md").write_text("start\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp, check=True, capture_output=True)

            with patch.dict(os.environ, {"BUILD_RELEASE_MCP_REPO_ROOT": tmp}):
                branch = response_json(tool_create_branch({"branch": "agent/fix"}))
                commit = response_json(
                    tool_commit_file_change(
                        {
                            "branch": "agent/fix",
                            "path": "README.md",
                            "content": "updated\n",
                            "message": "Update README",
                        }
                    )
                )

        self.assertEqual(branch["branch"], "agent/fix")
        self.assertEqual(commit["path"], "README.md")
        self.assertTrue(commit["commit"])

    def test_mark_finding_resolved_updates_state_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "jobs.sqlite3")
            store = JobStore(db)
            store.reconcile_findings(
                repo="owner/repo",
                pr_number=1,
                head_sha="abc",
                findings=[
                    Finding(
                        finding_id="one",
                        severity="high",
                        path="app.py",
                        line=1,
                        summary="Bug",
                        details="Bad",
                    )
                ],
            )

            with patch.dict(os.environ, {"HOSTED_SERVICE_DB": db}):
                payload = response_json(
                    tool_mark_finding_resolved(
                        {
                            "repo": "owner/repo",
                            "pr_number": 1,
                            "finding_id": "one",
                        }
                    )
                )

            self.assertEqual(payload["status"], RESOLVED)
            self.assertEqual(store.list_findings("owner/repo", 1, {RESOLVED})[0].finding_id, "one")


if __name__ == "__main__":
    unittest.main()
