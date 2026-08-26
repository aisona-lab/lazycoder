from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from lazycoder.config.models import EvalCase, EvalsConfig, ReviewRulesConfig
from lazycoder.domain import CodeBlock, RuleId, Verdict
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


def _case_block(case: EvalCase) -> CodeBlock:
    """Eval snippets are treated as a one-hunk file so citations are anchored."""
    return CodeBlock(file=f"{case.id}.py", start_line=1, code=case.input_code)


def run_case(
    reviewer: SingleRuleReviewer, case: EvalCase, rubric: ReviewRulesConfig
) -> EvalResult:
    """Score one case: expected rules fire, nothing else fires, verdict matches."""
    report = reviewer.review_rubric(_case_block(case), rubric)
    expected = frozenset(f.rule_id for f in case.expect_findings)
    actual = frozenset(f.rule_id for f in report.findings)
    abstained = frozenset(r.rule_id for r in report.abstentions)
    passed = expected == actual and report.verdict == case.expect_verdict
    return EvalResult(
        case_id=case.id,
        passed=passed,
        expected_rule_ids=expected,
        actual_rule_ids=actual,
        abstained_rule_ids=abstained,
        expected_verdict=case.expect_verdict,
        actual_verdict=report.verdict,
    )


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
