# Changelog

All notable changes to `lazycoder` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-11-27

### Added
- **Agent mode (`packet` / `check` / `init`)**: Run reviews keyless using your own coding agent as the model while keeping deterministic contract validation, citation anchoring, severity assignment, and verdict derivation in the harness (`src/lazycoder/agent_mode.py`, `src/lazycoder/scaffold.py`).
- **Rule presets (`config/presets.json`)**: Added `--preset` (`full`, `focused`, `security`) across `lazycoder`, `packet`, `check`, and `init` to trade rule breadth for cost without altering rubric severities.
- **Seeded canary planting**: `packet` and `check` deterministically mix known-defect blocks from `fixtures/deny/` using a diff-derived seed; missed canaries record a `RuleEvaluationError` and block `APPROVE`.
- **Pre-LLM line-preserving secret redaction (`src/lazycoder/redact.py`)**: Masks known credential formats, private-key bodies, and secret assignments with `<redacted:secret>` at both prompt and packet boundaries without shifting line numbers.
- **Stage 3a file-level context (`--context`)**: Displays each hunk inside a ±120-line post-change window (`*`-marked hunk lines remain the only citable range) for repo checkouts and `corpus/seed.context.jsonl`.
- **Stage 2 OSS corpus & offline proof (`corpus/seed.jsonl`, `scripts/corpus_cli.py`)**: 37 labelled hunks (22 clean / 15 defective) across `requests`, `httpx`, `urllib3`, and `click`, executable cull rules (`decide_cull`, `fail_on_gate`), and `corpus_cli.py prove`.
- **Deterministic verdict replay (`lazycoder replay`)**: Recomputes `derive_verdict` from append-only JSONL `--log` records without calling any LLM (`src/lazycoder/decision_log.py`).
- **Scope guardrails enforcement (`src/lazycoder/limits.py`)**: Refuses diffs exceeding `max_files_per_run` or API `max_tokens_budget` with exit code `4` before constructing any LLM client (bypassable with `--allow-large`).
- **Action auth/billing soft-skip (`scripts/soft_skip.py`)**: Classifies empty-credits, auth, rate-limit, and overloaded errors as `SKIPPED` under `fail-on: never` before posting any sticky PR comment.
- **1-step Docker distribution & reproducible harness benchmark**: Added multi-stage non-root `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `ARCHITECTURE.md`, and `scripts/bench_harness.py`.

### Changed
- Anchored citations to diff hunk paths and post-change line ranges (`parse_diff` preserves blank context lines), removed model-supplied `severity`, and added tri-state `RuleOutcome` (`pass`, `fail`, `insufficient_context`).
- Renamed environment overrides to `LAZYCODER_MODEL` / `LAZYCODER_MAX_TOKENS` (retaining `ARGUS_*` fallback) and set `DEFAULT_MODEL = "claude-opus-5"`.

### Removed
- Removed unused legacy test manifest `tests/tests.json`.

## [0.2.0] - 2026-07-10

### Added
- Composite GitHub Action (`action.yml`) with sticky PR comments (`scripts/render_comment.py`) and advisory `fail-on: never` default.
- Forced `submit_review` tool-use schema (`strict: true`) in `AnthropicClient`.
- CI test workflow (`.github/workflows/test.yml`) running `pytest`, `ruff`, `black`, and `mypy`.

## [0.1.1] - 2026-07-10

### Fixed
- Balanced-brace JSON extraction, configurable `LAZYCODER_MAX_TOKENS`, and per-rule parse error isolation for large TypeScript/TSX reviews.

## [0.1.0] - 2026-07-04

### Added
- Initial release with R1..R17 rubric, `SingleRuleReviewer`, `ReviewReport` domain contracts, `derive_verdict`, PyPI console entry point, and OIDC publish workflow.
