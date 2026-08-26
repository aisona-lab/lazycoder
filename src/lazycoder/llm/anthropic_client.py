from __future__ import annotations

import json
import os

import anthropic
from anthropic.types import TextBlock, ToolParam, ToolUseBlock

from lazycoder.domain.enums import RuleOutcome

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 8192

SYSTEM_PROMPT = (
    "You are a rigorous code reviewer. Evaluate exactly one rule against one"
    " code block and report your verdict via the submit_review tool."
)

# Mirrors the reviewer's _ReviewerResponse contract; pydantic re-validates
# downstream, so this schema is the first gate, not the only one.
SUBMIT_REVIEW_TOOL: ToolParam = {
    "name": "submit_review",
    "description": (
        "Submit the outcome for one rubric rule evaluated against one code"
        " block. Use insufficient_context instead of guessing when the hunk"
        " does not contain enough information to judge the rule. Cite a line"
        " number taken from the numbering shown in the block; severity is"
        " assigned by the rubric, never reported here."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": [outcome.value for outcome in RuleOutcome],
            },
            "line": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "end_line": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["outcome", "line", "end_line", "reason"],
        "additionalProperties": False,
    },
}


def _env(suffix: str, default: str) -> str:
    """Read LAZYCODER_<suffix>, falling back to the old ARGUS_<suffix> name."""
    return os.environ.get(
        f"LAZYCODER_{suffix}", os.environ.get(f"ARGUS_{suffix}", default)
    )


class AnthropicClient:
    """LLMClient backed by the live Anthropic API via forced tool use.

    Returns the submit_review tool input as a JSON string; all parsing and
    validation stays in the reviewer."""

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            msg = "ANTHROPIC_API_KEY is not set"
            raise RuntimeError(msg)
        self._model = _env("MODEL", DEFAULT_MODEL)
        raw_max_tokens = _env("MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
        try:
            self._max_tokens = int(raw_max_tokens)
        except ValueError:
            msg = f"LAZYCODER_MAX_TOKENS must be an integer, got {raw_max_tokens!r}"
            raise RuntimeError(msg) from None
        self._client = anthropic.Anthropic(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            tools=[SUBMIT_REVIEW_TOOL],
            tool_choice={"type": "tool", "name": "submit_review"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "submit_review":
                return json.dumps(block.input)
        # No tool block (e.g. truncation): fall back to raw text so the
        # reviewer's parser turns it into a per-rule error, never a crash.
        return "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )
