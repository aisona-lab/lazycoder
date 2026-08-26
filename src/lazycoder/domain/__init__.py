"""Domain contracts: findings, rule outcomes, and review reports."""

from lazycoder.domain.aggregator import derive_verdict
from lazycoder.domain.enums import RuleId, RuleOutcome, Severity, Verdict
from lazycoder.domain.models import (
    CodeBlock,
    CodeLocation,
    Finding,
    ReviewReport,
    RuleEvaluationError,
    RuleResult,
)

__all__ = [
    "CodeBlock",
    "CodeLocation",
    "Finding",
    "ReviewReport",
    "RuleEvaluationError",
    "RuleId",
    "RuleOutcome",
    "RuleResult",
    "Severity",
    "Verdict",
    "derive_verdict",
]
