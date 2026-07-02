from __future__ import annotations

from dataclasses import dataclass

from argus.config.models import EvalCase, EvalsConfig, ReviewRulesConfig
from argus.domain import RuleId, Verdict
from argus.reviewers import SingleRuleReviewer


@dataclass(frozen=True)
class EvalResult:
    """Outcome of one eval case: did the reviewer catch what it had to?"""

    case_id: str
    passed: bool
    expected_rule_ids: frozenset[RuleId]
    actual_rule_ids: frozenset[RuleId]
    expected_verdict: Verdict
    actual_verdict: Verdict


def run_case(
    reviewer: SingleRuleReviewer, case: EvalCase, rubric: ReviewRulesConfig
) -> EvalResult:
    """Score one case: every expected rule must fire AND the verdict must match."""
    report = reviewer.review_rubric(case.input_code, rubric)
    expected = frozenset(f.rule_id for f in case.expect_findings)
    actual = frozenset(f.rule_id for f in report.findings)
    passed = expected <= actual and report.verdict == case.expect_verdict
    return EvalResult(
        case_id=case.id,
        passed=passed,
        expected_rule_ids=expected,
        actual_rule_ids=actual,
        expected_verdict=case.expect_verdict,
        actual_verdict=report.verdict,
    )


def run_evals(
    reviewer: SingleRuleReviewer, evals: EvalsConfig, rubric: ReviewRulesConfig
) -> list[EvalResult]:
    """Run every eval case against the reviewer.

    Client-agnostic by construction: the reviewer wraps any LLMClient, so the
    same harness scores the fake today and the real model after a one-line swap.
    """
    return [run_case(reviewer, case, rubric) for case in evals.cases]
