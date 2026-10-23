from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from lazycoder.config.models import (
    EvalCase,
    EvalsConfig,
    ExpectedFinding,
    ReviewRulesConfig,
)
from lazycoder.domain import (
    CodeBlock,
    CodeLocation,
    Finding,
    ReviewReport,
    RuleId,
    RuleOutcome,
    RuleResult,
    Verdict,
    derive_verdict,
)
from lazycoder.reviewers import SingleRuleReviewer


@dataclass(frozen=True)
class EvalResult:
    """Outcome of one eval case: what it caught, what it invented, what it ducked."""

    case_id: str
    passed: bool
    expected_rule_ids: frozenset[RuleId]
    actual_rule_ids: frozenset[RuleId]
    abstained_rule_ids: frozenset[RuleId]
    expected_verdict: Verdict
    actual_verdict: Verdict

    @property
    def true_positives(self) -> frozenset[RuleId]:
        return self.expected_rule_ids & self.actual_rule_ids

    @property
    def false_positives(self) -> frozenset[RuleId]:
        """Rules that fired without being expected — the number that kills adoption."""
        return self.actual_rule_ids - self.expected_rule_ids

    @property
    def false_negatives(self) -> frozenset[RuleId]:
        return self.expected_rule_ids - self.actual_rule_ids


@dataclass(frozen=True)
class RuleStats:
    """Per-rule behaviour across the whole suite."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    abstentions: int = 0
    evaluations: int = 0

    @property
    def abstention_rate(self) -> float:
        """How often this rule declines to answer. High means wrong context level."""
        return self.abstentions / self.evaluations if self.evaluations else 0.0


@dataclass(frozen=True)
class EvalSummary:
    """Suite-level scores. Precision is reported because it is now measured."""

    cases_passed: int
    cases_total: int
    true_positives: int
    false_positives: int
    false_negatives: int
    per_rule: dict[RuleId, RuleStats] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        fired = self.true_positives + self.false_positives
        return self.true_positives / fired if fired else 1.0

    @property
    def recall(self) -> float:
        expected = self.true_positives + self.false_negatives
        return self.true_positives / expected if expected else 1.0


def case_block(case: EvalCase) -> CodeBlock:
    """Eval snippets are treated as a one-hunk file so citations are anchored."""
    return CodeBlock(file=f"{case.id}.py", start_line=1, code=case.input_code)


def derive_expected_verdict(
    case: EvalCase, findings: list[ExpectedFinding], rubric: ReviewRulesConfig
) -> Verdict:
    """The verdict the rubric's own policy gives if exactly these rules fail."""
    severity = {rule.id: rule.severity_if_unjustified for rule in rubric.rules}
    location = CodeLocation(file=case_block(case).file, line=1)
    failed = [
        RuleResult(
            rule_id=f.rule_id,
            outcome=RuleOutcome.FAIL,
            severity=severity[f.rule_id],
            finding=Finding(
                rule_id=f.rule_id,
                location=location,
                severity=severity[f.rule_id],
                reason=f.reason,
            ),
        )
        for f in findings
    ]
    return derive_verdict(failed, evaluation_errors=False)


def expected_for(
    case: EvalCase, rubric: ReviewRulesConfig
) -> tuple[frozenset[RuleId], Verdict]:
    """What the case expects from the rules this rubric (or preset) asks.

    On the full rubric that is the fixture's own expectation. A preset that
    drops an expected rule cannot be blamed for not firing it, so the
    expectation is narrowed and the verdict re-derived by the aggregator's
    own policy, never by a second opinion.
    """
    in_scope = {rule.id for rule in rubric.rules}
    kept = [f for f in case.expect_findings if f.rule_id in in_scope]
    expected = frozenset(f.rule_id for f in kept)
    if len(kept) == len(case.expect_findings):
        return expected, case.expect_verdict
    return expected, derive_expected_verdict(case, kept, rubric)


def score_case(
    case: EvalCase, report: ReviewReport, rubric: ReviewRulesConfig
) -> EvalResult:
    """Score one report: expected rules fire, nothing else fires, verdict matches."""
    expected, expected_verdict = expected_for(case, rubric)
    actual = frozenset(f.rule_id for f in report.findings)
    abstained = frozenset(r.rule_id for r in report.abstentions)
    passed = expected == actual and report.verdict == expected_verdict
    return EvalResult(
        case_id=case.id,
        passed=passed,
        expected_rule_ids=expected,
        actual_rule_ids=actual,
        abstained_rule_ids=abstained,
        expected_verdict=expected_verdict,
        actual_verdict=report.verdict,
    )


def run_case(
    reviewer: SingleRuleReviewer, case: EvalCase, rubric: ReviewRulesConfig
) -> EvalResult:
    """Run the reviewer on one case and score it."""
    return score_case(case, reviewer.review_rubric(case_block(case), rubric), rubric)


def run_evals(
    reviewer: SingleRuleReviewer, evals: EvalsConfig, rubric: ReviewRulesConfig
) -> list[EvalResult]:
    """Run every eval case against the reviewer.

    Client-agnostic by construction: the reviewer wraps any LLMClient, so the
    same harness scores the fake today and the real model after a one-line swap.
    """
    return [run_case(reviewer, case, rubric) for case in evals.cases]


def summarize(results: list[EvalResult], rubric: ReviewRulesConfig) -> EvalSummary:
    """Aggregate case results into precision, recall and per-rule abstention."""
    tp: Counter[RuleId] = Counter()
    fp: Counter[RuleId] = Counter()
    fn: Counter[RuleId] = Counter()
    abstained: Counter[RuleId] = Counter()
    for result in results:
        tp.update(result.true_positives)
        fp.update(result.false_positives)
        fn.update(result.false_negatives)
        abstained.update(result.abstained_rule_ids)

    per_rule = {
        rule.id: RuleStats(
            true_positives=tp[rule.id],
            false_positives=fp[rule.id],
            false_negatives=fn[rule.id],
            abstentions=abstained[rule.id],
            evaluations=len(results),
        )
        for rule in rubric.rules
    }
    return EvalSummary(
        cases_passed=sum(1 for r in results if r.passed),
        cases_total=len(results),
        true_positives=sum(tp.values()),
        false_positives=sum(fp.values()),
        false_negatives=sum(fn.values()),
        per_rule=per_rule,
    )


def format_case_line(result: EvalResult) -> str:
    mark = "PASS" if result.passed else "FAIL"
    parts = [f"{mark:4} {result.case_id:4}"]
    parts.append(f"verdict {result.actual_verdict.value}")
    if result.actual_verdict != result.expected_verdict:
        parts[-1] += f" (expected {result.expected_verdict.value})"
    if result.false_negatives:
        missed = sorted(r.value for r in result.false_negatives)
        parts.append("missed " + ",".join(missed))
    if result.false_positives:
        noise = sorted(r.value for r in result.false_positives)
        parts.append("noise " + ",".join(noise))
    if result.abstained_rule_ids:
        parts.append(
            "abstained " + ",".join(sorted(r.value for r in result.abstained_rule_ids))
        )
    return "  ".join(parts)


def format_summary(summary: EvalSummary) -> list[str]:
    lines = [
        "",
        f"cases     {summary.cases_passed}/{summary.cases_total}",
        f"precision {summary.precision:.2f}"
        f"  ({summary.true_positives} true, {summary.false_positives} false)",
        f"recall    {summary.recall:.2f}"
        f"  ({summary.true_positives} caught, {summary.false_negatives} missed)",
        "",
        f"{'rule':6}{'tp':>4}{'fp':>4}{'fn':>4}{'abstain':>9}",
    ]
    for rule_id, stats in summary.per_rule.items():
        lines.append(
            f"{rule_id.value:6}{stats.true_positives:>4}{stats.false_positives:>4}"
            f"{stats.false_negatives:>4}{stats.abstention_rate:>8.0%}"
        )
    return lines
