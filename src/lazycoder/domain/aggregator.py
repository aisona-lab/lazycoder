from __future__ import annotations

from lazycoder.domain.enums import RuleOutcome, Severity, Verdict
from lazycoder.domain.models import RuleResult


def derive_verdict(
    rule_results: list[RuleResult], *, evaluation_errors: bool
) -> Verdict:
    """Derive the verdict from rule outcomes and the rubric's own severities.

    Pure function of (which rules failed or abstained) x (review_rules.json).
    No model output reaches this decision: severity is rubric data, so the same
    rule outcomes always yield the same verdict.
    """
    failed = [r for r in rule_results if r.outcome is RuleOutcome.FAIL]
    if any(result.severity is Severity.HIGH for result in failed):
        return Verdict.BLOCK

    # A rule that could not be answered is not a pass. For high-severity rules
    # that is disqualifying; for the rest it is recorded and neutral, so the
    # abstention hatch cannot quietly become a second way to always block.
    unresolved_high = any(
        result.outcome is RuleOutcome.INSUFFICIENT_CONTEXT
        and result.severity is Severity.HIGH
        for result in rule_results
    )
    if failed or evaluation_errors or unresolved_high:
        return Verdict.REQUEST_CHANGES
    return Verdict.APPROVE
