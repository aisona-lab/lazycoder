"""guardrails.json limits, measured before anything is spent.

`max_files_per_run` bounds what one review may cover, on every path.
`max_tokens_budget` bounds what the API path may send: it is estimated from
the exact prompts the reviewer would build, before a client exists, so a
refusal costs nothing and needs no key. Agent mode spends the user's own
agent, not this budget, so only the file limit applies there.

Crossing a limit is not an error to work around: the working loop asks for a
human OK when scope exceeds limits, and `--allow-large` is that OK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from lazycoder.config.models import GuardrailLimits, ReviewRulesConfig
from lazycoder.domain import CodeBlock
from lazycoder.llm.anthropic_client import SUBMIT_REVIEW_TOOL, SYSTEM_PROMPT
from lazycoder.reviewers import SingleRuleReviewer

# Rough chars-per-token for English prose and code. An estimate, labelled as one.
CHARS_PER_TOKEN = 4
# Sent with every call besides the prompt: the system prompt and tool schema.
PER_CALL_OVERHEAD_CHARS = len(SYSTEM_PROMPT) + len(json.dumps(SUBMIT_REVIEW_TOOL))


@dataclass(frozen=True)
class Scope:
    files: int
    blocks: int
    calls: int
    est_input_tokens: int


def measure(blocks: list[CodeBlock], rubric: ReviewRulesConfig) -> Scope:
    chars = sum(
        len(SingleRuleReviewer.build_prompt(block, rule)) + PER_CALL_OVERHEAD_CHARS
        for block in blocks
        for rule in rubric.rules
    )
    return Scope(
        files=len({block.file for block in blocks}),
        blocks=len(blocks),
        calls=len(blocks) * len(rubric.rules),
        est_input_tokens=chars // CHARS_PER_TOKEN,
    )


def over_limits(scope: Scope, limits: GuardrailLimits, *, api: bool) -> list[str]:
    """Why this scope needs a human OK; empty when it is within limits."""
    reasons: list[str] = []
    if scope.files > limits.max_files_per_run:
        reasons.append(
            f"{scope.files} files > max_files_per_run {limits.max_files_per_run}"
        )
    if api and scope.est_input_tokens > limits.max_tokens_budget:
        reasons.append(
            f"~{scope.est_input_tokens:,} input tokens ({scope.calls} calls)"
            f" > max_tokens_budget {limits.max_tokens_budget:,}"
        )
    return reasons
