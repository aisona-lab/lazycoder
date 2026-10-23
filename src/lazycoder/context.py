"""File-level context (Stage 3a): show the hunk inside the file around it.

The corpus runs showed most defects are invisible from a hunk alone (R13
abstained on 41% of hunks, R14 on 78%). This attaches the surrounding
post-change lines to each block. It never changes what may be cited: the
hunk's own lines, validated exactly as before.

A context that does not contain the hunk verbatim at its stated lines is a
mismatch, refused loudly: reviewing a hunk against the wrong version of its
file would measure nothing.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lazycoder.domain import CodeBlock

# Lines of context on each side of the hunk. Fixed before Stage 3a was
# measured (docs/hardening-plan.md); a whole file is not the unit because
# some corpus files run to ~3,800 lines.
CONTEXT_RADIUS = 120


class ContextMismatchError(ValueError):
    """The file given as context does not contain the hunk where it claims."""


def with_context(block: CodeBlock, file_text: str) -> CodeBlock:
    """The block with a window of `file_text` around it attached."""
    lines = file_text.split("\n")
    hunk = block.code.split("\n")
    first = block.start_line - 1
    if lines[first : first + len(hunk)] != hunk:
        msg = (
            f"{block.file}:{block.start_line}-{block.end_line}: the file given as"
            " context does not contain this hunk at these lines (is it the"
            " post-change version?)"
        )
        raise ContextMismatchError(msg)
    lo = max(0, first - CONTEXT_RADIUS)
    hi = min(len(lines), first + len(hunk) + CONTEXT_RADIUS)
    return replace(block, context="\n".join(lines[lo:hi]), context_start=lo + 1)


def from_repo(blocks: list[CodeBlock], root: Path) -> list[CodeBlock]:
    """Attach context read from a checkout of the post-change tree."""
    out: list[CodeBlock] = []
    for block in blocks:
        path = root / block.file
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"{block.file}: cannot read context from {path} ({exc})"
            raise ContextMismatchError(msg) from exc
        out.append(with_context(block, text))
    return out


def load_sidecar(path: Path) -> dict[str, tuple[int, str]]:
    """Corpus context sidecar: one {"id", "context_start", "context"} per line."""
    windows: dict[str, tuple[int, str]] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            hunk_id, start, text = row["id"], int(row["context_start"]), row["context"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            msg = f"{path}:{number}: not a context row ({exc})"
            raise ContextMismatchError(msg) from exc
        if hunk_id in windows:
            msg = f"{path}:{number}: duplicate id {hunk_id!r}"
            raise ContextMismatchError(msg)
        windows[hunk_id] = (start, str(text))
    return windows


def from_sidecar(block: CodeBlock, window: tuple[int, str], hunk_id: str) -> CodeBlock:
    """Attach a stored window, checking it still holds the hunk verbatim."""
    start, text = window
    lines = text.split("\n")
    hunk = block.code.split("\n")
    offset = block.start_line - start
    if offset < 0 or lines[offset : offset + len(hunk)] != hunk:
        msg = f"{hunk_id}: stored context does not contain the hunk at its lines"
        raise ContextMismatchError(msg)
    return replace(block, context=text, context_start=start)
