import unittest

from build_release_mcp.findings import (
    coerce_findings,
    extract_json_object,
    finding_fingerprint,
)


class FindingsTests(unittest.TestCase):
    def test_fingerprint_is_stable(self) -> None:
        first = finding_fingerprint(
            path="app.py",
            line=12,
            summary="Missing null check",
            details="Can crash",
        )
        second = finding_fingerprint(
            path="app.py",
            line=12,
            summary=" Missing   null check ",
            details="Can crash",
        )

        self.assertEqual(first, second)

    def test_coerce_findings_normalizes_items(self) -> None:
        findings = coerce_findings(
            [
                {
                    "severity": "urgent",
                    "file": "app.py",
                    "line": "4",
                    "summary": "Bad thing",
                    "details": "Broken",
                    "fix": "Use the right value.",
                },
                {"summary": ""},
            ]
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "medium")
        self.assertEqual(findings[0].path, "app.py")
        self.assertEqual(findings[0].line, 4)
        self.assertEqual(findings[0].suggested_fix, "Use the right value.")

    def test_extract_json_object_from_fence(self) -> None:
        payload = extract_json_object(
            """```json
{"findings": [], "residual_risk": "tests not run"}
```"""
        )

        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["residual_risk"], "tests not run")


if __name__ == "__main__":
    unittest.main()
