"""Prompting, parsing, and rendering for PR review findings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .findings import Finding, coerce_findings, extract_json_object


@dataclass
class ReviewResult:
    body: str
    findings: list[Finding]
    residual_risk: str


def build_review_prompt(context: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    config = config or {}
    return "\n\n".join(
        [
            "Review this GitHub pull request.",
            "Prioritize correctness bugs, regressions, security issues, data loss, race conditions, missing migrations, and missing tests.",
            "Do not lead with style preferences or broad refactors.",
            "Return Markdown. If you find issues, use severity-ordered bullets with file paths and line references when possible.",
            "For each actionable issue, include a concise suggested fix when the fix is clear.",
            "If you do not find blocking issues, say that clearly and mention residual risk.",
            f"PR overview:\n```json\n{json.dumps(context['overview'], indent=2, sort_keys=True)}\n```",
            f"Changed files:\n```json\n{json.dumps(context['files'], indent=2, sort_keys=True)}\n```",
            f"Check runs:\n```json\n{json.dumps(context.get('check_runs', {}), indent=2, sort_keys=True)}\n```",
            f"Test results:\n```json\n{json.dumps(context.get('test_results', {}), indent=2, sort_keys=True)}\n```",
            f"CODEOWNERS matches:\n```json\n{json.dumps(context.get('codeowners', {}), indent=2, sort_keys=True)}\n```",
            f"Ignored files from config:\n```json\n{json.dumps(context.get('ignored_files', []), indent=2, sort_keys=True)}\n```",
            f"Review config:\n```json\n{json.dumps(config, indent=2, sort_keys=True)}\n```",
            f"Unresolved review threads:\n```json\n{json.dumps(context['review_threads'], indent=2, sort_keys=True)}\n```",
            f"Diff:\n```diff\n{context['diff'].get('text', '')}\n```",
        ]
    )


def build_structured_review_prompt(
    context: dict[str, Any], config: dict[str, Any] | None = None
) -> str:
    config = config or {}
    return "\n\n".join(
        [
            "Review this GitHub pull request and return structured JSON only.",
            "Find only real issues: correctness bugs, regressions, security issues, data loss, race conditions, missing migrations, broken CI, ownership gaps, deployment or release risk, and missing tests.",
            "Do not include style preferences, speculative broad refactors, or praise.",
            "Return this JSON shape exactly:",
            '{"findings":[{"severity":"critical|high|medium|low","path":"path or null","line":123,"summary":"short issue","details":"why this matters","suggested_fix":"clear fix or null"}],"residual_risk":"short note when no blocking issues or remaining uncertainty"}',
            "Use an empty findings array when no actionable issues are found.",
            "Do not wrap the JSON in Markdown.",
            f"PR overview:\n```json\n{json.dumps(context['overview'], indent=2, sort_keys=True)}\n```",
            f"Changed files:\n```json\n{json.dumps(context['files'], indent=2, sort_keys=True)}\n```",
            f"Check runs:\n```json\n{json.dumps(context.get('check_runs', {}), indent=2, sort_keys=True)}\n```",
            f"Test results:\n```json\n{json.dumps(context.get('test_results', {}), indent=2, sort_keys=True)}\n```",
            f"CODEOWNERS matches:\n```json\n{json.dumps(context.get('codeowners', {}), indent=2, sort_keys=True)}\n```",
            f"Ignored files from config:\n```json\n{json.dumps(context.get('ignored_files', []), indent=2, sort_keys=True)}\n```",
            f"Review config:\n```json\n{json.dumps(config, indent=2, sort_keys=True)}\n```",
            f"Unresolved review threads:\n```json\n{json.dumps(context['review_threads'], indent=2, sort_keys=True)}\n```",
            f"Diff:\n```diff\n{context['diff'].get('text', '')}\n```",
        ]
    )


def parse_structured_review(text: str) -> tuple[list[Finding], str]:
    payload = extract_json_object(text)
    findings = coerce_findings(payload.get("findings"))
    residual_risk = str(payload.get("residual_risk") or "").strip()
    return findings, residual_risk


def render_findings_markdown(findings: list[Finding], residual_risk: str = "") -> str:
    if not findings:
        risk = residual_risk or "No blocking issues found from the provided PR context."
        return f"No blocking issues found.\n\nResidual risk: {risk}"

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(findings, key=lambda item: severity_order.get(item.severity, 99))
    lines = ["Findings:"]
    for finding in ordered:
        location = finding.path or "unknown file"
        if finding.line:
            location = f"{location}:{finding.line}"
        lines.append(f"- **{finding.severity.upper()}** `{location}` - {finding.summary}")
        if finding.details:
            lines.append(f"  {finding.details}")
        if finding.suggested_fix:
            lines.append(f"  Suggested fix: {finding.suggested_fix}")
    if residual_risk:
        lines.extend(["", f"Residual risk: {residual_risk}"])
    return "\n".join(lines)

