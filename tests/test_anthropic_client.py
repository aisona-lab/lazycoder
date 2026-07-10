from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from argus.config import load_all_configs
from argus.domain import RuleId, Severity
from argus.llm.anthropic_client import (
    DEFAULT_MAX_TOKENS,
    SUBMIT_REVIEW_TOOL,
    AnthropicClient,
)
from argus.reviewers import SingleRuleReviewer


def _tool_block(payload: dict) -> ToolUseBlock:
    return ToolUseBlock(
        type="tool_use", id="toolu_01", name="submit_review", input=payload
    )


def _client_with_response(
    monkeypatch, content: list
) -> tuple[AnthropicClient, MagicMock]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("argus.llm.anthropic_client.anthropic.Anthropic") as mock_cls:
        create = MagicMock(return_value=MagicMock(content=content))
        mock_cls.return_value.messages.create = create
        client = AnthropicClient()
    return client, create


def test_anthropic_client_uses_configurable_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ARGUS_MAX_TOKENS", "16384")

    with patch("argus.llm.anthropic_client.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create = MagicMock(
            return_value=MagicMock(content=[])
        )
        client = AnthropicClient()
        client.generate("prompt")

    mock_cls.return_value.messages.create.assert_called_once()
    assert mock_cls.return_value.messages.create.call_args.kwargs["max_tokens"] == 16384


def test_anthropic_client_default_max_tokens_is_not_2048(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ARGUS_MAX_TOKENS", raising=False)

    with patch("argus.llm.anthropic_client.anthropic.Anthropic"):
        client = AnthropicClient()

    assert client._max_tokens == DEFAULT_MAX_TOKENS
    assert client._max_tokens > 2048


def test_anthropic_client_rejects_non_integer_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ARGUS_MAX_TOKENS", "8k")

    with patch("argus.llm.anthropic_client.anthropic.Anthropic"):
        with pytest.raises(RuntimeError, match="ARGUS_MAX_TOKENS must be an integer"):
            AnthropicClient()


def test_generate_forces_submit_review_tool(monkeypatch) -> None:
    client, create = _client_with_response(
        monkeypatch, [_tool_block({"passed": True, "finding": None})]
    )

    client.generate("prompt")

    kwargs = create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_review"}
    assert kwargs["tools"] == [SUBMIT_REVIEW_TOOL]
    assert kwargs["tools"][0]["strict"] is True
    assert "rigorous code reviewer" in kwargs["system"]


def test_generate_returns_tool_input_as_json(monkeypatch) -> None:
    payload = {"passed": True, "finding": None}
    client, _ = _client_with_response(monkeypatch, [_tool_block(payload)])

    assert json.loads(client.generate("prompt")) == payload


def test_generate_falls_back_to_text_without_tool_block(monkeypatch) -> None:
    client, _ = _client_with_response(
        monkeypatch, [TextBlock(type="text", text="truncated garbage")]
    )

    assert client.generate("prompt") == "truncated garbage"


def test_tool_input_round_trips_through_the_reviewer(monkeypatch) -> None:
    config = load_all_configs()
    rule = next(rule for rule in config.review_rules.rules if rule.id == RuleId.R7)
    payload = {
        "passed": False,
        "finding": {
            "rule_id": "R7",
            "location": {"file": "query.py", "line": 4, "end_line": None},
            "severity": "high",
            "reason": "user input concatenated into SQL",
        },
    }
    client, _ = _client_with_response(monkeypatch, [_tool_block(payload)])
    reviewer = SingleRuleReviewer(client=client)

    result = reviewer.review(code_block="q = 'select ' + user_input", rule=rule)

    assert result.passed is False
    assert result.finding is not None
    assert result.finding.rule_id == RuleId.R7
    assert result.finding.location.file == "query.py"
    assert result.finding.location.line == 4
    assert result.finding.severity == Severity.HIGH
