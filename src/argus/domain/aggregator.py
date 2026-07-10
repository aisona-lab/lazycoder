from __future__ import annotations

from argus.domain.enums import Severity, Verdict
from argus.domain.models import Finding


def aggregate(findings: list[Finding]) -> Verdict:
    """Aggregate findings into a verdict using the configured severity policy."""
    if any(finding.severity is Severity.HIGH for finding in findings):
        return Verdict.BLOCK
    if findings:
        return Verdict.REQUEST_CHANGES
    return Verdict.APPROVE


def derive_verdict(findings: list[Finding], *, evaluation_errors: bool) -> Verdict:
    """Apply severity policy, but never APPROVE when some rules failed to evaluate."""
    finding_verdict = aggregate(findings)
    if not evaluation_errors:
        return finding_verdict
    if finding_verdict is Verdict.BLOCK:
        return Verdict.BLOCK
    return Verdict.REQUEST_CHANGES
