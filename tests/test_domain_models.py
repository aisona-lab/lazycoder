"""Domain model contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from argus.config import load_all_configs
from argus.domain import (
    CodeLocation,
    Finding,
    ReviewReport,
    RuleEvaluationError,
    RuleId,
    RuleResult,
    Severity,
    Verdict,
)


def test_verdict_enum_matches_review_rules_config() -> None:
    config = load_all_configs()
    config_verdicts = {Verdict(v) for v in config.review_rules.verdicts}
    assert config_verdicts == set(Verdict)


def test_severity_enum_matches_review_rules_config() -> None:
    config = load_all_configs()
    config_severities = {Severity(s) for s in config.review_rules.severity_levels}
    assert config_severities == set(Severity)


def test_rule_id_enum_covers_config_rubric() -> None:
    config = load_all_configs()
    config_rule_ids = {rule.id for rule in config.review_rules.rules}
    assert config_rule_ids.issubset(set(RuleId))


def test_finding_requires_rule_location_severity_reason() -> None:
    finding = Finding(
        rule_id=RuleId.R4,
        location=CodeLocation(file="avg.py", line=2),
        severity=Severity.HIGH,
        reason="empty input raises ZeroDivisionError",
    )
    assert finding.rule_id == RuleId.R4
    assert finding.location.line == 2


def test_finding_rejects_empty_reason() -> None:
    with pytest.raises(ValidationError):
        Finding(
            rule_id=RuleId.R4,
            location=CodeLocation(file="avg.py", line=2),
            severity=Severity.HIGH,
            reason="   ",
        )


def test_rule_result_failed_requires_matching_finding() -> None:
    finding = Finding(
        rule_id=RuleId.R7,
        location=CodeLocation(file="db.py", line=10),
        severity=Severity.HIGH,
        reason="string-concatenated SQL is injectable",
    )
    result = RuleResult(rule_id=RuleId.R7, passed=False, finding=finding)
    assert result.finding is finding


def test_rule_result_passed_must_not_carry_finding() -> None:
    finding = Finding(
        rule_id=RuleId.R1,
        location=CodeLocation(file="x.py", line=1),
        severity=Severity.LOW,
        reason="unnecessary scan",
    )
    with pytest.raises(ValidationError, match="passed rule must not include"):
        RuleResult(rule_id=RuleId.R1, passed=True, finding=finding)


def test_rule_result_finding_rule_id_must_match() -> None:
    finding = Finding(
        rule_id=RuleId.R3,
        location=CodeLocation(file="money.py", line=3),
        severity=Severity.MEDIUM,
        reason="float used for money",
    )
    with pytest.raises(ValidationError, match="finding.rule_id must match"):
        RuleResult(rule_id=RuleId.R4, passed=False, finding=finding)


def test_review_report_links_findings_to_failed_rule_results() -> None:
    finding = Finding(
        rule_id=RuleId.R4,
        location=CodeLocation(file="avg.py", line=2),
        severity=Severity.HIGH,
        reason="empty input raises ZeroDivisionError",
    )
    report = ReviewReport(
        findings=[finding],
        rule_results=[RuleResult(rule_id=RuleId.R4, passed=False, finding=finding)],
    )
    assert report.verdict == Verdict.BLOCK
    assert len(report.findings) == 1


def test_review_report_rejects_orphan_failed_rule_result() -> None:
    finding = Finding(
        rule_id=RuleId.R4,
        location=CodeLocation(file="avg.py", line=2),
        severity=Severity.HIGH,
        reason="empty input raises ZeroDivisionError",
    )
    with pytest.raises(ValidationError, match="failed rule_result finding"):
        ReviewReport(
            findings=[],
            rule_results=[RuleResult(rule_id=RuleId.R4, passed=False, finding=finding)],
        )


def test_review_report_derives_verdict_from_findings() -> None:
    report = ReviewReport(
        findings=[
            Finding(
                rule_id=RuleId.R3,
                location=CodeLocation(file="money.py", line=3),
                severity=Severity.MEDIUM,
                reason="float used for money",
            )
        ]
    )
    assert report.verdict == Verdict.REQUEST_CHANGES


def test_review_report_with_rule_errors_never_approves() -> None:
    report = ReviewReport(
        findings=[],
        rule_errors=[
            RuleEvaluationError(
                rule_id=RuleId.R4,
                message="Invalid reviewer response: no JSON object found",
            )
        ],
    )
    assert report.verdict == Verdict.REQUEST_CHANGES


def test_review_report_rejects_injected_verdict() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReviewReport(findings=[], verdict=Verdict.APPROVE)
