"""Secrets never leave the harness: guardrails.json's promise, enforced."""

from __future__ import annotations

import pytest

from conftest import block
from lazycoder.agent_mode import build_packet
from lazycoder.config import load_all_configs
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.llm import FakeLLMClient
from lazycoder.redact import MARKER, redact_secrets
from lazycoder.reviewers import SingleRuleReviewer

ANTHROPIC_KEY = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3
PEM = (
    'KEY = """-----BEGIN RSA PRIVATE KEY-----\n'
    "MIIEowIBAAKCAQEA7bq9xQ0Xv1u2Y3Z4a5b6c7d8e9f0g1h2i3j4k5l6m7n8o9p0\n"
    "q1r2s3t4u5v6w7x8y9z0A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8S9T0U1V2\n"
    '-----END RSA PRIVATE KEY-----"""'
)


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        (f'client = Anthropic(api_key="{ANTHROPIC_KEY}")', ANTHROPIC_KEY),
        ('API_KEY = "abcd1234efgh5678"', "abcd1234efgh5678"),
        ('settings = {"db_password": "s3cr3t-Pa55"}', "s3cr3t-Pa55"),
        ("GITHUB_TOKEN = 'ghp_" + "x" * 36 + "'", "ghp_" + "x" * 36),
        ('aws = "AKIAABCDEFGHIJKLMNOP"', "AKIAABCDEFGHIJKLMNOP"),
        ('CLIENT_SECRET: "q9w8e7r6t5y4"', "q9w8e7r6t5y4"),
    ],
)
def test_secret_values_are_masked(line: str, secret: str) -> None:
    masked = redact_secrets(line)

    assert secret not in masked
    assert MARKER in masked


def test_private_key_body_is_masked_and_lines_are_kept() -> None:
    masked = redact_secrets(PEM)

    assert "MIIEowIBAAKCAQEA" not in masked
    assert masked.count("\n") == PEM.count("\n")
    assert "-----BEGIN RSA PRIVATE KEY-----" in masked  # evidence stays


def test_numbering_survives_redaction() -> None:
    numbered = block(PEM + f'\nTOKEN = "{ANTHROPIC_KEY}"', start_line=40).numbered()
    masked = redact_secrets(numbered)

    assert [ln.split("\t")[0] for ln in masked.split("\n")] == [
        str(n) for n in range(40, 45)
    ]


@pytest.mark.parametrize(
    "line",
    [
        'token_type = "bearer"',  # short, not a credential
        'password = os.environ["DB_PASSWORD"]',  # read from env: fine
        'help_text = "enter your password here"',  # spaced prose
        'secret_name = ""',
        "def tokenize(text: str) -> list[str]:",
    ],
)
def test_ordinary_code_is_left_alone(line: str) -> None:
    assert redact_secrets(line) == line


def test_guardrail_patterns_are_all_covered() -> None:
    # Config and code must not drift: every name the guardrail promises to
    # redact is masked here.
    guardrails = load_all_configs().guardrails.secret_handling
    samples = {
        "API_KEY": 'API_KEY = "abcd1234efgh"',
        "SECRET": 'SECRET = "abcd1234efgh"',
        "TOKEN": 'TOKEN = "abcd1234efgh"',
        "PASSWORD": 'PASSWORD = "abcd1234efgh"',
        "PRIVATE_KEY": 'PRIVATE_KEY = "abcd1234efgh"',
        "-----BEGIN": PEM,
    }
    assert set(guardrails.redact_patterns) <= set(samples)
    for pattern in guardrails.redact_patterns:
        assert MARKER in redact_secrets(samples[pattern]), pattern


# --- both exits ---

LEAKY = f'client = Anthropic(api_key="{ANTHROPIC_KEY}")'


def test_reviewer_prompt_never_carries_the_secret(rubric: ReviewRulesConfig) -> None:
    client = FakeLLMClient(
        responses=['{"outcome": "pass", "line": null, "end_line": null}']
    )
    SingleRuleReviewer(client=client).review(block(LEAKY), rubric.rules[0])

    [prompt] = client.prompts
    assert ANTHROPIC_KEY not in prompt
    assert MARKER in prompt


def test_packet_never_carries_the_secret(rubric: ReviewRulesConfig) -> None:
    packet = build_packet([block(LEAKY)], rubric, preset="full")

    assert ANTHROPIC_KEY not in str(packet)
    assert MARKER in packet["blocks"][0]["code"]
