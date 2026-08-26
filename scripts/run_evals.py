"""Run config/evals.json against the live model and print the scoreboard.

    ANTHROPIC_API_KEY=... .venv/bin/python scripts/run_evals.py

Costs one model call per rule per case (rules x cases). This is the number the
project lives or dies by, so it prints precision and recall, not just passes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lazycoder.config import load_all_configs  # noqa: E402
from lazycoder.evals import EvalResult, EvalSummary, run_case, summarize  # noqa: E402
from lazycoder.llm.anthropic_client import AnthropicClient  # noqa: E402
from lazycoder.reviewers import SingleRuleReviewer  # noqa: E402


def _case_line(result: EvalResult) -> str:
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


def _summary_lines(summary: EvalSummary) -> list[str]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="only these case ids")
    args = parser.parse_args()

    config = load_all_configs()
    rubric = config.review_rules
    cases = config.evals.cases
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case.id in wanted]

    calls = len(cases) * len(rubric.rules)
    print(f"{len(cases)} cases x {len(rubric.rules)} rules = {calls} model calls\n")

    reviewer = SingleRuleReviewer(client=AnthropicClient())
    results = []
    for case in cases:
        result = run_case(reviewer, case, rubric)
        results.append(result)
        print(_case_line(result), flush=True)

    print("\n".join(_summary_lines(summarize(results, rubric))))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
