<h1><img src="assets/logo.png" alt="" height="40" valign="middle">&nbsp;lazycoder</h1>

A code review agent with senior-level judgement. It interrogates every changed
block against a fixed rubric, runs the real checks, and returns a defensible
verdict — **APPROVE / REQUEST_CHANGES / BLOCK** — before code is trusted or merged.

Code gets written fast. The bottleneck is trusting it. lazycoder is the reviewer
that never gets tired, never skips a rule, and never self-reports green without
running the checks.

## Manual review vs lazycoder

| | Manual review | lazycoder |
|---|---|---|
| **Coverage** | Whatever the reviewer remembers to look at | Every rule (R1–R17) evaluated, every time |
| **Consistency** | Varies by reviewer, mood, time of day | Same rubric, same policy, deterministic |
| **Verdict** | "LGTM" / gut feel | APPROVE / REQUEST_CHANGES / BLOCK from a severity policy |
| **Evidence** | Comments, sometimes | Every finding cites `rule_id` + exact file:line |
| **Green claims** | "tests pass" (trust me) | Real linter/typecheck/test output in a sandbox |
| **Untrusted code** | Reviewer may run it locally | Reviewed code is data, never executed outside the sandbox |
| **Speed at scale** | Slows down as diffs grow | Loops the rubric per block, unattended |
| **Auditability** | Lives in someone's head | Append-only decision log; any verdict is replayable |

lazycoder does not replace the human — a person still confirms consequential
decisions. It removes the parts humans are bad at: remembering all 17 rules,
staying consistent across 200 files, and proving the checks actually ran.

## Status

The **deterministic domain layer is complete and closed**: a code block plus a
set of rules produces a full `ReviewReport` with an aggregated verdict, no model
required. The LLM is the last piece to plug in, so any failure isolates to the
prompt/model rather than the core logic.

```
review(block, rule)            → RuleResult          # one rule
review_all(block, rules)       → ReviewReport         # many rules
review_rubric(block, rubric)   → ReviewReport         # the whole config rubric
  └─ RuleResult[] → from_rule_results → aggregate → verdict
```

## Config-driven policy

Policy is declarative and lives in `config/`, not buried in code. Each file is
one part of the setup — reviewable, diffable, swappable:

```
lazycoder/
├── config/
│   ├── harness.json              # project context, stack, hard rules, definition of done
│   ├── guardrails.json           # what the agent may / may not do; injection defense; limits
│   ├── setup.json                # runtime, deps + rationale, env vars, bootstrap
│   ├── working_loop.json         # specify → plan → execute → verify → decide
│   ├── task_loop.json            # orchestrator + review subagents, isolation, aggregation
│   ├── review_rules.json         # R1..R17 — the interrogation rubric (the core)
│   ├── production_readiness.json # the release gate
│   ├── evals.json                # known-flawed/clean cases that test the reviewer
│   └── observability.json        # append-only decision log, tracing, redaction
├── src/argus/                    # domain, config loader, reviewers, llm client
└── tests/                        # unit + integration + eval coverage
```

## The rubric (R1..R17)

Code-level: data structure (R1), control flow (R2), inputs/outputs (R3), failure
modes (R4), side effects (R5), dependencies (R6). Security: validation, secrets,
injection (R7). Simplicity: simplest form (R8). System-level: state (R9), sync vs
async (R10), monolith vs services (R11), invariant (R12). Plus maintainability,
tests, and compatibility rules through R17.

## Design principles

- **Understanding over vibe coding** — the product is codified interrogation.
- **The agentic loop** — propose (findings) → verify (real tools) → decide (human).
- **Context engineering** — policy lives in `config/`, not in scattered constants.
- **Guardrails** — read-only by default; reviewed code is untrusted data.
- **The eval is the product** — `config/evals.json` measures the reviewer itself.

## Develop

```bash
uv sync --extra dev
pre-commit install

pytest -q
ruff check . && black --check .
mypy src
```

## Roadmap

1. Multi-file / diff orchestration on top of `review_rubric`.
2. Wire the real Anthropic client in place of the fake used in tests.
3. Run `config/evals.json` in CI as the reviewer's own regression gate.
