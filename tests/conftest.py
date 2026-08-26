from __future__ import annotations

import json

import pytest

from lazycoder.config import load_all_configs
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import CodeBlock

# Known-bad block from evals case E3: string-concatenated SQL (rule R7).
SQL_INJECTION_CODE = "cursor.execute('SELECT * FROM users WHERE name = ' + name)"

CLEAN_CODE = 'def greet(name: str) -> str:\n    return f"Hello, {name}"'

PASS_RESPONSE = '{"outcome": "pass", "line": null, "end_line": null, "reason": null}'


def fail_response(line: int, reason: str = "boom", end_line: int | None = None) -> str:
    return json.dumps(
        {"outcome": "fail", "line": line, "end_line": end_line, "reason": reason}
    )


def abstain_response(reason: str = "callers are not in this hunk") -> str:
    return json.dumps(
        {
            "outcome": "insufficient_context",
            "line": None,
            "end_line": None,
            "reason": reason,
        }
    )


def block(code: str, file: str = "sample.py", start_line: int = 1) -> CodeBlock:
    return CodeBlock(file=file, start_line=start_line, code=code)


@pytest.fixture(scope="session")
def rubric() -> ReviewRulesConfig:
    return load_all_configs().review_rules
