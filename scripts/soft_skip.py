"""Classify Anthropic stderr as soft-skip (auth/billing) vs hard fail.

Used by action.yml in the review step — before the sticky comment — when
fail-on=never, so an empty-credits / auth error becomes verdict=SKIPPED and
never posts an ERROR comment.

Exit codes (CLI): 0 = soft-skip, 1 = not a soft-skip / unreadable input.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Match Anthropic auth / empty-credits / billing. Also rate_limit / overloaded:
# under fail-on=never those are transient capacity, not a review finding.
SOFT_SKIP_RE = re.compile(
    r"credit balance|billing|authentication|unauthorized|"
    r"invalid.?api.?key|api.?key.*(invalid|missing)|"
    r"\b401\b|\b403\b|"
    r"rate.?limit|overloaded|\b529\b",
    re.IGNORECASE,
)


def is_soft_skip(stderr: str) -> bool:
    """True when stderr looks like Anthropic auth/billing (or rate-limit)."""
    return bool(SOFT_SKIP_RE.search(stderr))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 1
    try:
        text = Path(args[0]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 1
    return 0 if is_soft_skip(text) else 1


if __name__ == "__main__":
    raise SystemExit(main())
