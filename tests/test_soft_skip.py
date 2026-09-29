"""Regression: auth/billing soft-skip must exit soft (no hard-fail path).

Mirrors action.yml review-step classification so CI proves empty-credits
stderr never becomes an ERROR sticky / red check under fail-on=never.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from soft_skip import is_soft_skip, main as soft_skip_main  # noqa: E402, I001

ROOT = Path(__file__).resolve().parent.parent
CREDIT_STDERR = ROOT / "fixtures" / "action" / "credit_balance_stderr.txt"
NETWORK_STDERR = ROOT / "fixtures" / "action" / "network_crash_stderr.txt"


def test_credit_balance_fixture_contains_real_anthropic_string() -> None:
    text = CREDIT_STDERR.read_text(encoding="utf-8")
    assert "Your credit balance is too low to access the Anthropic API" in text
    assert "Plans & Billing" in text


def test_credit_balance_is_soft_skip() -> None:
    text = CREDIT_STDERR.read_text(encoding="utf-8")
    assert is_soft_skip(text) is True


def test_network_crash_is_not_soft_skip() -> None:
    text = NETWORK_STDERR.read_text(encoding="utf-8")
    assert is_soft_skip(text) is False


def test_cli_soft_skip_exit_0_on_credit_balance() -> None:
    assert soft_skip_main([str(CREDIT_STDERR)]) == 0


def test_cli_hard_path_exit_1_on_network_crash() -> None:
    assert soft_skip_main([str(NETWORK_STDERR)]) == 1


def test_subprocess_matches_action_yml_invocation() -> None:
    """Same invocation action.yml uses: python3 scripts/soft_skip.py <stderr>."""
    script = ROOT / "scripts" / "soft_skip.py"
    soft = subprocess.run(
        [sys.executable, str(script), str(CREDIT_STDERR)],
        check=False,
    )
    hard = subprocess.run(
        [sys.executable, str(script), str(NETWORK_STDERR)],
        check=False,
    )
    assert soft.returncode == 0, "credit-balance must soft-skip (exit 0)"
    assert hard.returncode == 1, "network crash must stay on hard-fail path"


@pytest.mark.parametrize(
    "snippet",
    [
        "AuthenticationError: invalid x-api-key",
        "Error code: 401 - unauthorized",
        "rate_limit_error: Number of requests",
        "Error code: 529 - {'type': 'error', 'error': {'type': 'overloaded_error'",
    ],
)
def test_auth_and_capacity_snippets_soft_skip(snippet: str) -> None:
    assert is_soft_skip(snippet) is True
