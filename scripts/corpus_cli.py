"""Harvest and score a corpus of real diff hunks.

    # pull candidate hunks from merged PRs (needs gh)
    python scripts/corpus_cli.py harvest --repo psf/requests --prs 8 \
        --out corpus/candidates.jsonl

    # label each line by hand: "label": "clean" | "defective" (+ expect_rules)

    # score the labelled corpus against the live model
    ANTHROPIC_API_KEY=... python scripts/corpus_cli.py run corpus/corpus.jsonl

Harvest emits the post-change side of each hunk, which is what a *clean*
sample is. Defective samples come from bug-fix PRs and are labelled by hand
for now; a --side old extractor is only worth building if that becomes the
bottleneck.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lazycoder.config import load_all_configs  # noqa: E402
from lazycoder.corpus import (  # noqa: E402
    CorpusLoadError,
    HunkResult,
    Label,
    load_corpus,
    report,
    score_hunk,
)
from lazycoder.llm.anthropic_client import AnthropicClient  # noqa: E402
from lazycoder.orchestrator import parse_diff  # noqa: E402
from lazycoder.reviewers import SingleRuleReviewer  # noqa: E402

CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb"}
MIN_HUNK_LINES = 3
# Most recently merged PRs on a popular repo are dependency bumps. Scanning
# them finds nothing and makes an empty harvest look like a broken one.
BOT_AUTHORS = {"dependabot", "pre-commit-ci", "renovate", "github-actions"}
# Most recently merged PRs on a popular repo are dependency bumps. Scanning
# them finds nothing and makes an empty harvest look like a broken one.
BOT_AUTHORS = {"dependabot", "pre-commit-ci", "renovate", "github-actions"}


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
    print(f"\n{'rule':6}{'noise%':>8}{'caught':>8}{'missed':>8}{'abstain':>9}")
    for rule_id, verdict in summary.per_rule.items():
        print(
            f"{rule_id.value:6}{verdict.clean_noise_rate:>7.0%}"
            f"{verdict.caught:>8}{verdict.missed:>8}"
            f"{verdict.abstention_rate:>8.0%}"
        )
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

    args = parser.parse_args()
    try:
        if args.command == "harvest":
            return harvest(args.repo, args.prs, args.per_pr, args.out, bots=args.bots)
        return run(args.path)
    except (CorpusLoadError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
