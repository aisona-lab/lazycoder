"""Stage 3a: the hunk is reviewed inside its file; only the hunk is citable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import block
from lazycoder import cli
from lazycoder.agent_mode import block_id, build_packet, check_answers
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.context import (
    CONTEXT_RADIUS,
    ContextMismatchError,
    from_repo,
    from_sidecar,
    load_sidecar,
    with_context,
)
from lazycoder.corpus import load_corpus
from lazycoder.domain import RuleId, Verdict
from lazycoder.reviewers import SingleRuleReviewer

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "corpus" / "seed.jsonl"
SIDECAR = REPO / "corpus" / "seed.context.jsonl"

FILE = "\n".join(f"line_{n} = {n}" for n in range(1, 401))
HUNK = block("line_200 = 200\nline_201 = 201", file="pkg/mod.py", start_line=200)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_window_is_radius_lines_each_side_with_real_numbers() -> None:
    ctx = with_context(HUNK, FILE)

    assert ctx.context_start == 200 - CONTEXT_RADIUS
    view = ctx.review_view().split("\n")
    assert len(view) == 2 + 2 * CONTEXT_RADIUS
    assert view[0] == f"{200 - CONTEXT_RADIUS}\tline_{200 - CONTEXT_RADIUS} = 80"
    marked = [ln for ln in view if ln.split("\t")[0].endswith("*")]
    assert marked == ["200*\tline_200 = 200", "201*\tline_201 = 201"]


def test_window_is_clipped_at_file_edges() -> None:
    ctx = with_context(block("line_2 = 2", file="m.py", start_line=2), FILE)

    assert ctx.context_start == 1
    assert ctx.review_view().split("\n")[1] == "2*\tline_2 = 2"


def test_a_file_without_the_hunk_at_its_lines_is_refused() -> None:
    with pytest.raises(ContextMismatchError, match="does not contain this hunk"):
        with_context(block("line_200 = 200", start_line=199), FILE)


def test_context_changes_the_block_id() -> None:
    assert block_id(HUNK) != block_id(with_context(HUNK, FILE))


def test_without_context_the_view_is_the_old_numbering() -> None:
    assert HUNK.review_view() == HUNK.numbered()


def test_prompt_explains_markers_and_still_rejects_context_citations(
    rubric: ReviewRulesConfig,
) -> None:
    ctx = with_context(HUNK, FILE)
    rule = rubric.rules[0]

    prompt = SingleRuleReviewer.build_prompt(ctx, rule)
    assert "cite only `*` lines" in prompt
    assert "150\tline_150 = 150" in prompt
    # A line that is shown as context is still not citable.
    payload = {
        "answers": [
            {
                "block_id": block_id(ctx),
                "rule_id": r.id.value,
                **(
                    {"outcome": "fail", "line": 150, "reason": "context line"}
                    if r.id is rule.id
                    else {"outcome": "pass"}
                ),
            }
            for r in rubric.rules
        ]
    }
    report = check_answers([ctx], rubric, payload)
    assert report.verdict is Verdict.REQUEST_CHANGES
    assert "outside the reviewed hunk" in report.rule_errors[0].message


def test_prompt_without_context_is_unchanged(rubric: ReviewRulesConfig) -> None:
    prompt = SingleRuleReviewer.build_prompt(HUNK, rubric.rules[0])
    assert (
        "post-change lines 200-201. Each line is shown as its real line number,"
        " a tab, then the source.\n" in prompt
    )


def test_packet_carries_the_marked_window(rubric: ReviewRulesConfig) -> None:
    packet = build_packet([with_context(HUNK, FILE)], rubric, preset="full")

    code = packet["blocks"][0]["code"]
    assert "200*\tline_200 = 200" in code
    assert any("cite only `*` lines" in line for line in packet["instructions"])


# --- sources ---


def test_from_repo_reads_the_checkout(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(FILE, encoding="utf-8")

    [ctx] = from_repo([HUNK], tmp_path)
    assert ctx.context is not None

    with pytest.raises(ContextMismatchError, match="cannot read context"):
        from_repo([HUNK], tmp_path / "elsewhere")


def test_committed_sidecar_matches_every_corpus_hunk() -> None:
    windows = load_sidecar(SIDECAR)
    hunks = load_corpus(SEED)

    assert set(windows) == {h.id for h in hunks}
    for hunk in hunks:
        ctx = from_sidecar(hunk.block(), windows[hunk.id], hunk.id)
        assert ctx.context is not None
        assert len(ctx.context.split("\n")) <= len(hunk.code.split("\n")) + 2 * (
            CONTEXT_RADIUS
        )


def test_sidecar_that_lost_the_hunk_is_refused(tmp_path: Path) -> None:
    hunk = load_corpus(SEED)[0]
    start, text = load_sidecar(SIDECAR)[hunk.id]
    with pytest.raises(ContextMismatchError, match=hunk.id):
        from_sidecar(hunk.block(), (start + 1, text), hunk.id)

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(ContextMismatchError, match="not a context row"):
        load_sidecar(bad)


# --- CLI ---

DIFF = (
    "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -200,1 +200,2 @@\n"
    " line_200 = 200\n+line_201 = 201\n"
)


def _repo(tmp_path: Path, text: str = FILE) -> Path:
    root = tmp_path / "checkout"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text(text, encoding="utf-8")
    return root


def test_cli_diff_round_trip_with_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path)
    diff = tmp_path / "c.diff"
    diff.write_text(DIFF, encoding="utf-8")
    out = tmp_path / "p.json"
    common = ["--preset", "security", "--context", str(root)]

    assert cli.main(["packet", str(diff), "--out", str(out), *common]) == 0
    packet = json.loads(out.read_text(encoding="utf-8"))
    real = [b for b in packet["blocks"] if b["file"] == "pkg/mod.py"]
    assert "201*\tline_201 = 201" in real[0]["code"]

    answers = tmp_path / "a.json"
    answers.write_text(
        json.dumps(
            {
                "answers": [
                    {"block_id": b["block_id"], "rule_id": "R7", "outcome": "pass"}
                    for b in packet["blocks"]
                ]
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    code = cli.main(["check", str(diff), "--answers", str(answers), *common])
    # Rubber stamp: the canary is missed, so never APPROVE.
    assert code == cli.EXIT_CODES[Verdict.REQUEST_CHANGES]
    assert "canaries: 0/1 caught" in capsys.readouterr().out


def test_cli_refuses_a_checkout_that_does_not_match_the_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path, FILE.replace("line_201 = 201", "line_201 = 0"))
    diff = tmp_path / "c.diff"
    diff.write_text(DIFF, encoding="utf-8")

    code = cli.main(["packet", str(diff), "--context", str(root)])
    assert code == cli.EXIT_ERROR
    assert "does not contain this hunk" in capsys.readouterr().err


def test_cli_context_does_not_apply_to_evals() -> None:
    with pytest.raises(SystemExit):
        cli.main(["packet", "--evals", "--context", "x"])


def test_cli_corpus_with_context_scores_an_oracle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "p.json"
    ctx = ["--context", str(SIDECAR), "--preset", "security"]
    assert cli.main(["packet", "--corpus", str(SEED), "--out", str(out), *ctx]) == 0
    packet = json.loads(out.read_text(encoding="utf-8"))
    hunks = load_corpus(SEED)
    windows = load_sidecar(SIDECAR)
    expected = {
        block_id(from_sidecar(h.block(), windows[h.id], h.id)): set(h.expect_rules)
        for h in hunks
    }
    answers = [
        {
            "block_id": b["block_id"],
            "rule_id": "R7",
            **(
                {"outcome": "fail", "line": b["start_line"], "reason": "labelled"}
                if RuleId.R7 in expected[b["block_id"]]
                else {"outcome": "pass"}
            ),
        }
        for b in packet["blocks"]
    ]
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"answers": answers}), encoding="utf-8")
    capsys.readouterr()

    code = cli.main(["check", "--corpus", str(SEED), "--answers", str(path), *ctx])

    out_text = capsys.readouterr().out
    assert code == 0
    assert "hunk recall 100%  (5/5" in out_text
