from __future__ import annotations

import argparse
import sys
from pathlib import Path

import anthropic

from argus.config import load_all_configs
from argus.config.exceptions import ConfigLoadError
from argus.domain import ReviewReport, Verdict
from argus.llm.anthropic_client import AnthropicClient
from argus.orchestrator import review_diff
from argus.reviewers import LLMReviewerParseError, SingleRuleReviewer

EXIT_CODES = {Verdict.APPROVE: 0, Verdict.REQUEST_CHANGES: 1, Verdict.BLOCK: 2}
EXIT_ERROR = 3


def _default_config_dir() -> Path:
    # Installed wheels bundle the rubric as package data; a repo checkout
    # falls back to the top-level config/ directory.
    bundled = Path(__file__).resolve().parent / "config_defaults"
    if bundled.is_dir():
        return bundled
    from argus.config.loader import DEFAULT_CONFIG_DIR

    return DEFAULT_CONFIG_DIR


def _render(report: ReviewReport) -> str:
    lines = [f"verdict: {report.verdict.value}"]
    for finding in report.findings:
        location = f"{finding.location.file}:{finding.location.line}"
        lines.append(
            f"  {finding.rule_id.value} {location}"
            f" [{finding.severity.value}] {finding.reason}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lazycoder",
        description=(
            "Review a unified diff against the R1..R17 rubric and return"
            " an APPROVE / REQUEST_CHANGES / BLOCK verdict"
            " (exit codes 0 / 1 / 2). Requires ANTHROPIC_API_KEY."
        ),
    )
    parser.add_argument("diff", help="unified diff file, or '-' for stdin")
    parser.add_argument(
        "--config", help="config directory (defaults to the bundled rubric)"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the full ReviewReport as JSON"
    )
    args = parser.parse_args(argv)

    try:
        if args.diff == "-":
            diff_text = sys.stdin.read()
        else:
            diff_text = Path(args.diff).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read diff: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        config_dir = Path(args.config) if args.config else _default_config_dir()
        rubric = load_all_configs(config_dir).review_rules
        reviewer = SingleRuleReviewer(client=AnthropicClient())
        report = review_diff(reviewer, diff_text, rubric)
    except (
        ConfigLoadError,
        LLMReviewerParseError,
        RuntimeError,
        anthropic.APIError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not report.rule_results:
        # Hard rule: never APPROVE unless every rule was evaluated — an empty
        # diff evaluated nothing, so it gets an error, not a green verdict.
        print("error: no reviewable hunks found in the diff", file=sys.stderr)
        return EXIT_ERROR

    print(report.model_dump_json(indent=2) if args.json else _render(report))
    return EXIT_CODES[report.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
