from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from argus.llm.anthropic_client import DEFAULT_MAX_TOKENS, AnthropicClient


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
