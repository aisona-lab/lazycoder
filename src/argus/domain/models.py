from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from argus.domain.enums import RuleId, Severity, Verdict


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


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


class RuleResult(_StrictModel):
    """Outcome of evaluating one rubric rule against a code block."""

    rule_id: RuleId
    passed: bool
    finding: Finding | None = None

    @model_validator(mode="after")
    def finding_matches_passed(self) -> RuleResult:
        if self.passed and self.finding is not None:
            msg = "passed rule must not include a finding"
            raise ValueError(msg)
        if not self.passed and self.finding is None:
            msg = "failed rule must include a finding"
            raise ValueError(msg)
        if not self.passed and self.finding is not None:
            if self.finding.rule_id != self.rule_id:
                msg = "finding.rule_id must match rule_result.rule_id"
                raise ValueError(msg)
        return self


class ReviewReport(_StrictModel):
    """Structured output of a review run."""

    findings: list[Finding]
    rule_results: list[RuleResult] = Field(default_factory=list)

    @classmethod
    def from_rule_results(cls, rule_results: list[RuleResult]) -> ReviewReport:
        """Build a report from rule outcomes; findings come from failed rules."""
        findings = [r.finding for r in rule_results if r.finding is not None]
        return cls(findings=findings, rule_results=rule_results)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> Verdict:
        from argus.domain.aggregator import aggregate

        return aggregate(self.findings)

    @model_validator(mode="after")
    def findings_align_with_rule_results(self) -> ReviewReport:
        failed_findings = [
            result.finding
            for result in self.rule_results
            if not result.passed and result.finding is not None
        ]
        if not failed_findings:
            return self

        report_keys = {
            (f.rule_id, f.location.file, f.location.line, f.reason)
            for f in self.findings
        }
        for finding in failed_findings:
            key = (
                finding.rule_id,
                finding.location.file,
                finding.location.line,
                finding.reason,
            )
            if key not in report_keys:
                msg = "every failed rule_result finding must appear in findings"
                raise ValueError(msg)
        return self
