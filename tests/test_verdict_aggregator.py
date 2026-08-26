from __future__ import annotations

import pytest
from pydantic import ValidationError

from lazycoder.config import load_all_configs
from lazycoder.domain import (
    CodeLocation,
    Finding,
    RuleId,
    RuleOutcome,
    RuleResult,
    Severity,
    Verdict,
    derive_verdict,
)


def failed(severity: Severity, rule_id: RuleId = RuleId.R4) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        outcome=RuleOutcome.FAIL,
        severity=severity,
        finding=Finding(
            rule_id=rule_id,
            location=CodeLocation(file="sample.py", line=1),
            severity=severity,
            reason=f"{severity.value} severity finding",
        ),
    )


def resolved(outcome: RuleOutcome, severity: Severity) -> RuleResult:
    return RuleResult(rule_id=RuleId.R9, outcome=outcome, severity=severity)


def test_aggregate_matches_configured_policy_text() -> None:
    config = load_all_configs()
    policy = config.task_loop.aggregation.verdict_policy
    assert "BLOCK if any finding is high severity" in policy
    assert "REQUEST_CHANGES if any finding is medium or low severity" in policy
    assert "insufficient_context" in policy


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([], Verdict.APPROVE),
        ([resolved(RuleOutcome.PASS, Severity.HIGH)], Verdict.APPROVE),
        ([failed(Severity.LOW)], Verdict.REQUEST_CHANGES),
        ([failed(Severity.MEDIUM)], Verdict.REQUEST_CHANGES),
        ([failed(Severity.HIGH)], Verdict.BLOCK),
        ([failed(Severity.LOW), failed(Severity.HIGH)], Verdict.BLOCK),
    ],
)
def test_verdict_is_driven_by_rubric_severity(
    results: list[RuleResult], expected: Verdict
) -> None:
    assert derive_verdict(results, evaluation_errors=False) == expected


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        # A high-severity rule that could not be answered is not a pass...
        (Severity.HIGH, Verdict.REQUEST_CHANGES),
        # ...but abstention must not become a second way to always block.
        (Severity.MEDIUM, Verdict.APPROVE),
        (Severity.LOW, Verdict.APPROVE),
    ],
)
def test_abstention_blocks_approval_only_for_high_severity_rules(
    severity: Severity, expected: Verdict
) -> None:
    results = [resolved(RuleOutcome.INSUFFICIENT_CONTEXT, severity)]
    assert derive_verdict(results, evaluation_errors=False) == expected


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([], Verdict.REQUEST_CHANGES),
        ([failed(Severity.HIGH)], Verdict.BLOCK),
        ([failed(Severity.LOW)], Verdict.REQUEST_CHANGES),
    ],
)
def test_derive_verdict_never_approves_with_evaluation_errors(
    results: list[RuleResult], expected: Verdict
) -> None:
    assert derive_verdict(results, evaluation_errors=True) == expected


def test_rule_result_rejects_a_severity_that_contradicts_the_rubric() -> None:
    # Severity is rubric data. A finding may not carry a different one, so no
    # model output can reach the verdict through this field.
    with pytest.raises(ValidationError, match="configured severity"):
        RuleResult(
            rule_id=RuleId.R4,
            outcome=RuleOutcome.FAIL,
            severity=Severity.MEDIUM,
            finding=Finding(
                rule_id=RuleId.R4,
                location=CodeLocation(file="sample.py", line=1),
                severity=Severity.HIGH,
                reason="smuggled severity",
            ),
        )


def test_configured_high_severity_rules_are_answerable_from_a_hunk() -> None:
    # Policy check, not a style check: a rule that must guess must not BLOCK.
    config = load_all_configs()
    high = {
        r.id
        for r in config.review_rules.rules
        if r.severity_if_unjustified is Severity.HIGH
    }
    assert high == {RuleId.R4, RuleId.R7}
