from __future__ import annotations

import os

import pytest

from conftest import SQL_INJECTION_CODE, block
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import Finding, ReviewReport, RuleId, RuleOutcome, Verdict
from lazycoder.llm.anthropic_client import AnthropicClient
from lazycoder.reviewers import SingleRuleReviewer

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY is not set",
    ),
]


def test_live_review_catches_sql_injection(rubric: ReviewRulesConfig) -> None:
    reviewer = SingleRuleReviewer(client=AnthropicClient())

    report = reviewer.review_rubric(block(SQL_INJECTION_CODE, file="db.py"), rubric)

    # Structure only — model wording is non-deterministic.
    assert isinstance(report, ReviewReport)
    assert report.verdict in Verdict
    assert len(report.rule_results) == len(rubric.rules)
    assert all(isinstance(f, Finding) for f in report.findings)
    assert all(f.rule_id in RuleId for f in report.findings)
    failed = {r.rule_id for r in report.rule_results if r.outcome is RuleOutcome.FAIL}
    assert RuleId.R7 in failed, "live reviewer must flag the SQL injection (R7)"
    # Citations are anchored to the diff, so this must hold for every finding.
    assert all(f.location.file == "db.py" for f in report.findings)
