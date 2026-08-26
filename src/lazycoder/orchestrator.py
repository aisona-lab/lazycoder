from __future__ import annotations

import re

from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import CodeBlock, ReviewReport
from lazycoder.reviewers import SingleRuleReviewer

# Matches a unified-diff hunk header, capturing the new-file start line:
#   @@ -12,3 +45,6 @@  ->  45
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_diff(diff_text: str) -> list[CodeBlock]:
    """Split a unified diff into per-hunk code blocks (added + context lines).

    ponytail: naive line scanner, no renames/binaries/mode changes. Add when a
    real diff needs them. Line numbering, though, is load-bearing: every
    citation is validated against it, so context lines are never dropped.
    """
    blocks: list[CodeBlock] = []
    current_file: str | None = None
    start_line = 1
    in_hunk = False
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
            in_hunk = False
        elif match := _HUNK.match(raw):
            flush()
            lines = []
            start_line = int(match.group(1))
            in_hunk = True
        elif raw.startswith("+") and not raw.startswith("+++"):
            lines.append(raw[1:])
        elif raw.startswith(" "):
            lines.append(raw[1:])
        elif in_hunk and not raw:
            # A blank context line whose single leading space was stripped by
            # whatever produced the diff. Dropping it would shift every line
            # number after it, so the citation would anchor to the wrong line.
            lines.append("")
        # '-' removals, '\', and file headers are ignored.

    flush()
    return blocks


def review_diff(
    reviewer: SingleRuleReviewer, diff_text: str, rubric: ReviewRulesConfig
) -> ReviewReport:
    """Review every hunk of a diff against the full rubric, one global report."""
    reports = [reviewer.review_rubric(block, rubric) for block in parse_diff(diff_text)]
    if not reports:
        return ReviewReport(findings=[], rule_results=[], rule_errors=[])
    return ReviewReport.merge(reports)
