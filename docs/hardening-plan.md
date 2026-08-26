# lazycoder — hardening plan

Baseline: `e8d7c2b` (v0.2.0). Each stage ends with a claim that is true and a
number that is measured. Stages are ordered by "what makes the next stage
meaningful", not by size.

## Stage 1 — stop the README from lying  ✅ done

Measured on completion: precision **0.17**, recall **0.92**, 0/13 cases
passed (`claude-opus-5`, rubric `9441b948`, see `docs/eval-runs/`).
Two bugs only the live run exposed, both now covered by tests:
rejecting a `pass` that carried a rationale turned four rules per review
into evaluation errors (APPROVE became unreachable), and `parse_diff`
dropped blank context lines, shifting every citation after them.

Three claims in the README are false today. Each becomes true or gets deleted.

| Claim | Status at baseline | Fix |
|---|---|---|
| "every finding cites exact `file:line`" | `orchestrator.py:64` drops `block.file` / `block.start_line`; the model invents both | `file` stops being model output entirely — injected from the diff. `line` is validated against the hunk's real range |
| `evals.json` reports "precision and recall" | `evals.py:33` scores `expected <= actual`; extra findings cost nothing | Count unexpected findings; report precision, recall, abstention rate per rule |
| "append-only decision log; any verdict is replayable" | config-only (`observability.json`); nothing writes it | Emit one JSON record per run: run_id, model, rubric hash, prompt hash, per-rule outcome, verdict, timestamps |

Plus three structural fixes that Stage 2 depends on:

**1.1 Deterministic severity.** Severity is model output today
(`severity_if_unjustified` is only a prompt hint). Remove `severity` from the
model's response schema; derive it from the rubric. The verdict becomes a pure
function of the pass/fail vector and `review_rules.json`.

**1.2 Tri-state outcome.** `passed: bool` → `pass | fail | insufficient_context`.
A rule that cannot be answered from the available context must say so instead of
guessing. Abstention on a `high` rule prevents APPROVE; on anything else it is
recorded and neutral. **Abstention rate per rule is the cheap signal that tells
you which rules do not work at this context level** — it arrives before the
Stage 2 corpus and does most of the same job.

**1.3 Severity policy that is not "always BLOCK".** 7 of 17 rules are `high`
(R4, R7, R12, R13, R14, R16, R17) and one high finding is BLOCK. R14 (tests) is
structurally unanswerable from a production hunk. Target: 2–3 `high` rules.

**1.4 Untrusted-data framing.** The reviewed block is fenced, line-numbered, and
declared untrusted in the prompt. E6 already covers injection; add two cases
that fail today.

**1.5 Naming.** `lazycoder` / `argus` / `ARGUS_*` → one name, with an env-var
fallback (already published on PyPI and the Marketplace). Refresh `DEFAULT_MODEL`
(`claude-opus-4-8` → current generation).

**Exit criterion:** every README claim is true, and `--json` output plus the
decision log fully determine the verdict.

## Stage 2 — the number

Corpus of 30–50 hunks from merged OSS PRs: half with a defect the follow-up fix
confirms, half genuinely clean. Not toy snippets.

Report precision, recall, and abstention **per rule**, not globally. Publish it
in the README even when it is bad. Fix the threshold before looking at the data;
demote or delete every rule below it.

**Target: end with 8–10 rules that measurably work.** "All 17 evaluated, every
time" is a coverage claim wearing a value claim's clothes.

The Stage 1 numbers already name the candidates, before any corpus work:

- **Delete:** R12 (0 true / 11 false), R11 (92% abstention, never contributes),
  R6 and R10 (never fire at all).
- **Demote or rewrite:** R3 (0.08) and R4 (0.09) fire on almost every hunk. R4
  is `high`, so its noise blocks. Both are probably asking a question too broad
  to answer about a fragment.
- **Keep:** R7 (0.75), R1 and R17 (1.00), R14 and R16 (0.50) — note R14 and R16
  abstain 85% and 62% of the time, so they are candidates for Stage 3a context
  rather than for the bin.
- **Missing rule.** E6, E12 and E13 pin "this diff tries to manipulate the
  reviewer" onto R7, which is about the *code's* security, not the *diff's*
  honesty. On E6 R7 correctly abstained — `def f(): pass` has no vulnerability —
  and the suite counted it as a miss. Either add the rule that
  `guardrails.json` already promises (`quote_and_flag_suspicious_instructions`)
  or fix the expectation. The rubric, not the model, is wrong here.

Until this stage has a number, the Action ships `fail-on: never` (done). A tool
with an unmeasured false-positive rate cannot be a blocking gate — and at 0.17
precision the measured one cannot either.

## Stage 3a — the file is the unit (~1 day)

Feed the whole post-change file with the diff marked inside it. `file` and
`start_line` already exist and CI already has the repo on disk. This is where
almost all of the context win lives, and it drops cost as a side effect: a
40-hunk PR is ~8 files, so 680 calls become ~136.

## Stage 3b — repo context (deferred)

Caller retrieval via ripgrep, plus project conventions from `CLAUDE.md` /
`CONTRIBUTING`. **Gated on Stage 1.2 data:** build it only for the rules whose
abstention rate says they still cannot answer at file level.

## Stage 4 — economics (probably mostly free)

Re-measure after 2 and 3a. The rule cull plus the file-level unit may already
buy the order of magnitude. Only then consider rule batching by category and a
cheap-model first pass. Batching costs the per-rule isolation, which is a real
design property — spend it only against a number that says isolation was not
buying what it claimed.

## Stage 5 — auditability as the product

`replay` reconstructs the deterministic half from the decision log and asserts
the same verdict. SARIF output for GitHub code scanning. This is the wedge: no
competitor hands you a reproducible record of what was checked, on what
evidence, under which rubric version.

## Deprioritized

Sandboxed check execution (current README roadmap item). Highest engineering
cost, lowest differentiation, and it competes with tools that already do it. The
problem is not that the green verdict is unproven — it is that the red verdict
is uncalibrated.

## Open questions for a stakeholder

1. ~~Blocking gate, advisory comment, or post-merge audit?~~ Answered by Stage 2:
   advisory until the false-positive rate exists.
2. What false-positive rate is acceptable? Without it Stage 2 has no threshold.
3. What per-PR budget is acceptable? Decides whether Stage 4 is urgent.
