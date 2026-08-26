from __future__ import annotations

from pathlib import Path

import pytest

from conftest import PASS_RESPONSE, SQL_INJECTION_CODE, fail_response
from lazycoder import cli
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import RuleId
from lazycoder.llm import FakeLLMClient

SQL_INJECTION_DIFF = (
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n"
    " def handler(name):\n"
    f"+    {SQL_INJECTION_CODE}\n"
)

R7_FINDING_RESPONSE = fail_response(2, "string-concatenated SQL is injectable")


def test_cli_reviews_diff_and_maps_verdict_to_exit_code(
    rubric: ReviewRulesConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    diff_file = tmp_path / "my.diff"
    diff_file.write_text(SQL_INJECTION_DIFF, encoding="utf-8")
    responses = [
        R7_FINDING_RESPONSE if rule.id == RuleId.R7 else PASS_RESPONSE
        for rule in rubric.rules
    ]
    monkeypatch.setattr(
        cli, "AnthropicClient", lambda: FakeLLMClient(responses=responses)
    )

    exit_code = cli.main([str(diff_file)])

    out = capsys.readouterr().out
    assert exit_code == 2  # BLOCK
    assert "verdict: BLOCK" in out
    assert "R7 app.py:2 [high]" in out


def test_cli_refuses_to_approve_an_empty_diff(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    diff_file = tmp_path / "empty.diff"
    diff_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "AnthropicClient", lambda: FakeLLMClient(responses=[]))

    exit_code = cli.main([str(diff_file)])

    assert exit_code == cli.EXIT_ERROR
    assert "no reviewable hunks" in capsys.readouterr().err
