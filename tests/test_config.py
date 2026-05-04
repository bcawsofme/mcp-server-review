import unittest

from build_release_mcp.config import (
    parse_config,
    review_enabled,
    review_ignored_paths,
    review_max_diff_bytes,
    review_model,
)


class ConfigTests(unittest.TestCase):
    def test_parse_simple_yaml_review_config(self) -> None:
        config = parse_config(
            """
model: gpt-5
pr_review:
  enabled: true
  max_diff_bytes: 12345
  ignored_paths:
    - docs/**
    - "*.md"
"""
        )

        self.assertTrue(review_enabled(config))
        self.assertEqual(review_max_diff_bytes(config, 100), 12345)
        self.assertEqual(review_ignored_paths(config), ["docs/**", "*.md"])
        self.assertEqual(review_model(config), "gpt-5")

    def test_parse_json_config(self) -> None:
        config = parse_config('{"pr_review": {"enabled": false}}')

        self.assertFalse(review_enabled(config))


if __name__ == "__main__":
    unittest.main()
