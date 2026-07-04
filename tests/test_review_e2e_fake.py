from __future__ import annotations

from argus.config.models import ReviewRulesConfig
from argus.domain import RuleId, Verdict
from argus.llm import FakeLLMClient
from argus.reviewers import SingleRuleReviewer
from conftest import CLEAN_CODE, SQL_INJECTION_CODE

PASS_RESPONSE = '{"passed": true, "finding": null}'

R7_FINDING_RESPONSE = (
    '{"passed": false, "finding": {'
    '"rule_id": "R7",'
    '"location": {"file": "diff.py", "line": 1},'
    '"severity": "high",'
    '"reason": "string-concatenated SQL is injectable"}}'
)


def test_sql_injection_block_yields_r7_finding_and_block_verdict(
    rubric: ReviewRulesConfig,
) -> None:
    responses = [
        R7_FINDING_RESPONSE if rule.id == RuleId.R7 else PASS_RESPONSE
        for rule in rubric.rules
    ]
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))

    report = reviewer.review_rubric(SQL_INJECTION_CODE, rubric)

    assert len(report.rule_results) == len(rubric.rules)
    assert [f.rule_id for f in report.findings] == [RuleId.R7]
    assert report.verdict is Verdict.BLOCK


def test_clean_code_yields_no_findings_and_approve(
    rubric: ReviewRulesConfig,
) -> None:
    responses = [PASS_RESPONSE] * len(rubric.rules)
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))

    report = reviewer.review_rubric(CLEAN_CODE, rubric)

    assert len(report.rule_results) == len(rubric.rules)
    assert report.findings == []
    assert report.verdict is Verdict.APPROVE
