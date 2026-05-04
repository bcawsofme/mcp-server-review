import unittest

from build_release_mcp.review_runner import apply_review_config, parse_pr_url, review_hash


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


if __name__ == "__main__":
    unittest.main()
