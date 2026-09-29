from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import PASS_RESPONSE, SQL_INJECTION_CODE, fail_response
from lazycoder import cli, decision_log
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import RuleId, RuleOutcome, Verdict
from lazycoder.llm import FakeLLMClient
from lazycoder.orchestrator import review_diff
from lazycoder.reviewers import SingleRuleReviewer

SQL_INJECTION_DIFF = (
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " def handler(name):\n"
    f"+    {SQL_INJECTION_CODE}\n"
)


def _report(rubric: ReviewRulesConfig):
    responses = [
        (
            fail_response(2, "string-concatenated SQL is injectable")
            if rule.id == RuleId.R7
            else PASS_RESPONSE
        )
        for rule in rubric.rules
    ]
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))
    return review_diff(reviewer, SQL_INJECTION_DIFF, rubric)


def test_record_carries_everything_the_verdict_was_derived_from(
    rubric: ReviewRulesConfig,
) -> None:
    record = decision_log.build_record(
        report=_report(rubric),
        diff_text=SQL_INJECTION_DIFF,
        rubric=rubric,
        model="claude-opus-5",
        started_at=datetime.now(UTC),
    )

    assert record["model"] == "claude-opus-5"
    assert record["verdict"] == Verdict.BLOCK.value
    assert len(record["rubric_sha256"]) == 64
    assert len(record["diff_sha256"]) == 64
    assert record["report"]["findings"][0]["location"]["file"] == "app.py"


def test_verdict_replays_from_the_record_alone(rubric: ReviewRulesConfig) -> None:
    # The deterministic half of the claim "any verdict is replayable": the
    # record plus the aggregator must reproduce the verdict with no model.
    record = decision_log.build_record(
        report=_report(rubric),
        diff_text=SQL_INJECTION_DIFF,
        rubric=rubric,
        model="claude-opus-5",
        started_at=datetime.now(UTC),
    )

    assert decision_log.replay_verdict(record) == record["verdict"]


def test_rubric_hash_changes_when_the_policy_changes(
    rubric: ReviewRulesConfig,
) -> None:
    # A verdict is only defensible next to the rubric that produced it.
    before = decision_log.rubric_hash(rubric)
    edited = rubric.model_copy(deep=True)
    edited.rules[0].severity_if_unjustified = edited.rules[
        0
    ].severity_if_unjustified.__class__("high")

    assert decision_log.rubric_hash(edited) != before


def test_log_is_append_only(tmp_path: Path, rubric: ReviewRulesConfig) -> None:
    path = tmp_path / "runs" / "decisions.jsonl"
    for _ in range(2):
        decision_log.append(
            path,
            decision_log.build_record(
                report=_report(rubric),
                diff_text=SQL_INJECTION_DIFF,
                rubric=rubric,
                model="claude-opus-5",
                started_at=datetime.now(UTC),
            ),
        )

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["run_id"] != records[1]["run_id"]


def test_cli_log_flag_writes_one_record_per_run(
    rubric: ReviewRulesConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    diff_file = tmp_path / "my.diff"
    diff_file.write_text(SQL_INJECTION_DIFF, encoding="utf-8")
    log_file = tmp_path / "decisions.jsonl"
    responses = [
        (
            fail_response(2, "string-concatenated SQL is injectable")
            if rule.id == RuleId.R7
            else PASS_RESPONSE
        )
        for rule in rubric.rules
    ]
    monkeypatch.setattr(
        cli, "AnthropicClient", lambda: FakeLLMClient(responses=responses)
    )

    exit_code = cli.main([str(diff_file), "--log", str(log_file)])

    record = json.loads(log_file.read_text().strip())
    assert exit_code == 2
    assert record["verdict"] == Verdict.BLOCK.value
    outcomes = {r["rule_id"]: r["outcome"] for r in record["report"]["rule_results"]}
    assert outcomes["R7"] == RuleOutcome.FAIL.value
    assert len(outcomes) == len(rubric.rules)


def test_no_record_is_written_when_nothing_was_reviewed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An empty diff exits 3. Logging it would leave an APPROVE in the audit
    # trail for a verdict the CLI never returned.
    diff_file = tmp_path / "empty.diff"
    diff_file.write_text("", encoding="utf-8")
    log_file = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(cli, "AnthropicClient", lambda: FakeLLMClient(responses=[]))

    exit_code = cli.main([str(diff_file), "--log", str(log_file)])

    assert exit_code == 3
    assert not log_file.exists()
