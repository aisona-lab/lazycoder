from __future__ import annotations

from enum import StrEnum


class Verdict(StrEnum):
    """Final review outcome."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    BLOCK = "BLOCK"


class RuleOutcome(StrEnum):
    """How one rubric rule resolved against one code block.

    INSUFFICIENT_CONTEXT is the escape hatch that stops the model from having
    to guess: a rule it cannot answer from the block in front of it abstains
    instead of inventing a pass or a fail.
    """

    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class Severity(StrEnum):
    """Finding severity; drives verdict aggregation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RuleId(StrEnum):
    """Review rubric rule identifiers (R1..R17)."""

    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"
    R7 = "R7"
    R8 = "R8"
    R9 = "R9"
    R10 = "R10"
    R11 = "R11"
    R12 = "R12"
    R13 = "R13"
    R14 = "R14"
    R15 = "R15"
    R16 = "R16"
    R17 = "R17"
