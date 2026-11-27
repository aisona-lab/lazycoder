"""Smoke tests for scripts/bench_harness.py (100% offline, deterministic)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bench_harness  # noqa: E402


def test_bench_harness_json_reports_all_stages_and_costs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = bench_harness.main(["--iterations", "5", "--warmup", "1", "--json"])
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    stages = [entry["stage"] for entry in payload["latency_ms"]]
    assert len(stages) == 8
    assert any("parse_diff" in s for s in stages)
    assert any("redact_secrets" in s for s in stages)
    assert any("packet + canaries" in s for s in stages)
    assert any("check + canaries" in s for s in stages)
    assert any("derive_verdict" in s for s in stages)
    assert any("replay_log" in s for s in stages)

    for entry in payload["latency_ms"]:
        assert 0.0 <= entry["min_ms"] <= entry["p50_ms"] <= entry["p95_ms"]

    costs = payload["cost_model_per_1k_hunks"]
    assert len(costs) == 6
    for row in costs:
        assert row["offline_agent_usd_per_1k_hunks"] == 0.0
        assert row["live_api_usd_per_1k_hunks"] > 0.0


def test_bench_harness_markdown_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = bench_harness.main(["--iterations", "3", "--warmup", "1"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Harness Stage Latency" in out
    assert "Cost Model per 1,000 Hunks" in out
    assert "$0.000" in out
