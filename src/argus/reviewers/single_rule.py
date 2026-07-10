from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from argus.config.models import ReviewRule, ReviewRulesConfig
from argus.domain import Finding, ReviewReport, RuleEvaluationError, RuleResult
from argus.llm import LLMClient


class LLMReviewerParseError(Exception):
    """Raised when a reviewer response is invalid or does not match the schema."""


def _normalize_severity(payload: dict[str, object]) -> None:
    """Lowercase severity at the parse boundary so the domain enum stays strict."""
    finding = payload.get("finding")
    if isinstance(finding, dict):
        severity = finding.get("severity")
        if isinstance(severity, str):
            finding["severity"] = severity.strip().lower()


class _ReviewerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    finding: Finding | None = None

    @model_validator(mode="after")
    def finding_matches_passed(self) -> _ReviewerResponse:
        if self.passed and self.finding is not None:
            msg = "passed response must not include a finding"
            raise ValueError(msg)
        if not self.passed and self.finding is None:
            msg = "failed response must include a finding"
            raise ValueError(msg)
        return self


class SingleRuleReviewer:
    """Minimal reviewer that evaluates one rule on one code block."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def review(self, code_block: str, rule: ReviewRule) -> RuleResult:
        prompt = self._build_prompt(code_block=code_block, rule=rule)
        raw_response = self._client.generate(prompt)
        parsed = self._parse_response(raw_response)
        finding = parsed.finding
        if finding is not None and finding.rule_id != rule.id:
            msg = "Invalid reviewer response: finding.rule_id must match requested rule"
            raise LLMReviewerParseError(msg)
        return RuleResult(rule_id=rule.id, passed=parsed.passed, finding=finding)

    def review_all(self, code_block: str, rules: list[ReviewRule]) -> ReviewReport:
        """Evaluate every rule on one block and aggregate into a report."""
        results: list[RuleResult] = []
        errors: list[RuleEvaluationError] = []
        for rule in rules:
            try:
                results.append(self.review(code_block, rule))
            except LLMReviewerParseError as exc:
                # Only bad model output is tolerated per-rule; infra errors
                # (API/auth/network) must propagate and abort the run.
                errors.append(RuleEvaluationError(rule_id=rule.id, message=str(exc)))
        return ReviewReport.from_rule_results(results, rule_errors=errors)

    def review_rubric(self, code_block: str, rubric: ReviewRulesConfig) -> ReviewReport:
        """Evaluate one block against every rule in the configured rubric."""
        return self.review_all(code_block, rubric.rules)

    def _build_prompt(self, code_block: str, rule: ReviewRule) -> str:
        rule_id = rule.id.value
        return (
            "You are reviewing one code block against one rule.\n"
            f"Rule ID: {rule_id}\n"
            f"Question: {rule.question}\n"
            f"Checks: {rule.checks}\n"
            f"Flag when: {rule.flag_when}\n"
            f"Expected severity if unjustified: {rule.severity_if_unjustified.value}\n"
            "Respond with a single JSON object and nothing else"
            " - no prose, no code fences.\n"
            "Fields:\n"
            "- passed (bool): true if the rule is satisfied,"
            " false if it is violated.\n"
            "- finding (object|null): null when passed is true;"
            " required when passed is false, with fields:\n"
            f'  - rule_id (string): must be exactly "{rule_id}".\n'
            "  - location (object): file (string, non-empty),"
            " line (int, 1-based), optional end_line (int >= line).\n"
            '  - severity (string): one of "low", "medium", "high".\n'
            "  - reason (string, non-empty): why the code violates the rule.\n"
            "Example output when the rule passes:\n"
            '{"passed": true, "finding": null}\n'
            "Example output when the rule is violated:\n"
            f'{{"passed": false, "finding": {{"rule_id": "{rule_id}",'
            ' "location": {"file": "diff.py", "line": 3}, "severity": "high",'
            ' "reason": "unvalidated input reaches the query"}}\n'
            "Code block:\n"
            f"{code_block}\n"
        )

    def _parse_response(self, raw_response: str) -> _ReviewerResponse:
        payload = self._extract_json_object(raw_response)
        _normalize_severity(payload)
        try:
            return _ReviewerResponse.model_validate(payload)
        except ValidationError as exc:
            msg = f"Invalid reviewer response: {exc}"
            raise LLMReviewerParseError(msg) from exc

    @staticmethod
    def _extract_json_object(raw_response: str) -> dict[str, object]:
        text = SingleRuleReviewer._strip_code_fence(raw_response.strip())
        start = text.find("{")
        if start == -1:
            msg = "Invalid reviewer response: no JSON object found"
            raise LLMReviewerParseError(msg)

        end = SingleRuleReviewer._find_matching_object_end(text, start)
        if end is None:
            msg = "Invalid reviewer response: unterminated JSON object"
            raise LLMReviewerParseError(msg)

        snippet = text[start : end + 1]
        try:
            payload = json.loads(snippet)
        except json.JSONDecodeError as exc:
            msg = f"Invalid reviewer response: invalid JSON at line {exc.lineno}"
            raise LLMReviewerParseError(msg) from exc
        if not isinstance(payload, dict):
            msg = "Invalid reviewer response: expected a JSON object"
            raise LLMReviewerParseError(msg)
        return payload

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        if not text.startswith("```"):
            return text
        lines = text.splitlines()
        if not lines:
            return text
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _find_matching_object_end(text: str, start: int) -> int | None:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return None
