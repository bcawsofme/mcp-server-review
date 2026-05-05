import unittest

from build_release_mcp.fix_runner import (
    build_fix_prompt,
    extract_unified_diff,
    paths_from_unified_diff,
    validate_patch_paths,
)
from build_release_mcp.review_runner import (
    RunnerError,
    apply_review_config,
    parse_pr_url,
    review_hash,
)


class ReviewRunnerTests(unittest.TestCase):
    def test_parse_pr_url(self) -> None:
        self.assertEqual(
            parse_pr_url("https://github.com/owner/repo/pull/42"),
            ("owner", "repo", 42),
        )

    def test_apply_review_config_filters_files(self) -> None:
        context = {
            "files": [
                {"path": "docs/readme.md"},
                {"path": "src/app.py"},
            ]
        }

        filtered = apply_review_config(
            context,
            {"pr_review": {"ignored_paths": ["docs/**"]}},
        )

        self.assertEqual(filtered["files"], [{"path": "src/app.py"}])
        self.assertEqual(filtered["ignored_files"], [{"path": "docs/readme.md"}])

    def test_review_hash_is_stable(self) -> None:
        self.assertEqual(review_hash("body"), review_hash("body"))

    def test_extract_unified_diff_from_fenced_response(self) -> None:
        response = """```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
```"""

        diff = extract_unified_diff(response)

        self.assertIsNotNone(diff)
        self.assertTrue(diff.startswith("diff --git"))

    def test_extract_unified_diff_from_response_with_prose(self) -> None:
        response = """Here is the patch:

```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
```
"""

        diff = extract_unified_diff(response)

        self.assertIsNotNone(diff)
        self.assertNotIn("```", diff)

    def test_extract_unified_diff_accepts_no_changes(self) -> None:
        self.assertIsNone(extract_unified_diff("NO_CHANGES"))

    def test_build_fix_prompt_requires_diff_or_no_changes(self) -> None:
        prompt = build_fix_prompt(
            {
                "overview": {},
                "files": [],
                "review_threads": [],
                "diff": {"text": ""},
            }
        )

        self.assertIn("NO_CHANGES", prompt)
        self.assertIn("unified diff", prompt)

    def test_paths_from_unified_diff_reads_git_headers(self) -> None:
        diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old
+new
"""

        self.assertEqual(paths_from_unified_diff(diff), {"src/app.py"})

    def test_validate_patch_paths_rejects_workflow_changes(self) -> None:
        diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
-old
+new
"""

        with self.assertRaises(RunnerError):
            validate_patch_paths(diff)


if __name__ == "__main__":
    unittest.main()
