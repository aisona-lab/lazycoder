---
name: verify
description: Build, install, and drive the lazycoder CLI end-to-end against a real diff to verify changes at the production surface.
---

# Verifying lazycoder

Surface: CLI (`lazycoder <diff-file>` / `lazycoder -` for stdin). Exit codes: 0 APPROVE, 1 REQUEST_CHANGES, 2 BLOCK, 3 operational error.

## Install as production

```bash
uv tool install . --force --reinstall   # installs to ~/.local/bin/lazycoder
```

## Drive it

Needs a real key — load from the repo `.env` (never print it):

```bash
set -a && source .env && set +a
lazycoder path/to/feature.diff
```

Cost: one API call per rubric rule (17) per diff hunk — keep test diffs to 1 hunk. A TSX diff with braces is the historically fragile input; a deliberate bug in the diff (e.g. fake debounce) confirms findings fire.

## Error-path probes (no/one API call each)

```bash
LAZYCODER_MAX_TOKENS=8k lazycoder x.diff        # -> exit 3, clean message
env -u ANTHROPIC_API_KEY lazycoder x.diff   # -> exit 3
ANTHROPIC_API_KEY=bad lazycoder x.diff      # -> exit 3 (401 propagates, NOT rule errors)
echo "" | lazycoder -                        # -> exit 3, "no reviewable hunks"
LAZYCODER_MAX_TOKENS=16 lazycoder x.diff        # truncates model output -> per-rule ERROR lines, REQUEST_CHANGES, exit 1 (never APPROVE)
```

## Gotchas

- Shell is zsh: use `pipestatus` (lowercase) or `out=$(cmd); code=$?` — `PIPESTATUS` is bash-only and silently reads the wrong exit code.
- With tiny max_tokens under tool use (v0.2.0+), ALL 17 rules truncate mid-tool-input and error (tool input overhead exceeds ~16 tokens even for passing verdicts); on the pre-tool-use text path only failing rules truncated.
