# Stage 2 corpus

Labelled real hunks for precision / quiet-rate measurement. See
[`docs/hardening-plan.md`](../docs/hardening-plan.md) Stage 2.

| File | Role |
|------|------|
| `seed.jsonl` | Labelled seed (≥20 clean, ≥15 defective). Checked into git. |
| `candidates.jsonl` | Unlabelled harvest output — local only, not committed. |
| `expansion.jsonl` | **Proposed, not confirmed.** 20 defective + 17 clean hunks from requests, httpx, urllib3, click, flask and starlette, selected by fixed rules and labelled by Claude (see below). Not part of any scored run until a human confirms each row. |
| `expansion.context.jsonl` | Context windows for `expansion.jsonl`, built the same way as `seed.context.jsonl`. |
| `seed.context.jsonl` | Stage 3a: each hunk's file window (±120 lines), from the merge commit (clean) or its parent (defective). Rebuild: `corpus_cli.py context corpus/seed.jsonl`. Its `rev` field reveals the label, so like `seed.jsonl` it must never reach the answering agent; the packet carries only file, line and code. |

## Labels

- **clean** — post-change side of a merged non-bugfix PR. Seed notes mark
  provisional labels that have not been longitudinally checked for later fixes.
- **defective** — pre-image of a known bug-fix PR, with `expect_rules` naming
  the defect the follow-up fixed. Extra findings on defective hunks are
  *unlabelled*, not false positives.

`load_corpus` refuses any line with `"label": null`.

## Offline proof (no API key)

```bash
uv run python scripts/corpus_cli.py prove corpus/seed.jsonl
# artifact: docs/eval-runs/corpus-prove.txt  — expect exit 0
```

## Live scoring (needs Anthropic credits)

```bash
ANTHROPIC_API_KEY=... uv run python scripts/corpus_cli.py run corpus/seed.jsonl
```

Do **not** flip Action `fail-on` away from `never` until the printed fail-on
gate is ready (`quiet_rate ≥ 80%` and no high rule above 5% clean noise).

## Expanding the corpus (2026-10-23)

`expansion.jsonl` was harvested from git history alone (anonymous shallow
clones; no GitHub API), with selection rules fixed before any row was read:

- **defective:** a first-parent, non-merge commit whose subject says fix /
  bug / regression and not typo, docs, lint, typing, test, revert; touching
  at most 2 non-test `.py` files with at most 40 lines of churn. The hunk is
  the pre-fix side, and it must contain a line the fix changed (a fix that
  only adds code leaves nothing visible to review, so it is dropped).
- **clean:** a non-fix commit with a feature/refactor subject, touching no
  file that any fix candidate touched; the hunk is the post-change side.
- Then by hand: dropped docs-only, shell-script and revert-pair commits, and
  one "feature" that is a fix in disguise.

Each row's `note` says why it is labelled as it is, and carries
`PROPOSED by Claude`. **The reviewer being measured is also a Claude model**,
so these labels are circular until a human checks them. To confirm a row:
open its `source.url`, check the label and `expect_rules`, edit or delete
the row, remove the `PROPOSED by Claude …` sentence from its note, and move
it (and its context row) into `seed.jsonl` / `seed.context.jsonl`. A test
refuses any seed row that still carries the mark.

