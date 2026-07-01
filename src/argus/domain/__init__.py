"""Domain contracts: findings, rule outcomes, and review reports."""

from argus.domain.aggregator import aggregate
from argus.domain.enums import RuleId, Severity, Verdict
from argus.domain.models import CodeLocation, Finding, ReviewReport, RuleResult

__all__ = [
    "aggregate",
    "CodeLocation",
    "Finding",
    "ReviewReport",
    "RuleId",
    "RuleResult",
    "Severity",
    "Verdict",
]
