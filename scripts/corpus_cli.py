"""Harvest, prove, and score a corpus of real diff hunks.

    # pull candidate hunks from merged PRs (needs gh)
    python scripts/corpus_cli.py harvest --repo psf/requests --prs 8 \
        --out corpus/candidates.jsonl

    # label each line by hand: "label": "clean" | "defective" (+ expect_rules)

    # offline Stage 2 proof (no Anthropic key): shape + cull thresholds
    python scripts/corpus_cli.py prove corpus/seed.jsonl \
        --out docs/eval-runs/corpus-prove.txt

    # score the labelled corpus against the live model (needs ANTHROPIC_API_KEY)
    ANTHROPIC_API_KEY=... python scripts/corpus_cli.py run corpus/seed.jsonl

Harvest emits the post-change side of each hunk, which is what a *clean*
sample is. Defective samples come from bug-fix PRs (pre-image) and are
labelled by hand.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lazycoder.config import load_all_configs  # noqa: E402
from lazycoder.corpus import (  # noqa: E402
    DELETE_NOISE_RATE,
    DEMOTE_HIGH_NOISE_RATE,
    FAIL_ON_MAX_HIGH_NOISE_RATE,
    FAIL_ON_MIN_QUIET_RATE,
    MIN_CLEAN_HUNKS,
    MIN_DEFECTIVE_HUNKS,
    STAGE3A_ABSTENTION_RATE,
    STAGE3A_MAX_NOISE_RATE,
    CorpusLoadError,
    CullAction,
    HunkResult,
    Label,
    RuleVerdict,
    corpus_shape,
    cull_plan,
    decide_cull,
    fail_on_gate,
    load_corpus,
    report,
    score_hunk,
)
from lazycoder.domain import RuleId, Severity  # noqa: E402
from lazycoder.llm.anthropic_client import AnthropicClient  # noqa: E402
from lazycoder.orchestrator import parse_diff  # noqa: E402
from lazycoder.reviewers import SingleRuleReviewer  # noqa: E402

CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb"}
MIN_HUNK_LINES = 3
# Most recently merged PRs on a popular repo are dependency bumps. Scanning
# them finds nothing and makes an empty harvest look like a broken one.
BOT_AUTHORS = {"dependabot", "pre-commit-ci", "renovate", "github-actions"}

USER_TZ = ZoneInfo("Europe/Prague")


def _gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        msg = f"gh {' '.join(args)} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def _is_bot(entry: dict) -> bool:
    login = ((entry.get("author") or {}).get("login") or "").lower()
    return any(bot in login for bot in BOT_AUTHORS)


def harvest(repo: str, prs: int, per_pr: int, out: Path, *, bots: bool) -> int:
    listing = json.loads(
        _gh(
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--limit",
            str(prs),
            "--json",
            "number,url,mergeCommit,author",
        )
    )

    lines: list[str] = []
    skipped = {"bot PRs": 0, "non-code files": 0, "hunks under min size": 0}
    for entry in listing:
        number = entry["number"]
        if not bots and _is_bot(entry):
            skipped["bot PRs"] += 1
            continue
        sha = (entry.get("mergeCommit") or {}).get("oid", "unknown")
        try:
            diff = _gh("pr", "diff", str(number), "--repo", repo)
        except RuntimeError as exc:  # a PR whose diff gh cannot fetch
            print(f"  skip PR {number}: {exc}", file=sys.stderr)
            continue

        kept = 0
        for index, block in enumerate(parse_diff(diff)):
            if kept >= per_pr:
                break
            if Path(block.file).suffix not in CODE_SUFFIXES:
                skipped["non-code files"] += 1
                continue
            if block.code.count("\n") + 1 < MIN_HUNK_LINES:
                skipped["hunks under min size"] += 1
                continue
            lines.append(
                json.dumps(
                    {
                        "id": f"{repo.split('/')[-1]}-{number}-{index}",
                        "source": {
                            "repo": repo,
                            "pr": number,
                            "sha": sha,
                            "url": entry.get("url"),
                        },
                        "file": block.file,
                        "start_line": block.start_line,
                        "code": block.code,
                        # Labelling is the human's job. load_corpus refuses to
                        # score a file that still has nulls in it.
                        "label": None,
                        "expect_rules": [],
                        "note": None,
                    }
                )
            )
            kept += 1
        print(f"  PR {number}: {kept} hunk(s)", file=sys.stderr)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n" if lines else "")
    reasons = ", ".join(f"{n} {what}" for what, n in skipped.items() if n)
    print(
        f"{len(lines)} candidate hunk(s) appended to {out}"
        + (f" (skipped: {reasons})" if reasons else ""),
        file=sys.stderr,
    )
    if lines:
        print("label each line, then: corpus_cli.py run " + str(out), file=sys.stderr)
    return 0


def _result_line(result: HunkResult) -> str:
    parts = [f"{result.label.value:9} {result.hunk_id:28}"]
    if result.label is Label.CLEAN:
        parts.append("quiet" if result.is_quiet else "NOISE " + _ids(result.noise))
    else:
        parts.append("caught " + (_ids(result.caught) or "-"))
        if result.missed:
            parts.append("MISSED " + _ids(result.missed))
        if result.unlabelled:
            parts.append("unlabelled " + _ids(result.unlabelled))
    if result.errored:
        parts.append("errors " + _ids(result.errored))
    return "  ".join(parts)


def _ids(rules: frozenset) -> str:
    return ",".join(sorted(rule.value for rule in rules))


def run(path: Path) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "error: ANTHROPIC_API_KEY unset — live corpus scoring is blocked.\n"
            "  Offline half: python scripts/corpus_cli.py prove " + str(path),
            file=sys.stderr,
        )
        return 2

    config = load_all_configs()
    rubric = config.review_rules
    hunks = load_corpus(path)
    clean = sum(1 for h in hunks if h.label is Label.CLEAN)
    print(
        f"{len(hunks)} hunks ({clean} clean, {len(hunks) - clean} defective)"
        f" x {len(rubric.rules)} rules = {len(hunks) * len(rubric.rules)} calls\n",
        file=sys.stderr,
    )

    reviewer = SingleRuleReviewer(client=AnthropicClient())
    results = [score_hunk(reviewer, hunk, rubric) for hunk in hunks]
    for result in results:
        print(_result_line(result), flush=True)

    summary = report(results, rubric)
    print(
        f"\nquiet rate  {summary.quiet_rate:.0%}"
        f"  ({summary.quiet_clean_hunks}/{summary.clean_hunks} clean hunks"
        " drew no comment)"
    )
    print(f"noise       {summary.noise_per_clean_hunk:.2f} findings per clean hunk")
    print(
        f"recall      {summary.recall:.0%}"
        f"  ({summary.caught} caught, {summary.missed} missed)"
    )
    print(
        f"\n{'rule':6}{'noise%':>8}{'caught':>8}{'missed':>8}{'abstain':>9}{'cull':>14}"
    )
    plan = cull_plan(summary, rubric)
    for rule_id, verdict in summary.per_rule.items():
        print(
            f"{rule_id.value:6}{verdict.clean_noise_rate:>7.0%}"
            f"{verdict.caught:>8}{verdict.missed:>8}"
            f"{verdict.abstention_rate:>8.0%}"
            f"{plan[rule_id].value:>14}"
        )
    gate = fail_on_gate(summary, rubric)
    print(f"\nfail-on gate ready: {gate.ready}  ({gate.reason})")
    if not gate.ready:
        print("Action fail-on stays never — metrics do not justify a blocking gate.")
    return 0


def _cull_self_check() -> list[str]:
    """Measurable offline proof that the encoded thresholds match the plan table."""
    cases: list[tuple[str, RuleVerdict, Severity, CullAction]] = [
        (
            "delete: noise>25% and never right",
            RuleVerdict(RuleId.R12, 20, 6, 0, 0, 0, 0, 20),
            Severity.MEDIUM,
            CullAction.DELETE,
        ),
        (
            "demote: high rule noise>10%",
            RuleVerdict(RuleId.R4, 20, 3, 1, 0, 0, 0, 20),
            Severity.HIGH,
            CullAction.DEMOTE,
        ),
        (
            "stage3a: abstains a lot, quiet on clean",
            RuleVerdict(RuleId.R14, 20, 1, 0, 0, 0, 12, 20),
            Severity.MEDIUM,
            CullAction.KEEP_STAGE_3A,
        ),
        (
            "keep: modest noise, sometimes right",
            RuleVerdict(RuleId.R7, 20, 2, 3, 1, 0, 2, 20),
            Severity.HIGH,
            CullAction.KEEP,
        ),
        (
            "delete beats demote when never right",
            RuleVerdict(RuleId.R4, 20, 6, 0, 0, 0, 0, 20),
            Severity.HIGH,
            CullAction.DELETE,
        ),
        (
            "keep: noisy medium with catches (not delete, not demote)",
            RuleVerdict(RuleId.R3, 20, 6, 2, 0, 0, 0, 20),
            Severity.MEDIUM,
            CullAction.KEEP,
        ),
    ]
    failures: list[str] = []
    for name, verdict, severity, expected in cases:
        got = decide_cull(verdict, severity)
        if got is not expected:
            failures.append(f"{name}: expected {expected.value}, got {got.value}")
    return failures


def prove(path: Path, out: Path | None) -> int:
    """Offline Stage 2 proof: labelled corpus shape + cull threshold self-check.

    Does not call the model. Live scoring remains a separate `run` step.
    """
    now = datetime.now(tz=USER_TZ)
    lines: list[str] = [
        "lazycoder Stage 2 — corpus prove (offline)",
        f"date: {now.strftime('%Y-%m-%d %H:%M %Z')} (PT)",
        f"corpus: {path}",
        "",
        "Pre-registered thresholds (hardening-plan.md, 2026-08-26):",
        f"  delete if clean_noise > {DELETE_NOISE_RATE:.0%} and caught == 0",
        f"  demote if clean_noise > {DEMOTE_HIGH_NOISE_RATE:.0%} and severity high",
        f"  stage3a if abstention > {STAGE3A_ABSTENTION_RATE:.0%}"
        f" and clean_noise < {STAGE3A_MAX_NOISE_RATE:.0%}",
        f"  fail-on ready if quiet_rate ≥ {FAIL_ON_MIN_QUIET_RATE:.0%}"
        f" and no high rule > {FAIL_ON_MAX_HIGH_NOISE_RATE:.0%} clean noise",
        f"  shape: ≥{MIN_CLEAN_HUNKS} clean, ≥{MIN_DEFECTIVE_HUNKS} defective",
        "",
    ]

    hunks = load_corpus(path)
    shape = corpus_shape(hunks)
    lines.append(f"shape: {shape.summary}")
    repos = sorted({h.source.repo for h in hunks})
    lines.append(f"repos: {', '.join(repos)}")
    lines.append(f"hunks: {len(hunks)}")

    cull_failures = _cull_self_check()
    if cull_failures:
        lines.append("cull self-check: FAIL")
        lines.extend(f"  - {f}" for f in cull_failures)
    else:
        lines.append("cull self-check: PASS (6/6 decision-table cases)")

    key_present = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if key_present:
        lines.append(
            "live scoring: API key present — run `corpus_cli.py run` separately"
        )
        live_status = "KEY_PRESENT"
    else:
        lines.append(
            "live scoring: BLOCKED — ANTHROPIC_API_KEY unset "
            "(no credits/key in this environment; offline half only)"
        )
        live_status = "BLOCKED"

    lines.append(
        "fail-on: stays never until live corpus metrics satisfy the gate "
        "(no live scores in this prove run — gate not claimed ready)"
    )
    lines.append("")

    offline_ok = shape.ok and not cull_failures
    lines.append(
        f"OFFLINE_PROVE: {'PASS' if offline_ok else 'FAIL'}  "
        f"LIVE_SCORING: {live_status}  FAIL_ON: never"
    )

    text = "\n".join(lines) + "\n"
    sys.stdout.write(text)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"artifact: {out}", file=sys.stderr)

    if not offline_ok:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    h = sub.add_parser("harvest", help="pull candidate hunks from merged PRs")
    h.add_argument("--repo", required=True, help="owner/name")
    h.add_argument("--prs", type=int, default=10, help="merged PRs to scan")
    h.add_argument("--per-pr", type=int, default=3, help="max hunks kept per PR")
    h.add_argument("--out", type=Path, default=Path("corpus/candidates.jsonl"))
    h.add_argument("--bots", action="store_true", help="include dependency-bot PRs")

    r = sub.add_parser("run", help="score a labelled corpus against the live model")
    r.add_argument("path", type=Path)

    p = sub.add_parser(
        "prove",
        help="offline Stage 2 proof: corpus shape + cull threshold self-check",
    )
    p.add_argument("path", type=Path, help="labelled corpus JSONL")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("docs/eval-runs/corpus-prove.txt"),
        help="where to write the prove artifact",
    )
    p.add_argument(
        "--no-artifact",
        action="store_true",
        help="print only; do not write --out",
    )

    args = parser.parse_args()
    try:
        if args.command == "harvest":
            return harvest(args.repo, args.prs, args.per_pr, args.out, bots=args.bots)
        if args.command == "prove":
            out = None if args.no_artifact else args.out
            return prove(args.path, out)
        return run(args.path)
    except (CorpusLoadError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
