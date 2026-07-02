from __future__ import annotations

import re
from dataclasses import dataclass

from argus.config.models import ReviewRulesConfig
from argus.domain import ReviewReport
from argus.reviewers import SingleRuleReviewer

# Matches a unified-diff hunk header, capturing the new-file start line:
#   @@ -12,3 +45,6 @@  ->  45
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class CodeBlock:
    """One reviewable chunk of a diff: a single hunk's post-change content."""

    file: str
    start_line: int
    code: str


def parse_diff(diff_text: str) -> list[CodeBlock]:
    """Split a unified diff into per-hunk code blocks (added + context lines).

    ponytail: naive line scanner, no renames/binaries/mode changes. Add when a
    real diff needs them.
    """
    blocks: list[CodeBlock] = []
    current_file: str | None = None
    start_line = 1
    lines: list[str] = []

    def flush() -> None:
        if current_file and current_file != "/dev/null" and lines:
            blocks.append(CodeBlock(current_file, start_line, "\n".join(lines)))

    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            flush()
            lines = []
            path = raw[4:].strip()
            current_file = path[2:] if path.startswith("b/") else path
        elif match := _HUNK.match(raw):
            flush()
            lines = []
            start_line = int(match.group(1))
        elif raw.startswith("+") and not raw.startswith("+++"):
            lines.append(raw[1:])
        elif raw.startswith(" "):
            lines.append(raw[1:])
        # '-' removals, '\', and file headers are ignored.

    flush()
    return blocks


def review_diff(
    reviewer: SingleRuleReviewer, diff_text: str, rubric: ReviewRulesConfig
) -> ReviewReport:
    """Review every hunk of a diff against the full rubric, one global report."""
    results = [
        result
        for block in parse_diff(diff_text)
        for result in reviewer.review_rubric(block.code, rubric).rule_results
    ]
    return ReviewReport.from_rule_results(results)
