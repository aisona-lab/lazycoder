from __future__ import annotations

import os

import pytest

from argus.config.models import ReviewRulesConfig
from argus.domain import Finding, ReviewReport, RuleId, Verdict
from argus.llm.anthropic_client import AnthropicClient
from argus.reviewers import SingleRuleReviewer
from conftest import SQL_INJECTION_CODE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY is not set",
    ),
]


def test_live_review_catches_sql_injection(rubric: ReviewRulesConfig) -> None:
    reviewer = SingleRuleReviewer(client=AnthropicClient())

    report = reviewer.review_rubric(SQL_INJECTION_CODE, rubric)

    # Structure only — model wording is non-deterministic.
    assert isinstance(report, ReviewReport)
    assert report.verdict in Verdict
    assert len(report.rule_results) == len(rubric.rules)
    assert all(isinstance(f, Finding) for f in report.findings)
    assert all(f.rule_id in RuleId for f in report.findings)
    failed = {r.rule_id for r in report.rule_results if not r.passed}
    assert RuleId.R7 in failed, "live reviewer must flag the SQL injection (R7)"
