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
