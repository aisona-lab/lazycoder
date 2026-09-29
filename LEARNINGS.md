# lazycoder — delivery learnings

Short, hard-won rules from the aisona-lab harness loop. Do not invent numbers
to make a stage look done.

## Delivery loop (non-negotiable)

**SPEC → PLAN → OK → smallest unit → prove with a command → merge → clean tree.**

1. Write the spec / claim that must become true.
2. Plan the smallest change that makes that claim true.
3. Get human OK when scope is unclear or consequential.
4. Ship one concern per PR — no half-open branches left behind.
5. Prove offline with a real command (see below); paste exit 0, not vibes.
6. Merge only when CI is green and the working tree is clean.

## Architecture thesis

| Role | Repo | Keys |
|------|------|------|
| **Auth engine** | [agent-action-gate](https://github.com/aisona-lab/agent-action-gate) | **Zero** LLM keys. Deterministic allow / deny / approval. |
| **Trailer** | this repo (lazycoder) | Optional **one** Anthropic key for live review / Action. |
| Deterministic half | verdict, replay, corpus `prove`, pytest | **No** key. |

LLM is never the authorization engine. Never claim the stack needs two keys.
Never put real keys in git.

## Offline proof (definition of done without credits)

```bash
env -u ANTHROPIC_API_KEY uv run pytest -q
env -u ANTHROPIC_API_KEY uv run python scripts/corpus_cli.py prove corpus/seed.jsonl
```

Live corpus scoring / Action dogfood with a real model stays **BLOCKED** until
Anthropic credits exist. Do not invent precision; do not flip `fail-on` without
Stage 2 live numbers (`docs/hardening-plan.md`).

## After every "fix"

Run an adversarial audit: missing key, billing soft-skip, injection-in-args as
data, sticky ERROR vs SKIPPED. Close gaps with **regression fixtures / tests**,
not prose. Soft-skip auth/billing **before** posting an ERROR sticky when
advisory (`fail-on: never`).

## Honesty

- No fake precision. Publish measured numbers even when bad.
- Offline proves without keys. Live paths soft-skip cleanly when the key is
  absent or billing fails.
- Prefer harness (docs, fixtures, FEATURE_MAP, CI) over semantic refactors
  unless the task explicitly asks for a semantic change.
