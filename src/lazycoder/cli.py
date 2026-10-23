from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from lazycoder import decision_log, scaffold
from lazycoder.agent_mode import (
    AgentAnswersError,
    build_packet,
    check_answers,
    check_blocks,
)
from lazycoder.config import AppConfig, apply_preset, load_all_configs, load_presets
from lazycoder.config.exceptions import ConfigLoadError
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import ReviewReport, Verdict
from lazycoder.evals import (
    case_block,
    format_case_line,
    format_summary,
    score_case,
    summarize,
)
from lazycoder.llm.anthropic_client import AnthropicClient
from lazycoder.orchestrator import parse_diff, review_diff
from lazycoder.reviewers import SingleRuleReviewer

EXIT_CODES = {Verdict.APPROVE: 0, Verdict.REQUEST_CHANGES: 1, Verdict.BLOCK: 2}
EXIT_ERROR = 3
EXIT_REPLAY_MISMATCH = 1


def _default_config_dir() -> Path:
    # Installed wheels bundle the rubric as package data; a repo checkout
    # falls back to the top-level config/ directory.
    bundled = Path(__file__).resolve().parent / "config_defaults"
    if bundled.is_dir():
        return bundled
    from lazycoder.config.loader import DEFAULT_CONFIG_DIR

    return DEFAULT_CONFIG_DIR


def _load(
    config_arg: str | None, preset: str | None
) -> tuple[AppConfig, ReviewRulesConfig, str]:
    """All configs, plus the rubric narrowed to the chosen preset and its name."""
    config_dir = Path(config_arg) if config_arg else _default_config_dir()
    app = load_all_configs(config_dir)
    presets = load_presets(config_dir)
    name = preset or presets.default
    return app, apply_preset(app.review_rules, presets, name), name


def _read_diff(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    return Path(arg).read_text(encoding="utf-8")


def _add_rubric_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", help="config directory (defaults to the bundled rubric)"
    )
    parser.add_argument(
        "--preset",
        help="rule subset from presets.json: full | focused | security"
        " (default: the config's default, full)",
    )


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


def _replay_main(argv: list[str]) -> int:
    """Recompute derive_verdict from a decision log. Never calls the model."""
    parser = argparse.ArgumentParser(
        prog="lazycoder replay",
        description=(
            "Recompute each recorded verdict from rule_results alone "
            "(no model call). Exit 0 if every record matches, 1 on drift."
        ),
    )
    parser.add_argument(
        "log",
        help="JSONL decision log written by `lazycoder --log PATH`",
    )
    args = parser.parse_args(argv)

    path = Path(args.log)
    try:
        rows = decision_log.replay_log(path)
    except OSError as exc:
        print(f"error: cannot read log: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not rows:
        print("error: decision log is empty", file=sys.stderr)
        return EXIT_ERROR

    mismatches = 0
    for run_id, recorded, derived, ok in rows:
        mark = "OK" if ok else "DRIFT"
        print(f"{mark:5} {run_id}  recorded={recorded}  derived={derived}")
        if not ok:
            mismatches += 1

    if mismatches:
        print(
            f"error: {mismatches}/{len(rows)} record(s) drifted",
            file=sys.stderr,
        )
        return EXIT_REPLAY_MISMATCH
    print(f"{len(rows)} record(s) replayed; verdicts match")
    return 0


def _review_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="lazycoder",
        description=(
            "Review a unified diff against the R1..R17 rubric and return"
            " an APPROVE / REQUEST_CHANGES / BLOCK verdict"
            " (exit codes 0 / 1 / 2). Requires ANTHROPIC_API_KEY."
            " Keyless subcommands: `packet` / `check` (your own agent is the"
            " model), `init` (install the agent skill), `replay` (recompute"
            " verdicts from a decision log)."
        ),
    )
    parser.add_argument("diff", help="unified diff file, or '-' for stdin")
    _add_rubric_args(parser)
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
        diff_text = _read_diff(args.diff)
    except OSError as exc:
        print(f"error: cannot read diff: {exc}", file=sys.stderr)
        return EXIT_ERROR

    started_at = datetime.now(UTC)
    try:
        _, rubric, preset = _load(args.config, args.preset)
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
                preset=preset,
            ),
        )

    print(report.model_dump_json(indent=2) if args.json else _render(report))
    return EXIT_CODES[report.verdict]


def _packet_main(argv: list[str]) -> int:
    """Write the review packet the user's agent answers. Never calls a model."""
    parser = argparse.ArgumentParser(
        prog="lazycoder packet",
        description=(
            "Emit every (hunk, rule) question as JSON for your own coding"
            " agent to answer. No API key. Answer it, then run"
            " `lazycoder check`."
        ),
    )
    parser.add_argument("diff", nargs="?", help="unified diff file, or '-'")
    parser.add_argument(
        "--evals", action="store_true", help="packet the bundled eval fixtures"
    )
    _add_rubric_args(parser)
    parser.add_argument("--out", help="write the packet here instead of stdout")
    args = parser.parse_args(argv)
    if args.evals == bool(args.diff):
        parser.error("give a diff or --evals (exactly one)")

    try:
        app, rubric, preset = _load(args.config, args.preset)
        if args.evals:
            blocks = [case_block(case) for case in app.evals.cases]
        else:
            blocks = parse_diff(_read_diff(args.diff))
    except (ConfigLoadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not blocks:
        print("error: no reviewable hunks found in the diff", file=sys.stderr)
        return EXIT_ERROR

    packet = build_packet(blocks, rubric, preset=preset)
    text = json.dumps(packet, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(
            f"packet: {len(blocks)} block(s) x {len(rubric.rules)} rule(s)"
            f" = {packet['expected_answers']} answers expected -> {out}"
        )
    else:
        print(text)
    return 0


def _check_main(argv: list[str]) -> int:
    """Validate the agent's answers and derive the verdict. Never calls a model."""
    parser = argparse.ArgumentParser(
        prog="lazycoder check",
        description=(
            "Hold your agent's answers to the reviewer contract and derive the"
            " verdict from the rubric (exit 0 / 1 / 2; 3 if the answers do"
            " not match the packet). With --evals, score them instead."
        ),
    )
    parser.add_argument("diff", nargs="?", help="the diff the packet was built from")
    parser.add_argument("--answers", required=True, help='JSON {"answers": [...]}')
    parser.add_argument(
        "--evals", action="store_true", help="score answers to `packet --evals`"
    )
    _add_rubric_args(parser)
    parser.add_argument("--json", action="store_true", help="emit the full report")
    parser.add_argument("--log", help="append one decision record to this file")
    parser.add_argument(
        "--agent", default="unknown", help="who answered, for the decision log"
    )
    args = parser.parse_args(argv)
    if args.evals == bool(args.diff):
        parser.error("give a diff or --evals (exactly one)")

    started_at = datetime.now(UTC)
    try:
        app, rubric, preset = _load(args.config, args.preset)
        payload = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        if args.evals:
            cases = app.evals.cases
            reports = check_blocks([case_block(c) for c in cases], rubric, payload)
            results = [
                score_case(case, report, rubric)
                for case, report in zip(cases, reports, strict=True)
            ]
            for result in results:
                print(format_case_line(result))
            print("\n".join(format_summary(summarize(results, rubric))))
            return 0
        diff_text = _read_diff(args.diff)
        blocks = parse_diff(diff_text)
        if not blocks:
            print("error: no reviewable hunks found in the diff", file=sys.stderr)
            return EXIT_ERROR
        report = check_answers(blocks, rubric, payload)
    except (ConfigLoadError, OSError, AgentAnswersError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except json.JSONDecodeError as exc:
        print(f"error: answers file is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.log:
        decision_log.append(
            Path(args.log),
            decision_log.build_record(
                report=report,
                diff_text=diff_text,
                rubric=rubric,
                model=f"agent:{args.agent}",
                started_at=started_at,
                preset=preset,
            ),
        )
    print(report.model_dump_json(indent=2) if args.json else _render(report))
    return EXIT_CODES[report.verdict]


def _init_main(argv: list[str]) -> int:
    """Install the agent skill into a repo so its own agent runs the review."""
    parser = argparse.ArgumentParser(
        prog="lazycoder init",
        description=(
            "Write a lazycoder-review agent skill into this repo: your coding"
            " agent answers the packet, `lazycoder check` decides. No API key."
        ),
    )
    _add_rubric_args(parser)
    parser.add_argument("--root", default=".", help="repository root (default .)")
    parser.add_argument(
        "--skills-dir",
        default=str(scaffold.DEFAULT_SKILLS_DIR),
        help="where agent skills live (default .claude/skills; .agents/skills"
        " for Codex-style agents)",
    )
    parser.add_argument(
        "--command",
        default=scaffold.default_command(),
        help="how the skill invokes lazycoder (default: pinned uvx)",
    )
    parser.add_argument(
        "--agent", default="claude-code", help="agent name for the decision log"
    )
    parser.add_argument("--force", action="store_true", help="overwrite the skill")
    args = parser.parse_args(argv)

    try:
        # Validates the preset name now, not when the agent first runs it.
        _, _, preset = _load(args.config, args.preset)
        written = scaffold.write_skill(
            Path(args.root),
            preset=preset,
            command=args.command,
            agent=args.agent,
            skills_dir=Path(args.skills_dir),
            force=args.force,
        )
    except (ConfigLoadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for path in written:
        print(f"wrote {path}")
    print(f'preset {preset}. Ask your agent: "run the lazycoder-review skill".')
    return 0


_SUBCOMMANDS = {
    "replay": _replay_main,
    "packet": _packet_main,
    "check": _check_main,
    "init": _init_main,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in _SUBCOMMANDS:
        return _SUBCOMMANDS[args[0]](args[1:])
    return _review_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
