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

The **entire deterministic pipeline is built and closed** — everything except the
LLM call itself. A real unified diff flows all the way to an aggregated verdict
with no model in the loop:

```
diff → parse_diff → CodeBlock[]
         └─ review_rubric(block, rubric)  # every rule, every block
              └─ RuleResult[] → from_rule_results → aggregate → verdict
```

Because the model is the *last* thing plugged in, any future failure isolates to
the prompt or the model — never to the plumbing, which is already proven. The
response parser is hardened against real LLM output (code fences, surrounding
prose, severity casing) using recorded fixtures, so wiring the real client is a
trivial swap rather than a rewrite.

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

## Design decisions — the *why*

The interesting part of this project is not the review logic; it's the choices
that make the review logic trustworthy.

- **Deterministic core, model last.** Everything that can be pure logic *is* pure
  logic, and the non-deterministic LLM is bolted on at the very end. This is a
  deliberate failure-isolation strategy: when a review goes wrong, the bug is in
  the prompt or the model, because the plumbing has tests proving it isn't there.

- **Contracts make invalid state unrepresentable.** The domain types are strict
  pydantic models with validators, not bags of fields. A *passed* rule cannot
  carry a finding; a *failed* one must. Every finding must cite its `rule_id` and
  an exact `file:line`. The verdict is a *computed* field over findings, never a
  value someone can set by hand. You cannot construct a lying `ReviewReport`.

- **Normalize at the boundary, keep the core strict.** Untrusted LLM text is
  cleaned up where it enters (`"HIGH"` → `"high"`), but the domain enum stays the
  single source of truth and never loosens. Leniency lives at the edge; the core
  does not bend.

- **Debt is executable, not documented.** The one known parser limitation is
  pinned by a `strict` xfail test, not a comment someone can ignore. The day the
  fix lands, that test flips to green and the suite *tells you* the debt is
  closed. Notes rot; tests don't.

- **TDD throughout.** Every behavior went RED before GREEN — including the
  garbage-input fixtures that hardened the parser.

- **The eval is the product.** `config/evals.json` is a set of known-flawed and
  known-clean cases whose job is to measure *the reviewer itself*. Wired as a CI
  gate, it closes the loop: a code reviewer that has its own reviewer, and knows
  whether it's still good every time it changes.

## Develop

```bash
uv sync --extra dev
pre-commit install

pytest -q
ruff check . && black --check .
mypy src
```

## Roadmap

1. ~~Multi-file / diff orchestration on top of `review_rubric`.~~ ✓
2. ~~Harden the response parser against real LLM output (fixtures).~~ ✓
3. **Wire `config/evals.json` as a CI regression gate — while still on the fake
   client.** Order matters. On the fake, the evals prove *the logic*: parser,
   aggregator, verdict policy. This is the last deterministic gate.
4. **Then** wire the real Anthropic client (trivial swap — the parser already
   absorbs its output). Now those same evals stop measuring the plumbing and
   start measuring the truth that matters: does the real model, with this prompt,
   actually catch the SQL injection in eval E3 — or miss it? That is where the
   project stops being *tested plumbing* and becomes *a reviewer that works, or
   doesn't* — and thanks to the isolation above, a failing eval points straight
   at the prompt or the model, never at the code underneath.
