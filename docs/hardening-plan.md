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

**Phase 3 (offline) landed:** `corpus/seed.jsonl` meets the shape floor
(≥20 clean / ≥15 defective); `decide_cull` / `fail_on_gate` encode the
pre-registered thresholds; `scripts/corpus_cli.py prove` is the offline
proof. Live `run` + rule cull from real scores remain gated on Anthropic
credits — do not invent precision numbers and do not flip `fail-on`.

**Keyless path (agent mode):** `lazycoder packet --corpus` / `check --corpus`
scores the corpus with the user's own coding agent as the reviewer, through
the same `report` / `cull_plan` / `fail_on_gate`. The number it produces is
labelled with that agent and measures it, not the API path; the answering
agent must not be able to read `seed.jsonl`. Note before reading results:
8 of the 15 labelled defects are R4 and the `focused` preset does not ask R4,
so `focused` cannot catch most of this corpus by construction.

**First live run (agent mode, 2026-10-23,
[`docs/eval-runs/2026-10-23-agent-mode-corpus.txt`](eval-runs/2026-10-23-agent-mode-corpus.txt)):**
quiet rate 100%, recall **0%** (0/15 by rule), gate **not ready** — the
recall floor did its job. The reviewer went from Stage 1's noise (precision
0.17, API, toy cases) to total silence on real hunks. One real-looking defect
(requests-7308 header regex) was found under R7/R12/R13 while labelled R4, so
rule-identity scoring hides it. The run is confounded by a conservative
subagent prompt and soft isolation; no cull decision is taken from it.

**Run 2 (same shards, conservative sentence removed,
[`docs/eval-runs/2026-10-23-agent-mode-corpus-run2.txt`](eval-runs/2026-10-23-agent-mode-corpus-run2.txt)):**
quiet rate 86%, 0.14 noise per clean hunk, recall still **0%** by rule, gate
not ready. Read by hand, the reviewer described 2 of the 8 labelled defects
(httpx-3442, requests-7308) but filed both under rules other than the label.
Two readings, both open: rule-identity scoring undercounts a reviewer whose
rules overlap, and hunk-only context leaves most defects invisible (R13
abstains 41%, R14 78%), which is the Stage 3a case. Any defect-level metric
must be pre-registered before the next run, not fitted to this one.


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

### Pre-registered decision rules

Fixed on 2026-08-26, **before any corpus data exists**. Chosen after the toy
suite (precision 0.17) but before a single real hunk has been scored. Written
down here so the cull is a measurement and not a rationalisation — if these
turn out to be the wrong thresholds, they get changed in a commit that says so,
not quietly while reading the results.

Corpus shape: **≥20 clean** hunks and **≥15 defective**, from non-bot merged
PRs of mature repositories. Clean means the hunk is still untouched by any
later fix; defective means a follow-up commit fixed a specific defect in it.

Per rule, after scoring:

| Condition | Action |
|---|---|
| `clean_noise_rate > 25%` **and** `caught == 0` | **Delete.** It interrupts constantly and has never been right. |
| `clean_noise_rate > 10%` and severity is `high` | **Demote to medium.** Its noise must not block. |
| `abstention_rate > 50%` **and** `clean_noise_rate < 10%` | **Keep, route to Stage 3a.** Silent is not the same failure as noisy — this rule is being asked at the wrong level of context, not asked the wrong question. |
| otherwise | **Keep.** |

Gate for flipping the Action's `fail-on` back to `request-changes`:
**`quiet_rate ≥ 80%`** and no `high`-severity rule above **5%** clean noise. In
words: at least four in five clean hunks draw no comment at all, and nothing
that can block fires on clean code more than one time in twenty.

Two things this deliberately does *not* do. It does not set a recall floor
for the cull — recall is already 0.92 and is not the failing number, so a
threshold there would only give the cull an excuse to keep noisy rules. And it does not score
`unlabelled` findings on defective hunks in either direction; they get read by
a human and either become labels or become nothing.

**Amendment, 2026-10-23 — before any live corpus score.** The fail-on gate
gains **`recall ≥ 50%`** on the labelled defects. Reason: a dry run of agent
mode with a reviewer that answers `pass` to everything scored quiet_rate 100%,
recall 0%, and the gate read *ready*. The "no recall floor" call above assumed
the API reviewer (recall 0.92); agent mode makes a silent reviewer cheap to
run, and silence must not be able to flip `fail-on`. The cull table is
unchanged: the floor applies to the gate only.

**Amendment 2, 2026-10-23 — after runs 1–2, before Stage 3a.** The recall the
gate reads becomes **hunk recall**: the share of in-scope defective hunks that
draw at least one finding, under any rule. Reason: in run 2 the reviewer
described two labelled defects correctly under rules other than the label
(R4 / R7 / R12 / R13 overlap), so rule recall measures which name it picked
as much as whether it saw. This is decided after looking at runs 1–2, and it
changes neither outcome (hunk recall 1/15 and 3/15, both under 50%). It is
fixed now so Stage 3a is scored against it, not fitted to it. Known
weakness: a finding about a different problem in the same hunk still counts
(1 of 3 in run 2); `unlabelled` is printed so a human can check. Rule recall
stays in the output, ungated.

## Stage 3a — the file is the unit (~1 day)

Feed the whole post-change file with the diff marked inside it. `file` and
`start_line` already exist and CI already has the repo on disk. This is where
almost all of the context win lives, and it drops cost as a side effect: a
40-hunk PR is ~8 files, so 680 calls become ~136.

**Built (2026-10-23):** `--context` on review / packet / check. Each hunk is
shown inside a window of its post-change file, **120 lines each side**
(`CONTEXT_RADIUS`; the unit is not the whole file because some corpus files
run to ~3,800 lines), hunk lines marked `*`, and only those citable. The
corpus windows are in `corpus/seed.context.jsonl` (built from the merge
commit for clean hunks and its first parent for defective ones, each checked
to hold its hunk verbatim). Not done: the per-file batching that would cut
the call count; each hunk is still asked separately.

### Pre-registered: corpus run 3 (context), fixed before it runs

Protocol identical to run 2 except the context: same 37 hunks, `full`
preset, 8 shards of 5 hunks, one fresh Claude Code subagent per shard, the
run-2 prompt (no "only fail when the code shows it" sentence), soft
isolation by instruction. Scored with the current gate: quiet rate ≥ 80%,
hunk recall ≥ 50%, no high rule > 5% clean noise.

Decision rule for whether context earns its cost:
- **Adopt** (make `--context .` the skill's default) if hunk recall reaches
  **≥ 6/15** (double run 2's 3/15) **and** quiet rate stays **≥ 80%**.
- **Inconclusive** if hunk recall is 4–5/15: 15 hunks cannot separate that
  from noise; grow the corpus before deciding.
- **Reject** (keep context opt-in, look elsewhere) if hunk recall ≤ 3/15 or
  quiet rate falls below 80%.

Abstention on R13 / R14 is reported against run 2 (41% / 78%) as a
secondary read, not a criterion.

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
