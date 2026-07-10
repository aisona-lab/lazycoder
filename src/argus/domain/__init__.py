"""Domain contracts: findings, rule outcomes, and review reports."""

from argus.domain.aggregator import aggregate, derive_verdict
from argus.domain.enums import RuleId, Severity, Verdict
from argus.domain.models import (
    CodeLocation,
    Finding,
    ReviewReport,
    RuleEvaluationError,
    RuleResult,
)

__all__ = [
    "aggregate",
    "derive_verdict",
    "CodeLocation",
    "Finding",
    "ReviewReport",
    "RuleEvaluationError",
    "RuleId",
    "RuleResult",
    "Severity",
    "Verdict",
]
