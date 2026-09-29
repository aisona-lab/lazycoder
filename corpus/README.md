# Stage 2 corpus

Labelled real hunks for precision / quiet-rate measurement. See
[`docs/hardening-plan.md`](../docs/hardening-plan.md) Stage 2.

| File | Role |
|------|------|
| `seed.jsonl` | Labelled seed (≥20 clean, ≥15 defective). Checked into git. |
| `candidates.jsonl` | Unlabelled harvest output — local only, not committed. |

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
