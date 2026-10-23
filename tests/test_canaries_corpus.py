"""Canaries catch a rubber-stamping agent; the corpus scores one, both keyless."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conftest import CLEAN_CODE
from lazycoder import cli
from lazycoder.agent_mode import (
    CANARY_PACKS,
    block_id,
    canary_seed,
    check_with_canaries,
    plant_canaries,
)
from lazycoder.config import apply_preset, load_presets
from lazycoder.config.loader import load_fixture_cases
from lazycoder.config.models import EvalCase, ReviewRulesConfig
from lazycoder.corpus import load_corpus
from lazycoder.domain import CodeBlock, RuleId, Verdict
from lazycoder.orchestrator import parse_diff

REPO = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO / "config"
SEED = REPO / "corpus" / "seed.jsonl"

CLEAN_DIFF = (
    "--- a/src/app/greet.py\n"
    "+++ b/src/app/greet.py\n"
    "@@ -0,0 +1,2 @@\n" + "".join(f"+{line}\n" for line in CLEAN_CODE.split("\n"))
)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom() -> None:
        raise AssertionError("agent mode must never construct the API client")

    monkeypatch.setattr(cli, "AnthropicClient", _boom)


@pytest.fixture
def pool() -> list[EvalCase]:
    return load_fixture_cases(CONFIG_DIR, CANARY_PACKS)


def _preset(rubric: ReviewRulesConfig, name: str) -> ReviewRulesConfig:
    return apply_preset(rubric, load_presets(CONFIG_DIR), name)


Answer = Callable[[CodeBlock, RuleId], dict[str, Any]]


def _pass(_: CodeBlock, __: RuleId) -> dict[str, Any]:
    return {"outcome": "pass"}


def _answers(
    blocks: list[CodeBlock], rubric: ReviewRulesConfig, answer: Answer
) -> dict[str, Any]:
    return {
        "answers": [
            {"block_id": block_id(b), "rule_id": r.id.value, **answer(b, r.id)}
            for b in blocks
            for r in rubric.rules
        ]
    }


def _flag(targets: dict[str, set[RuleId]]) -> Answer:
    """An agent that fails exactly `targets[block_id]` and passes the rest."""

    def answer(block: CodeBlock, rule_id: RuleId) -> dict[str, Any]:
        if rule_id in targets.get(block_id(block), set()):
            return {"outcome": "fail", "line": block.start_line, "reason": "defect"}
        return {"outcome": "pass"}

    return answer


# --- planting ---


def test_planting_is_deterministic_and_keeps_real_order(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> None:
    real = parse_diff(CLEAN_DIFF)
    seed = canary_seed(CLEAN_DIFF, "full")

    first = plant_canaries(real, pool, rubric, count=2, seed=seed)
    second = plant_canaries(real, pool, rubric, count=2, seed=seed)

    assert first == second
    planted, canaries = first
    assert len(canaries) == 2
    assert [b for b in planted if b in real] == real
    for canary in canaries:
        assert canary.block.file.startswith("src/app/")
        assert canary.block in planted


def test_only_canaries_the_preset_can_catch_are_planted(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> None:
    security = _preset(rubric, "security")
    _, canaries = plant_canaries(
        parse_diff(CLEAN_DIFF), pool, security, count=5, seed="s"
    )

    assert canaries
    assert all(canary.expect == {RuleId.R7} for canary in canaries)


def test_no_canaries_when_disabled_or_nothing_to_review(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> None:
    real = parse_diff(CLEAN_DIFF)
    assert plant_canaries(real, pool, rubric, count=0, seed="s") == (real, [])
    assert plant_canaries([], pool, rubric, count=1, seed="s") == ([], [])


# --- checking ---


def _planted(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> tuple[list[CodeBlock], list[Any]]:
    return plant_canaries(
        parse_diff(CLEAN_DIFF),
        pool,
        rubric,
        count=1,
        seed=canary_seed(CLEAN_DIFF, "full"),
    )


def test_rubber_stamp_agent_cannot_approve(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> None:
    blocks, canaries = _planted(rubric, pool)

    report, outcome = check_with_canaries(
        blocks, canaries, rubric, _answers(blocks, rubric, _pass)
    )

    assert (outcome.planted, outcome.caught) == (1, 0)
    assert report.verdict is Verdict.REQUEST_CHANGES
    [error] = report.rule_errors
    assert error.message.startswith("canary missed:")


def test_diligent_agent_approves_and_canary_stays_out_of_the_report(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> None:
    blocks, canaries = _planted(rubric, pool)
    [canary] = canaries
    agent = _flag({block_id(canary.block): set(canary.expect)})

    report, outcome = check_with_canaries(
        blocks, canaries, rubric, _answers(blocks, rubric, agent)
    )

    assert (outcome.planted, outcome.caught) == (1, 1)
    assert report.verdict is Verdict.APPROVE
    assert report.findings == []
    assert {r.rule_id for r in report.rule_results} == {r.id for r in rubric.rules}
    assert len(report.rule_results) == len(rubric.rules)  # real hunk only


def test_skipping_the_canary_counts_as_missing_it(
    rubric: ReviewRulesConfig, pool: list[EvalCase]
) -> None:
    blocks, canaries = _planted(rubric, pool)
    real_only = [b for b in blocks if b != canaries[0].block]

    report, outcome = check_with_canaries(
        blocks, canaries, rubric, _answers(real_only, rubric, _pass)
    )

    assert outcome.caught == 0
    assert report.verdict is Verdict.REQUEST_CHANGES
    assert len(report.rule_errors) == 1  # the canary's own gaps are not the user's


# --- CLI ---


def _write(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def _packet(tmp_path: Path, *args: str) -> dict[str, Any]:
    out = tmp_path / "packet.json"
    assert cli.main(["packet", *args, "--out", str(out)]) == 0
    packet: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return packet


def test_cli_canary_round_trip_logs_and_replays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    diff = _write(tmp_path, "c.diff", CLEAN_DIFF)
    packet = _packet(tmp_path, str(diff), "--preset", "security")
    assert len(packet["blocks"]) == 2  # one real hunk, one canary

    # A rubber stamp: pass everything the packet asks.
    answers = _write(
        tmp_path,
        "a.json",
        {
            "answers": [
                {"block_id": b["block_id"], "rule_id": "R7", "outcome": "pass"}
                for b in packet["blocks"]
            ]
        },
    )
    log = tmp_path / "runs.jsonl"
    capsys.readouterr()

    code = cli.main(
        ["check", str(diff), "--answers", str(answers), "--preset", "security"]
        + ["--log", str(log)]
    )

    out = capsys.readouterr().out
    assert code == cli.EXIT_CODES[Verdict.REQUEST_CHANGES]
    assert "canaries: 0/1 caught" in out
    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["canaries"] == {"planted": 1, "caught": 0}
    assert cli.main(["replay", str(log)]) == 0


def test_cli_canary_count_must_match_between_packet_and_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    diff = _write(tmp_path, "c.diff", CLEAN_DIFF)
    packet = _packet(tmp_path, str(diff), "--preset", "security")
    answers = _write(
        tmp_path,
        "a.json",
        {
            "answers": [
                {"block_id": b["block_id"], "rule_id": "R7", "outcome": "pass"}
                for b in packet["blocks"]
            ]
        },
    )

    code = cli.main(
        ["check", str(diff), "--answers", str(answers), "--preset", "security"]
        + ["--canaries", "0"]
    )

    assert code == cli.EXIT_ERROR
    assert "different packet" in capsys.readouterr().err


def test_cli_needs_exactly_one_source(tmp_path: Path) -> None:
    diff = _write(tmp_path, "c.diff", CLEAN_DIFF)
    with pytest.raises(SystemExit):
        cli.main(["packet", str(diff), "--corpus", str(SEED)])
    with pytest.raises(SystemExit):
        cli.main(["packet", "--evals", "--corpus", str(SEED)])


# --- corpus ---


def test_seed_corpus_blocks_are_distinct() -> None:
    hunks = load_corpus(SEED)
    assert len({block_id(h.block()) for h in hunks}) == len(hunks)


def test_corpus_packet_leaks_no_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    packet = _packet(tmp_path, "--corpus", str(SEED), "--preset", "security")
    hunks = load_corpus(SEED)

    assert len(packet["blocks"]) == len(hunks)
    text = json.dumps(packet["blocks"])
    for hunk in hunks:
        assert hunk.id not in text
        assert hunk.source.sha not in text
    assert set(packet["blocks"][0]) == {
        "block_id",
        "file",
        "start_line",
        "end_line",
        "code",
    }
    assert "labels are in" in capsys.readouterr().err


def test_cli_corpus_scores_an_oracle_agent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    packet = _packet(tmp_path, "--corpus", str(SEED), "--preset", "focused")
    by_id = {block_id(h.block()): h for h in load_corpus(SEED)}
    answers = []
    for block in packet["blocks"]:
        expected = set(by_id[block["block_id"]].expect_rules)  # oracle knows all
        for rule in packet["rules"]:
            fires = RuleId(rule["rule_id"]) in expected
            answers.append(
                {
                    "block_id": block["block_id"],
                    "rule_id": rule["rule_id"],
                    "outcome": "fail" if fires else "pass",
                    "line": block["start_line"] if fires else None,
                    "reason": "labelled defect" if fires else None,
                }
            )
    path = _write(tmp_path, "ca.json", {"answers": answers})
    capsys.readouterr()

    code = cli.main(
        ["check", "--corpus", str(SEED), "--answers", str(path), "--preset", "focused"]
        + ["--agent", "oracle"]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "quiet rate  100%" in out
    # Only R7 defects are in scope for focused; R3/R4 ones are not "missed".
    assert "rule recall 100%  (5 caught, 0 missed" in out
    assert "hunk recall 100%  (5/5 defective hunks" in out
    assert "fail-on gate ready:" in out
    assert "agent:oracle, preset focused" in out
