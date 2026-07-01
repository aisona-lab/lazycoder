from __future__ import annotations

import pytest

from argus.config import load_all_configs
from argus.domain import CodeLocation, RuleId, Severity, Verdict
from argus.llm import FakeLLMClient
from argus.reviewers import LLMReviewerParseError, SingleRuleReviewer


def test_fake_llm_client_returns_queued_response_and_records_prompt() -> None:
    client = FakeLLMClient(responses=['{"passed": true, "finding": null}'])

    response = client.generate("prompt-1")

    assert response == '{"passed": true, "finding": null}'
    assert client.prompts == ["prompt-1"]


def test_single_rule_reviewer_converts_valid_llm_response_to_rule_result() -> None:
    config = load_all_configs()
    rule = next(rule for rule in config.review_rules.rules if rule.id == RuleId.R4)
    client = FakeLLMClient(responses=["""
            {
              "passed": false,
              "finding": {
                "rule_id": "R4",
                "location": {"file": "sample.py", "line": 2},
                "severity": "high",
                "reason": "empty input raises ZeroDivisionError"
              }
            }
            """])
    reviewer = SingleRuleReviewer(client=client)

    result = reviewer.review(
        code_block="def average(xs):\n    return sum(xs) / len(xs)", rule=rule
    )

    assert result.rule_id == RuleId.R4
    assert result.passed is False
    assert result.finding is not None
    assert result.finding.location == CodeLocation(file="sample.py", line=2)
    assert result.finding.severity == Severity.HIGH
    assert result.finding.reason == "empty input raises ZeroDivisionError"
    assert "What are the failure modes" in client.prompts[0]
    assert "def average(xs)" in client.prompts[0]


def test_single_rule_reviewer_rejects_invalid_llm_response_cleanly() -> None:
    config = load_all_configs()
    rule = next(rule for rule in config.review_rules.rules if rule.id == RuleId.R4)
    client = FakeLLMClient(responses=["this is not json"])
    reviewer = SingleRuleReviewer(client=client)

    with pytest.raises(LLMReviewerParseError, match="Invalid reviewer response"):
        reviewer.review(
            code_block="def average(xs):\n    return sum(xs) / len(xs)", rule=rule
        )


def test_review_all_aggregates_rule_results_into_report() -> None:
    config = load_all_configs()
    rules = [r for r in config.review_rules.rules if r.id in (RuleId.R4, RuleId.R5)][:2]
    fail = f"""
        {{"passed": false, "finding": {{
          "rule_id": "{rules[0].id.value}",
          "location": {{"file": "sample.py", "line": 2}},
          "severity": "high",
          "reason": "boom"}}}}
    """
    client = FakeLLMClient(responses=[fail, '{"passed": true, "finding": null}'])
    reviewer = SingleRuleReviewer(client=client)

    report = reviewer.review_all(code_block="x = 1", rules=rules)

    assert len(report.rule_results) == 2
    assert len(report.findings) == 1
    assert report.verdict == Verdict.BLOCK


def test_review_rubric_runs_every_configured_rule() -> None:
    config = load_all_configs()
    rubric = config.review_rules
    client = FakeLLMClient(
        responses=['{"passed": true, "finding": null}'] * len(rubric.rules)
    )
    reviewer = SingleRuleReviewer(client=client)

    report = reviewer.review_rubric(code_block="x = 1", rubric=rubric)

    assert len(report.rule_results) == len(rubric.rules)
    assert report.findings == []
    assert report.verdict == Verdict.APPROVE
