from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from render_comment import render  # noqa: E402


def _write(tmp_path: Path, report: dict) -> str:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return str(path)


def test_comment_lists_findings_with_their_anchored_location(tmp_path: Path) -> None:
    report = {
        "findings": [
            {
                "rule_id": "R7",
                "location": {"file": "db.py", "line": 12},
                "severity": "high",
                "reason": "string-concatenated SQL is injectable",
            }
        ],
        "rule_results": [],
        "rule_errors": [],
    }

    body = render(_write(tmp_path, report), "BLOCK", "")

    assert "⛔ BLOCK" in body
    assert "`db.py:12`" in body
    assert "1 finding(s)" in body


def test_comment_explains_a_verdict_driven_only_by_abstentions(
    tmp_path: Path,
) -> None:
    report = {
        "findings": [],
        "rule_results": [
            {
                "rule_id": "R16",
                "outcome": "insufficient_context",
                "severity": "high",
                "finding": None,
                "note": "callers are not in this diff",
            }
        ],
        "rule_errors": [],
    }

    body = render(_write(tmp_path, report), "REQUEST_CHANGES", "")

    assert "could not be judged" in body
    assert "R16" in body
    assert "callers are not in this diff" in body
    assert "1 abstention(s)" in body
