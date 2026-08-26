from __future__ import annotations

from conftest import (
    CLEAN_CODE,
    PASS_RESPONSE,
    SQL_INJECTION_CODE,
    block,
    fail_response,
)
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import RuleId, Verdict
from lazycoder.llm import FakeLLMClient
from lazycoder.reviewers import SingleRuleReviewer


def test_sql_injection_block_yields_r7_finding_and_block_verdict(
    rubric: ReviewRulesConfig,
) -> None:
    responses = [
        (
            fail_response(1, "string-concatenated SQL is injectable")
            if rule.id == RuleId.R7
            else PASS_RESPONSE
        )
        for rule in rubric.rules
    ]
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))

    report = reviewer.review_rubric(block(SQL_INJECTION_CODE, file="db.py"), rubric)

    assert len(report.rule_results) == len(rubric.rules)
    assert [f.rule_id for f in report.findings] == [RuleId.R7]
    # The file comes from the diff, never from the model.
    assert report.findings[0].location.file == "db.py"
    assert report.verdict is Verdict.BLOCK


def test_clean_code_yields_no_findings_and_approve(
    rubric: ReviewRulesConfig,
) -> None:
    responses = [PASS_RESPONSE] * len(rubric.rules)
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))

    report = reviewer.review_rubric(block(CLEAN_CODE), rubric)

    assert len(report.rule_results) == len(rubric.rules)
    assert report.findings == []
    assert report.verdict is Verdict.APPROVE
