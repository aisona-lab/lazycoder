from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lazycoder import __version__
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import ReviewReport


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rubric_hash(rubric: ReviewRulesConfig) -> str:
    """Content hash of the rubric as loaded — formatting-independent."""
    canonical = json.dumps(rubric.model_dump(mode="json"), sort_keys=True)
    return _sha256(canonical)


def build_record(
    *,
    report: ReviewReport,
    diff_text: str,
    rubric: ReviewRulesConfig,
    model: str,
    started_at: datetime,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    """One append-only record with everything the verdict was derived from.

    The verdict is a pure function of rule_results plus the rubric, and both
    are in here, so a replay can recompute it and prove it did not drift.
    """
    return {
        "run_id": str(uuid.uuid4()),
        "engine_version": __version__,
        "model": model,
        "rubric_sha256": rubric_hash(rubric),
        "diff_sha256": _sha256(diff_text),
        "started_at": started_at.isoformat(),
        "finished_at": (finished_at or datetime.now(UTC)).isoformat(),
        "verdict": report.verdict.value,
        "report": report.model_dump(mode="json"),
    }


def append(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line. Append-only: the log is never rewritten in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
