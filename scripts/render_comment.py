"""Render a lazycoder --json report as a sticky PR comment (stdlib only).

Usage: render_comment.py <report.json> <verdict> <stderr.txt>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "<!-- lazycoder-report -->"
MAX_COMMENT_CHARS = 60000
BADGES = {
    "APPROVE": "✅ APPROVE",
    "REQUEST_CHANGES": "⚠️ REQUEST_CHANGES",
    "BLOCK": "⛔ BLOCK",
    "ERROR": "💥 ERROR",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render(report_path: str, verdict: str, stderr_path: str) -> str:
    lines = [MARKER, f"## lazycoder review — {BADGES.get(verdict, verdict)}", ""]

    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}

    findings = report.get("findings", [])
    if findings:
        lines += ["| Rule | Location | Severity | Reason |", "|---|---|---|---|"]
        for finding in findings:
            location = finding.get("location", {})
            where = f"{location.get('file', '?')}:{location.get('line', '?')}"
            lines.append(
                f"| {finding.get('rule_id', '?')} | `{where}`"
                f" | {finding.get('severity', '?')}"
                f" | {_cell(finding.get('reason', ''))} |"
            )
        lines.append("")
    elif verdict == "APPROVE":
        lines += ["No findings — every rubric rule passed.", ""]

    rule_errors = report.get("rule_errors", [])
    if rule_errors:
        lines.append("**Rules that could not be evaluated:**")
        lines += [
            f"- `{error.get('rule_id', '?')}`: {_cell(error.get('message', ''))}"
            for error in rule_errors
        ]
        lines.append("")

    if verdict == "ERROR":
        try:
            stderr = Path(stderr_path).read_text(encoding="utf-8").strip()
        except OSError:
            stderr = ""
        if stderr:
            lines += ["```", stderr[:4000], "```", ""]

    lines.append(
        f"<sub>{len(findings)} finding(s), {len(rule_errors)} rule error(s)"
        " — R1..R17 rubric via [lazycoder](https://github.com/aisona-lab/lazycoder)</sub>"
    )

    body = "\n".join(lines)
    if len(body) > MAX_COMMENT_CHARS:
        body = body[:MAX_COMMENT_CHARS] + "\n\n*(truncated)*"
    return body


if __name__ == "__main__":
    print(render(sys.argv[1], sys.argv[2], sys.argv[3]))
