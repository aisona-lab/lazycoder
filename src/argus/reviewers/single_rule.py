from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from argus.config.models import ReviewRule, ReviewRulesConfig
from argus.domain import Finding, ReviewReport, RuleResult
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
        results = [self.review(code_block, rule) for rule in rules]
        return ReviewReport.from_rule_results(results)

    def review_rubric(self, code_block: str, rubric: ReviewRulesConfig) -> ReviewReport:
        """Evaluate one block against every rule in the configured rubric."""
        return self.review_all(code_block, rubric.rules)

    def _build_prompt(self, code_block: str, rule: ReviewRule) -> str:
        return (
            "You are reviewing one code block against one rule.\n"
            f"Rule ID: {rule.id.value}\n"
            f"Question: {rule.question}\n"
            f"Checks: {rule.checks}\n"
            f"Flag when: {rule.flag_when}\n"
            f"Expected severity if unjustified: {rule.severity_if_unjustified.value}\n"
            "Return strict JSON with keys: passed (bool), finding (object|null).\n"
            "If finding is present it must match the Finding schema.\n"
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
        # Slice from the first '{' to the last '}' so code fences (```json)
        # and surrounding prose are dropped in one move.
        # ponytail: naive brace slice; over-captures if prose after the object
        # also contains a '}'. Switch to a bracket-matching scan if that shows up.
        start = raw_response.find("{")
        end = raw_response.rfind("}")
        if start == -1 or end < start:
            msg = "Invalid reviewer response: no JSON object found"
            raise LLMReviewerParseError(msg)
        try:
            payload = json.loads(raw_response[start : end + 1])
        except json.JSONDecodeError as exc:
            msg = f"Invalid reviewer response: invalid JSON at line {exc.lineno}"
            raise LLMReviewerParseError(msg) from exc
        if not isinstance(payload, dict):
            msg = "Invalid reviewer response: expected a JSON object"
            raise LLMReviewerParseError(msg)
        return payload
