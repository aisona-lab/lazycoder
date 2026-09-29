"""T1: config loading — every JSON validates; malformed config fails loudly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazycoder.config.exceptions import ConfigLoadError
from lazycoder.config.loader import CONFIG_FILES, load_all_configs, load_config_file
from lazycoder.config.models import HarnessConfig, ReviewRulesConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


@pytest.mark.parametrize("filename", list(CONFIG_FILES.keys()))
def test_each_config_file_loads_and_validates(filename: str) -> None:
    model = CONFIG_FILES[filename]
    config = load_config_file(CONFIG_DIR / filename, model)
    assert config is not None


def test_load_all_configs_returns_app_config() -> None:
    app = load_all_configs(CONFIG_DIR)
    assert app.harness.project.codename == "lazycoder"
    assert len(app.review_rules.rules) >= 12
    assert len(app.evals.cases) >= 5


def test_malformed_json_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "harness.json"
    bad.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match=r"invalid JSON"):
        load_config_file(bad, HarnessConfig)


def test_schema_validation_failure_is_loud(tmp_path: Path) -> None:
    bad = tmp_path / "review_rules.json"
    payload = json.loads((CONFIG_DIR / "review_rules.json").read_text(encoding="utf-8"))
    payload["rules"][0]["id"] = "R999"  # not a valid RuleId
    bad.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc_info:
        load_config_file(bad, ReviewRulesConfig)

    message = str(exc_info.value)
    assert "review_rules.json" in message or "R999" in message
    assert "rules" in message.lower() or "validation failed" in message.lower()


def test_missing_config_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match="missing"):
        load_all_configs(tmp_path)


def test_unknown_extra_field_fails_loudly(tmp_path: Path) -> None:
    bad = tmp_path / "guardrails.json"
    payload = json.loads((CONFIG_DIR / "guardrails.json").read_text(encoding="utf-8"))
    payload["typo_field"] = "oops"
    bad.write_text(json.dumps(payload), encoding="utf-8")

    # load_all needs all files; test single-file validation instead
    from lazycoder.config.models import GuardrailsConfig

    with pytest.raises(ConfigLoadError, match="typo_field|extra"):
        load_config_file(bad, GuardrailsConfig)


def test_evals_load_cases_from_fixture_packs() -> None:
    app = load_all_configs(CONFIG_DIR)
    ids = {case.id for case in app.evals.cases}
    assert ids == {
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
        "E6",
        "E7",
        "E8",
        "E9",
        "E10",
        "E11",
        "E12",
        "E13",
    }
    assert set(app.evals.fixture_packs) == {
        "clean",
        "deny",
        "empty",
        "malicious",
        "boundary",
    }
    # Thin wrapper: case bodies must not be duplicated in evals.json.
    raw = json.loads((CONFIG_DIR / "evals.json").read_text(encoding="utf-8"))
    assert "cases" not in raw
    assert "fixture_packs" in raw


def test_embedded_cases_in_evals_json_are_rejected(tmp_path: Path) -> None:
    """Dual-source drift guard: cases belong in fixtures/, not evals.json."""
    import shutil

    from lazycoder.config.loader import load_evals

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in CONFIG_FILES:
        shutil.copy(CONFIG_DIR / name, config_dir / name)
    shutil.copytree(REPO_ROOT / "fixtures", tmp_path / "fixtures")

    payload = json.loads((config_dir / "evals.json").read_text(encoding="utf-8"))
    payload["cases"] = [
        {
            "id": "E99",
            "name": "embedded",
            "input_code": "x = 1",
            "expect_findings": [],
            "expect_verdict": "APPROVE",
        }
    ]
    (config_dir / "evals.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="dual-source|must not be embedded"):
        load_evals(config_dir)
