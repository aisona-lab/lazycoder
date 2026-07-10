from __future__ import annotations

import json
import os

import anthropic
from anthropic.types import TextBlock, ToolParam, ToolUseBlock

from argus.domain.enums import RuleId, Severity

DEFAULT_MODEL = "claude-opus-4-8"
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
        "Submit the pass/fail verdict for one rubric rule evaluated against"
        " one code block. finding must be null when passed is true and a"
        " full finding object when passed is false."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "finding": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "rule_id": {
                                "type": "string",
                                "enum": [rule.value for rule in RuleId],
                            },
                            "location": {
                                "type": "object",
                                "properties": {
                                    "file": {"type": "string"},
                                    "line": {"type": "integer"},
                                    "end_line": {
                                        "anyOf": [
                                            {"type": "integer"},
                                            {"type": "null"},
                                        ]
                                    },
                                },
                                "required": ["file", "line", "end_line"],
                                "additionalProperties": False,
                            },
                            "severity": {
                                "type": "string",
                                "enum": [severity.value for severity in Severity],
                            },
                            "reason": {"type": "string"},
                        },
                        "required": ["rule_id", "location", "severity", "reason"],
                        "additionalProperties": False,
                    },
                ]
            },
        },
        "required": ["passed", "finding"],
        "additionalProperties": False,
    },
}


class AnthropicClient:
    """LLMClient backed by the live Anthropic API via forced tool use.

    Returns the submit_review tool input as a JSON string; all parsing and
    validation stays in the reviewer."""

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
