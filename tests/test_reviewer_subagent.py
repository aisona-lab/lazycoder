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


def _fail_finding_json(severity: str = "high") -> str:
    return (
        '{"passed": false, "finding": {'
        '"rule_id": "R4",'
        '"location": {"file": "sample.py", "line": 2},'
        f'"severity": "{severity}",'
        '"reason": "empty input raises ZeroDivisionError"}}'
    )


def _review_r4(raw_response: str):
    config = load_all_configs()
    rule = next(rule for rule in config.review_rules.rules if rule.id == RuleId.R4)
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=[raw_response]))
    return reviewer.review(code_block="def average(xs): ...", rule=rule)


def test_parser_accepts_json_wrapped_in_code_fences() -> None:
    raw = f"```json\n{_fail_finding_json()}\n```"

    result = _review_r4(raw)

    assert result.passed is False
    assert result.finding is not None
    assert result.finding.severity == Severity.HIGH


def test_parser_accepts_prose_around_the_json_object() -> None:
    raw = f"Here is my review:\n{_fail_finding_json()}\nHope that helps!"

    result = _review_r4(raw)

    assert result.passed is False
    assert result.finding is not None
    assert result.finding.rule_id == RuleId.R4


def test_parser_normalizes_severity_casing() -> None:
    result = _review_r4(_fail_finding_json(severity="HIGH"))

    assert result.finding is not None
    assert result.finding.severity == Severity.HIGH


def test_parser_rejects_response_with_no_json_object() -> None:
    with pytest.raises(LLMReviewerParseError, match="Invalid reviewer response"):
        _review_r4("I cannot review this code.")


def test_parser_handles_json_followed_by_prose_with_a_brace() -> None:
    raw = f"{_fail_finding_json()} Note: consider the {{edge}} case."

    result = _review_r4(raw)

    assert result.finding is not None
    assert result.finding.severity == Severity.HIGH


def test_parser_handles_json_followed_by_typescript_codeblock() -> None:
    raw = (
        f"{_fail_finding_json()}\n\n"
        "```typescript\n"
        "export function Foo({ bar }: Props) {\n"
        "  return <div>{bar}</div>;\n"
        "}\n"
        "```"
    )

    result = _review_r4(raw)

    assert result.finding is not None
    assert result.finding.rule_id == RuleId.R4


def test_review_all_continues_when_one_rule_response_is_garbage() -> None:
    config = load_all_configs()
    rules = [r for r in config.review_rules.rules if r.id in (RuleId.R4, RuleId.R5)][:2]
    client = FakeLLMClient(
        responses=["this is not json", '{"passed": true, "finding": null}']
    )
    reviewer = SingleRuleReviewer(client=client)

    report = reviewer.review_all(code_block="x = 1", rules=rules)

    assert len(report.rule_results) == 1
    assert len(report.rule_errors) == 1
    assert report.rule_errors[0].rule_id == rules[0].id
    assert report.verdict == Verdict.REQUEST_CHANGES


def test_review_all_propagates_infrastructure_errors() -> None:
    class _BrokenClient:
        def generate(self, prompt: str) -> str:
            msg = "connection refused"
            raise RuntimeError(msg)

    config = load_all_configs()
    rules = [r for r in config.review_rules.rules if r.id == RuleId.R4]
    reviewer = SingleRuleReviewer(client=_BrokenClient())

    with pytest.raises(RuntimeError, match="connection refused"):
        reviewer.review_all(code_block="x = 1", rules=rules)


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
