"""Proposed corpus rows stay proposed until a human confirms them."""

from __future__ import annotations

from pathlib import Path

from lazycoder.agent_mode import block_id
from lazycoder.context import from_sidecar, load_sidecar
from lazycoder.corpus import Label, load_corpus

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
MARK = "PROPOSED by Claude"


def test_seed_holds_no_unconfirmed_rows() -> None:
    # Labels decide what the reviewer is scored against. A model-proposed
    # label must not reach the scored seed without a human removing the mark.
    assert all(MARK not in (h.note or "") for h in load_corpus(CORPUS / "seed.jsonl"))


def test_expansion_is_marked_and_well_formed() -> None:
    hunks = load_corpus(CORPUS / "expansion.jsonl")
    seed = load_corpus(CORPUS / "seed.jsonl")

    assert all(MARK in (h.note or "") for h in hunks)
    assert all(len(h.expect_rules) == 1 for h in hunks if h.label is Label.DEFECTIVE)
    assert not {h.id for h in hunks} & {h.id for h in seed}
    assert not {h.source.sha for h in hunks} & {h.source.sha for h in seed}


def test_expansion_context_matches_every_hunk() -> None:
    hunks = load_corpus(CORPUS / "expansion.jsonl")
    windows = load_sidecar(CORPUS / "expansion.context.jsonl")

    assert set(windows) == {h.id for h in hunks}
    ids = [block_id(from_sidecar(h.block(), windows[h.id], h.id)) for h in hunks]
    assert len(set(ids)) == len(ids)
