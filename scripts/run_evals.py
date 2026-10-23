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
from lazycoder.evals import (  # noqa: E402
    format_case_line,
    format_summary,
    run_case,
    summarize,
)
from lazycoder.llm.anthropic_client import AnthropicClient  # noqa: E402
from lazycoder.reviewers import SingleRuleReviewer  # noqa: E402


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
        print(format_case_line(result), flush=True)

    print("\n".join(format_summary(summarize(results, rubric))))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
