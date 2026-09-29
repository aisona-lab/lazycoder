# Feature map

Maps lazycoder surfaces to unit tests, eval fixture packs, and decision-log
replay. Harness-only: does not change rubric taste, Action `fail-on`, or the
Stage 2 corpus.

## Deterministic core

| Feature | Unit tests | Fixtures | Notes |
|---------|------------|----------|-------|
| Config load + loud failure | `test_config_loader.py` | — | Every `config/*.json` validates |
| Domain contracts (Finding / RuleResult / ReviewReport) | `test_domain_models.py` | — | Invalid state unrepresentable |
| `derive_verdict` from rule outcomes × rubric severities | `test_verdict_aggregator.py` | — | Pure; no model |
| Diff parse → CodeBlock; file/line from hunk | `test_orchestrator.py` | — | Model cannot invent `file` |
| Single-rule reviewer + forced tool schema | `test_reviewer_subagent.py` | — | Fake client in CI |
| Orchestrator aggregates per-block results | `test_orchestrator.py` | — | |
| Append-only decision log | `test_decision_log.py` | — | `--log PATH` |
| **Replay `derive_verdict` from a log/record (no model)** | `test_decision_log.py`, `test_cli.py` | — | `lazycoder replay LOG` |

## Eval harness (`config/evals.json` → `fixtures/`)

Case bodies live under `fixtures/{pack}/cases.json`. `config/evals.json` is a
thin wrapper (`fixture_packs` + scoring metadata) so the suite cannot drift
from a second embedded copy.

| Pack | Intent | Cases |
|------|--------|-------|
| `clean/` | Expect APPROVE, no findings | E5 |
| `deny/` | Known defects the reviewer must catch | E2, E3, E4, E7, E9, E11 |
| `empty/` | Empty / missing-input failure modes | E1 |
| `malicious/` | Prompt-injection / forged reviewer output treated as data | E6, E12, E13 |
| `boundary/` | Tests / API compatibility edges | E8, E10 |

| Feature | Unit tests | Fixtures |
|---------|------------|----------|
| Gate: expected rules fire, nothing else, verdict matches | `test_evals.py` | all packs via loader |
| Precision / recall / abstention summary | `test_evals.py` | all packs |
| Fixture packs are the sole case source | `test_config_loader.py` | `fixtures/*` |

## CLI / Action

| Feature | Unit tests | Notes |
|---------|------------|-------|
| Review diff → exit code 0/1/2 | `test_cli.py` | Fake client |
| Refuse APPROVE on empty diff | `test_cli.py` | Exit 3 |
| `--log` writes one record | `test_decision_log.py` | |
| `lazycoder replay LOG` | `test_cli.py` | No Anthropic client constructed |
| GitHub Action wrapper | — | `action.yml`; advisory `fail-on: never` |

## How to run

```bash
uv sync --extra dev
pytest -q
# optional: recompute verdicts from a prior --log file (no API key)
lazycoder replay runs.jsonl
```

CI (`.github/workflows/test.yml`): `uv sync --extra dev` → `pytest -q` → ruff →
black → mypy. Replay coverage is inside pytest; no separate workflow step.
