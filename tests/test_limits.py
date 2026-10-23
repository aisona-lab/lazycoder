"""guardrails.json limits hold before anything is spent."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazycoder import cli
from lazycoder.config import load_all_configs
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.limits import measure, over_limits
from lazycoder.orchestrator import parse_diff


def _diff(files: int, hunks_per_file: int = 1) -> str:
    parts = []
    for f in range(files):
        parts.append(f"--- a/pkg/m{f}.py\n+++ b/pkg/m{f}.py\n")
        for h in range(hunks_per_file):
            start = 1 + h * 10
            parts.append(f"@@ -{start},1 +{start},2 @@\n x = {h}\n+y = x + {f}\n")
    return "".join(parts)


@pytest.fixture(autouse=True)
def _no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise AssertionError("a refused scope must not construct the API client")

    monkeypatch.setattr(cli, "AnthropicClient", _boom)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "big.diff"
    path.write_text(text, encoding="utf-8")
    return path


def test_measure_counts_files_calls_and_estimates_tokens(
    rubric: ReviewRulesConfig,
) -> None:
    scope = measure(parse_diff(_diff(files=3, hunks_per_file=2)), rubric)

    assert (scope.files, scope.blocks) == (3, 6)
    assert scope.calls == 6 * len(rubric.rules)
    assert scope.est_input_tokens > scope.calls * 100  # prompt + overhead


def test_token_budget_only_binds_the_api_path(rubric: ReviewRulesConfig) -> None:
    limits = load_all_configs().guardrails.limits
    scope = measure(parse_diff(_diff(files=1, hunks_per_file=40)), rubric)

    assert any("max_tokens_budget" in r for r in over_limits(scope, limits, api=True))
    assert over_limits(scope, limits, api=False) == []


def test_api_review_over_budget_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    diff = _write(tmp_path, _diff(files=1, hunks_per_file=40))

    assert cli.main([str(diff)]) == cli.EXIT_SCOPE
    err = capsys.readouterr().err
    assert "max_tokens_budget" in err
    assert "--allow-large" in err


def test_preset_can_bring_a_review_back_under_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import PASS_RESPONSE
    from lazycoder.llm import FakeLLMClient

    diff = _write(tmp_path, _diff(files=1, hunks_per_file=40))
    client = FakeLLMClient(responses=[PASS_RESPONSE] * 40)
    monkeypatch.setattr(cli, "AnthropicClient", lambda: client)

    assert cli.main([str(diff), "--preset", "security"]) == 0
    assert len(client.prompts) == 40


def test_packet_refuses_too_many_files_unless_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    limit = load_all_configs().guardrails.limits.max_files_per_run
    diff = _write(tmp_path, _diff(files=limit + 1))
    out = tmp_path / "p.json"

    assert cli.main(["packet", str(diff), "--out", str(out)]) == cli.EXIT_SCOPE
    assert f"{limit + 1} files > max_files_per_run {limit}" in capsys.readouterr().err
    assert not out.exists()

    assert cli.main(["packet", str(diff), "--out", str(out), "--allow-large"]) == 0
    assert out.exists()


def test_packet_ignores_the_api_token_budget(tmp_path: Path) -> None:
    # The user's own agent pays for agent mode; the API budget is not its limit.
    diff = _write(tmp_path, _diff(files=1, hunks_per_file=40))
    assert cli.main(["packet", str(diff), "--out", str(tmp_path / "p.json")]) == 0


def test_old_configs_with_max_steps_still_load(tmp_path: Path) -> None:
    import json
    import shutil

    from lazycoder.config.loader import DEFAULT_CONFIG_DIR

    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    shutil.copytree(DEFAULT_CONFIG_DIR.parent / "fixtures", tmp_path / "fixtures")
    path = config / "guardrails.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["limits"]["max_steps_per_review"] = 25  # as shipped up to 0.3.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    limits = load_all_configs(config).guardrails.limits
    assert limits.max_steps_per_review == 25  # accepted, never enforced
