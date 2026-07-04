from __future__ import annotations

import pytest

from argus.config import load_all_configs
from argus.config.models import ReviewRulesConfig

# Known-bad block from evals case E3: string-concatenated SQL (rule R7).
SQL_INJECTION_CODE = "cursor.execute('SELECT * FROM users WHERE name = ' + name)"

CLEAN_CODE = 'def greet(name: str) -> str:\n    return f"Hello, {name}"'


@pytest.fixture(scope="session")
def rubric() -> ReviewRulesConfig:
    return load_all_configs().review_rules
