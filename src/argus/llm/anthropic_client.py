from __future__ import annotations

import os

import anthropic
from anthropic.types import TextBlock

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 8192


class AnthropicClient:
    """LLMClient backed by the live Anthropic API. Returns raw text only;
    all parsing/validation stays in the reviewer."""

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            msg = "ANTHROPIC_API_KEY is not set"
            raise RuntimeError(msg)
        self._model = os.environ.get("ARGUS_MODEL", DEFAULT_MODEL)
        raw_max_tokens = os.environ.get("ARGUS_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
        try:
            self._max_tokens = int(raw_max_tokens)
        except ValueError:
            msg = f"ARGUS_MAX_TOKENS must be an integer, got {raw_max_tokens!r}"
            raise RuntimeError(msg) from None
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )
