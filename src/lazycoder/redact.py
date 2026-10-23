"""Mask secret-looking literals before code leaves the harness for a model.

guardrails.json promises `never_send_secrets_to_llm`; this is where that holds.
It runs at the two exits — the reviewer prompt (API path) and the packet
(agent mode) — and never on the copy used for line numbering or citation
checks, so every line keeps its number and nothing downstream shifts.

The marker stays in place of the value, so a reviewer can still say "a
credential is hardcoded here" (an R7 finding) without ever seeing it.
"""

from __future__ import annotations

import re

MARKER = "<redacted:secret>"

# Values that are credentials whatever they are called.
_TOKEN_FORMATS = re.compile(
    r"sk-[A-Za-z0-9_\-]{20,}"  # Anthropic sk-ant-…, OpenAI sk-…/sk-proj-…
    r"|gh[pousr]_[A-Za-z0-9]{36,}"  # GitHub tokens
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"  # Slack
    r"|AIza[0-9A-Za-z_\-]{35}"  # Google API key
)

# A string literal assigned to a name that says it holds a secret. Mirrors
# guardrails.json secret_handling.redact_patterns (a test keeps them in step).
# Short or spaced values are left alone: `token_type = "bearer"` is not a
# credential, and masking it would invite a false R7 finding.
_NAMED_SECRET = re.compile(
    r"(?i)(\b[\w.\-]*(?:api_?key|secret|token|passw(?:or)?d|private_?key)"
    r"[\w.\-]*\b[\"']?\s*[:=]\s*)([\"'])([^\s\"']{8,})\2"
)

_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def redact_secrets(text: str) -> str:
    """The same text, line for line, with secret-looking values masked."""
    out: list[str] = []
    in_pem = False
    for line in text.split("\n"):
        if in_pem:
            if _PEM_END.search(line):
                in_pem = False
            else:
                # Keep any "NNN\t" numbering prefix; mask the key material.
                prefix, tab, _ = line.partition("\t")
                line = f"{prefix}{tab}{MARKER}" if tab else MARKER
                out.append(line)
                continue
        elif _PEM_BEGIN.search(line):
            in_pem = True
        line = _NAMED_SECRET.sub(lambda m: f"{m[1]}{m[2]}{MARKER}{m[2]}", line)
        out.append(_TOKEN_FORMATS.sub(MARKER, line))
    return "\n".join(out)
