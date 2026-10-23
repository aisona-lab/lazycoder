"""Presets select rules; they never touch severities or the verdict policy."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lazycoder.config import apply_preset, load_presets
from lazycoder.config.exceptions import ConfigLoadError
from lazycoder.config.loader import load_config_file
from lazycoder.config.models import PresetsConfig, ReviewRulesConfig
from lazycoder.domain import RuleId

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_bundled_presets_load_and_default_to_full(rubric: ReviewRulesConfig) -> None:
    presets = load_presets(CONFIG_DIR)

    assert presets.default == "full"
    assert apply_preset(rubric, presets, None) == rubric
    assert {"full", "focused", "security"} <= set(presets.presets)


def test_preset_keeps_rubric_order_and_severities(rubric: ReviewRulesConfig) -> None:
    narrowed = apply_preset(rubric, load_presets(CONFIG_DIR), "focused")

    assert [r.id for r in narrowed.rules] == [
        RuleId.R1,
        RuleId.R7,
        RuleId.R14,
        RuleId.R16,
        RuleId.R17,
    ]
    by_id = {rule.id: rule for rule in rubric.rules}
    for rule in narrowed.rules:
        assert rule == by_id[rule.id]


def test_unknown_preset_fails_loudly(rubric: ReviewRulesConfig) -> None:
    with pytest.raises(ConfigLoadError, match="unknown preset 'nope'"):
        apply_preset(rubric, load_presets(CONFIG_DIR), "nope")


def test_preset_naming_a_rule_the_rubric_lacks_fails_loudly(
    rubric: ReviewRulesConfig,
) -> None:
    trimmed = rubric.model_copy(
        update={"rules": [r for r in rubric.rules if r.id is not RuleId.R7]}
    )
    with pytest.raises(ConfigLoadError, match="absent from the rubric: R7"):
        apply_preset(trimmed, load_presets(CONFIG_DIR), "security")


def test_missing_presets_file_falls_back_to_full(
    tmp_path: Path, rubric: ReviewRulesConfig
) -> None:
    presets = load_presets(tmp_path)

    assert list(presets.presets) == ["full"]
    assert apply_preset(rubric, presets, None) == rubric


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.update(default="ghost"), "default preset 'ghost'"),
        (lambda p: p["presets"]["security"].update(rules=[]), "at least one rule"),
        (
            lambda p: p["presets"]["security"].update(rules=["R7", "R7"]),
            "twice",
        ),
        (lambda p: p["presets"]["security"].update(rules=["R99"]), "rules.list"),
    ],
)
def test_invalid_presets_fail_loudly(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    payload = json.loads((CONFIG_DIR / "presets.json").read_text(encoding="utf-8"))
    mutate(payload)
    bad = tmp_path / "presets.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ConfigLoadError, match=message):
        load_config_file(bad, PresetsConfig)
