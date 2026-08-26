from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from lazycoder.domain.enums import RuleId, RuleOutcome, Severity, Verdict


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


@dataclass(frozen=True)
class CodeBlock:
    """One reviewable chunk of a diff: a single hunk's post-change content.

    Plain dataclass, not a pydantic model: `code` must survive verbatim, and
    the strict models strip whitespace, which would destroy indentation.
    """

    file: str
    start_line: int
    code: str

    @property
    def end_line(self) -> int:
        """Last post-change line number covered by this block."""
        return self.start_line + self.code.count("\n")

    def covers(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line

    def numbered(self) -> str:
        """The block with real post-change line numbers, for citation."""
        return "\n".join(
            f"{self.start_line + offset}\t{line}"
            for offset, line in enumerate(self.code.split("\n"))
        )


class CodeLocation(_StrictModel):
    """Exact code location cited by a finding."""

    file: str = Field(min_length=1)
    line: int = Field(ge=1, description="1-based start line")
    end_line: int | None = Field(default=None, ge=1, description="1-based end line")

    @model_validator(mode="after")
    def end_line_not_before_start(self) -> CodeLocation:
        if self.end_line is not None and self.end_line < self.line:
            msg = "end_line must be greater than or equal to line"
            raise ValueError(msg)
        return self


class Finding(_StrictModel):
    """A single issue flagged during review; must cite rule, location, and reason."""

    rule_id: RuleId
    location: CodeLocation
    severity: Severity
    reason: str = Field(min_length=1)


class RuleEvaluationError(_StrictModel):
    """A rubric rule that could not be evaluated."""

    rule_id: RuleId
    message: str = Field(min_length=1)


class RuleResult(_StrictModel):
    """Outcome of evaluating one rubric rule against a code block.

    `severity` is the rule's configured weight, copied from the rubric — never
    model output. It is carried here so the verdict is derivable from rule
    outcomes alone, including for abstentions, which produce no finding.
    """

    rule_id: RuleId
    outcome: RuleOutcome
    severity: Severity
    finding: Finding | None = None
    note: str | None = Field(
        default=None, description="why an abstaining rule could not answer"
    )

    @property
    def passed(self) -> bool:
        return self.outcome is RuleOutcome.PASS

    @model_validator(mode="after")
    def finding_matches_outcome(self) -> RuleResult:
        if self.outcome is not RuleOutcome.FAIL:
            if self.finding is not None:
                msg = "only a failed rule may carry a finding"
                raise ValueError(msg)
            return self
        if self.finding is None:
            msg = "failed rule must include a finding"
            raise ValueError(msg)
        if self.finding.rule_id != self.rule_id:
            msg = "finding.rule_id must match rule_result.rule_id"
            raise ValueError(msg)
        if self.finding.severity != self.severity:
            msg = "finding.severity must match the rule's configured severity"
            raise ValueError(msg)
        return self


class ReviewReport(_StrictModel):
    """Structured output of a review run."""

    findings: list[Finding]
    rule_results: list[RuleResult] = Field(default_factory=list)
    rule_errors: list[RuleEvaluationError] = Field(default_factory=list)

    @classmethod
    def from_rule_results(
        cls,
        rule_results: list[RuleResult],
        *,
        rule_errors: list[RuleEvaluationError] | None = None,
    ) -> ReviewReport:
        """Build a report from rule outcomes; findings come from failed rules."""
        findings = [r.finding for r in rule_results if r.finding is not None]
        return cls(
            findings=findings,
            rule_results=rule_results,
            rule_errors=rule_errors or [],
        )

    @classmethod
    def merge(cls, reports: list[ReviewReport]) -> ReviewReport:
        """Combine per-block reports into one global report."""
        return cls.from_rule_results(
            [result for report in reports for result in report.rule_results],
            rule_errors=[error for report in reports for error in report.rule_errors],
        )

    @property
    def abstentions(self) -> list[RuleResult]:
        """Rules that declined to answer for lack of context."""
        return [
            result
            for result in self.rule_results
            if result.outcome is RuleOutcome.INSUFFICIENT_CONTEXT
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> Verdict:
        from lazycoder.domain.aggregator import derive_verdict

        return derive_verdict(
            self.rule_results, evaluation_errors=bool(self.rule_errors)
        )

    @model_validator(mode="after")
    def findings_align_with_rule_results(self) -> ReviewReport:
        def key(finding: Finding) -> tuple[RuleId, str, int, str]:
            return (
                finding.rule_id,
                finding.location.file,
                finding.location.line,
                finding.reason,
            )

        from_rules = {
            key(result.finding)
            for result in self.rule_results
            if result.finding is not None
        }
        reported = {key(finding) for finding in self.findings}
        if from_rules - reported:
            msg = "every failed rule_result finding must appear in findings"
            raise ValueError(msg)
        # The verdict is derived from rule_results, so a finding with no rule
        # behind it would be invisible to it — an unrepresentable report.
        if reported - from_rules:
            msg = "every finding must come from a failed rule_result"
            raise ValueError(msg)
        return self
