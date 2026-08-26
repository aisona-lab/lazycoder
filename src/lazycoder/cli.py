from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from lazycoder import decision_log
from lazycoder.config import load_all_configs
from lazycoder.config.exceptions import ConfigLoadError
from lazycoder.domain import ReviewReport, Verdict
from lazycoder.llm.anthropic_client import AnthropicClient
from lazycoder.orchestrator import review_diff
from lazycoder.reviewers import SingleRuleReviewer

EXIT_CODES = {Verdict.APPROVE: 0, Verdict.REQUEST_CHANGES: 1, Verdict.BLOCK: 2}
EXIT_ERROR = 3


def _default_config_dir() -> Path:
    # Installed wheels bundle the rubric as package data; a repo checkout
    # falls back to the top-level config/ directory.
    bundled = Path(__file__).resolve().parent / "config_defaults"
    if bundled.is_dir():
        return bundled
    from lazycoder.config.loader import DEFAULT_CONFIG_DIR

    return DEFAULT_CONFIG_DIR


def _render(report: ReviewReport) -> str:
    lines = [f"verdict: {report.verdict.value}"]
    for finding in report.findings:
        location = f"{finding.location.file}:{finding.location.line}"
        lines.append(
            f"  {finding.rule_id.value} {location}"
            f" [{finding.severity.value}] {finding.reason}"
        )
    for result in report.abstentions:
        lines.append(
            f"  {result.rule_id.value} [{result.severity.value}]"
            f" insufficient context: {result.note or 'not stated'}"
        )
    for error in report.rule_errors:
        lines.append(f"  ERROR {error.rule_id.value}: {error.message}")
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
    parser.add_argument(
        "--log",
        help=(
            "append one JSON decision record per run to this file"
            " (run id, model, rubric hash, every rule outcome, verdict)"
        ),
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

    started_at = datetime.now(UTC)
    try:
        config_dir = Path(args.config) if args.config else _default_config_dir()
        rubric = load_all_configs(config_dir).review_rules
        client = AnthropicClient()
        report = review_diff(SingleRuleReviewer(client=client), diff_text, rubric)
    except (
        ConfigLoadError,
        RuntimeError,
        anthropic.APIError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not report.rule_results and not report.rule_errors:
        # Hard rule: never APPROVE unless every rule was evaluated — an empty
        # diff evaluated nothing, so it gets an error, not a green verdict.
        print("error: no reviewable hunks found in the diff", file=sys.stderr)
        return EXIT_ERROR

    if args.log:
        decision_log.append(
            Path(args.log),
            decision_log.build_record(
                report=report,
                diff_text=diff_text,
                rubric=rubric,
                model=getattr(client, "model", "unknown"),
                started_at=started_at,
            ),
        )

    print(report.model_dump_json(indent=2) if args.json else _render(report))
    return EXIT_CODES[report.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
