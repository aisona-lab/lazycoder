"""T1: config loading — every JSON validates; malformed config fails loudly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.config.exceptions import ConfigLoadError
from argus.config.loader import CONFIG_FILES, load_all_configs, load_config_file
from argus.config.models import HarnessConfig, ReviewRulesConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


@pytest.mark.parametrize("filename", list(CONFIG_FILES.keys()))
def test_each_config_file_loads_and_validates(filename: str) -> None:
    model = CONFIG_FILES[filename]
    config = load_config_file(CONFIG_DIR / filename, model)
    assert config is not None


def test_load_all_configs_returns_app_config() -> None:
    app = load_all_configs(CONFIG_DIR)
    assert app.harness.project.codename == "Argus"
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
    from argus.config.models import GuardrailsConfig

    with pytest.raises(ConfigLoadError, match="typo_field|extra"):
        load_config_file(bad, GuardrailsConfig)
