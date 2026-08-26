from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Protocol


class LLMClient(Protocol):
    """Minimal contract for components that produce raw model output."""

    def generate(self, prompt: str) -> str: ...


class FakeLLMClient:
    """Deterministic LLM test double with queued raw responses."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = deque(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            msg = "FakeLLMClient has no queued responses"
            raise ValueError(msg)
        return self._responses.popleft()
