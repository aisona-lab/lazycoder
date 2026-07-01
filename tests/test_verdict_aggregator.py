from __future__ import annotations

import pytest

from argus.config import load_all_configs
from argus.domain import CodeLocation, Finding, RuleId, Severity, Verdict, aggregate


def make_finding(severity: Severity) -> Finding:
    return Finding(
        rule_id=RuleId.R4,
        location=CodeLocation(file="sample.py", line=1),
        severity=severity,
        reason=f"{severity.value} severity finding",
    )


def test_aggregate_matches_configured_policy_text() -> None:
    config = load_all_configs()
    policy = config.task_loop.aggregation.verdict_policy
    assert "BLOCK if any finding is high severity" in policy
    assert "REQUEST_CHANGES if any finding is medium or low severity" in policy
    assert "APPROVE only if there are no findings" in policy


@pytest.mark.parametrize(
    ("findings", "expected"),
    [
        ([], Verdict.APPROVE),
        ([make_finding(Severity.LOW)], Verdict.REQUEST_CHANGES),
        ([make_finding(Severity.MEDIUM)], Verdict.REQUEST_CHANGES),
        ([make_finding(Severity.HIGH)], Verdict.BLOCK),
        (
            [make_finding(Severity.LOW), make_finding(Severity.HIGH)],
            Verdict.BLOCK,
        ),
        (
            [make_finding(Severity.LOW), make_finding(Severity.MEDIUM)],
            Verdict.REQUEST_CHANGES,
        ),
    ],
)
def test_aggregate_is_severity_driven(
    findings: list[Finding], expected: Verdict
) -> None:
    assert aggregate(findings) == expected
