from __future__ import annotations

from conftest import PASS_RESPONSE, abstain_response, fail_response
from lazycoder.config import load_all_configs
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import RuleId, Verdict
from lazycoder.evals import run_case, run_evals, summarize
from lazycoder.llm import FakeLLMClient
from lazycoder.reviewers import SingleRuleReviewer


def _responses(rubric: ReviewRulesConfig, response_for: dict[RuleId, str]) -> list[str]:
    """One queued fake response per rule, in rubric order (FIFO)."""
    return [response_for.get(rule.id, PASS_RESPONSE) for rule in rubric.rules]


def _e3_case():
    config = load_all_configs()
    case = next(c for c in config.evals.cases if c.id == "E3")
    return case, config.review_rules


_R7_FAIL = fail_response(1, "string-concatenated SQL is injectable")


def test_gate_passes_when_reviewer_catches_the_expected_rule() -> None:
    case, rubric = _e3_case()
    client = FakeLLMClient(responses=_responses(rubric, {RuleId.R7: _R7_FAIL}))

    result = run_case(SingleRuleReviewer(client=client), case, rubric)

    assert result.passed is True
    assert result.actual_rule_ids == {RuleId.R7}
    assert result.false_positives == frozenset()
    assert result.actual_verdict == Verdict.BLOCK


def test_gate_fails_when_reviewer_misses_the_expected_rule() -> None:
    # Reviewer passes every rule → no findings → misses R7 and verdict APPROVEs.
    # A gate that cannot fail here is theater; this proves it has teeth.
    case, rubric = _e3_case()
    client = FakeLLMClient(responses=_responses(rubric, {}))

    result = run_case(SingleRuleReviewer(client=client), case, rubric)

    assert result.passed is False
    assert result.false_negatives == {RuleId.R7}
    assert result.actual_verdict == Verdict.APPROVE
    assert result.expected_verdict == Verdict.BLOCK


def test_gate_fails_on_a_false_positive_even_when_the_real_bug_is_caught() -> None:
    # The number that decides whether anyone keeps the tool switched on. Before
    # this, an extra finding cost the score nothing.
    case, rubric = _e3_case()
    noise = fail_response(1, "this rule did not actually fire on anything")
    client = FakeLLMClient(
        responses=_responses(rubric, {RuleId.R7: _R7_FAIL, RuleId.R1: noise})
    )

    result = run_case(SingleRuleReviewer(client=client), case, rubric)

    assert result.passed is False
    assert result.false_positives == {RuleId.R1}
    assert result.true_positives == {RuleId.R7}


def test_case_records_abstentions_separately_from_findings() -> None:
    case, rubric = _e3_case()
    client = FakeLLMClient(
        responses=_responses(
            rubric, {RuleId.R7: _R7_FAIL, RuleId.R16: abstain_response()}
        )
    )

    result = run_case(SingleRuleReviewer(client=client), case, rubric)

    assert result.abstained_rule_ids == {RuleId.R16}
    assert RuleId.R16 not in result.false_positives


def test_summary_reports_precision_recall_and_per_rule_abstention() -> None:
    config = load_all_configs()
    rubric = config.review_rules
    # Every case: R7 fires, R1 fires spuriously, R16 abstains.
    noise = fail_response(1, "spurious")
    per_case = _responses(
        rubric,
        {RuleId.R7: _R7_FAIL, RuleId.R1: noise, RuleId.R16: abstain_response()},
    )
    n_cases = len(config.evals.cases)
    client = FakeLLMClient(responses=per_case * n_cases)

    results = run_evals(SingleRuleReviewer(client=client), config.evals, rubric)
    summary = summarize(results, rubric)

    assert summary.cases_total == n_cases
    # R7 fires in every case; it is a true positive only where the suite
    # expects it and noise everywhere else.
    expected_r7 = sum(
        1
        for case in config.evals.cases
        if any(f.rule_id is RuleId.R7 for f in case.expect_findings)
    )
    assert summary.false_positives > 0
    assert 0.0 < summary.precision < 1.0
    assert summary.per_rule[RuleId.R16].abstention_rate == 1.0
    assert summary.per_rule[RuleId.R7].true_positives == expected_r7
    assert summary.per_rule[RuleId.R7].false_positives == n_cases - expected_r7
