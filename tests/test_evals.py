from __future__ import annotations

import json

from argus.config import load_all_configs
from argus.config.models import ReviewRulesConfig
from argus.domain import RuleId, Verdict
from argus.evals import run_case
from argus.llm import FakeLLMClient
from argus.reviewers import SingleRuleReviewer


def _responses(
    rubric: ReviewRulesConfig, finding_for: dict[RuleId, dict[str, object]]
) -> list[str]:
    """One queued fake response per rule, in rubric order (FIFO)."""
    out: list[str] = []
    for rule in rubric.rules:
        finding = finding_for.get(rule.id)
        if finding is None:
            out.append('{"passed": true, "finding": null}')
        else:
            out.append(json.dumps({"passed": False, "finding": finding}))
    return out


def _r7_finding() -> dict[str, object]:
    return {
        "rule_id": "R7",
        "location": {"file": "e3.py", "line": 1},
        "severity": "high",
        "reason": "string-concatenated SQL is injectable",
    }


def _e3_case():
    config = load_all_configs()
    case = next(c for c in config.evals.cases if c.id == "E3")
    return case, config.review_rules


def test_gate_passes_when_reviewer_catches_the_expected_rule() -> None:
    case, rubric = _e3_case()
    client = FakeLLMClient(responses=_responses(rubric, {RuleId.R7: _r7_finding()}))
    reviewer = SingleRuleReviewer(client=client)

    result = run_case(reviewer, case, rubric)

    assert result.passed is True
    assert RuleId.R7 in result.actual_rule_ids
    assert result.actual_verdict == Verdict.BLOCK


def test_gate_fails_when_reviewer_misses_the_expected_rule() -> None:
    # Reviewer passes every rule → no findings → misses R7 and verdict APPROVEs.
    # A gate that cannot fail here is theater; this proves it has teeth.
    case, rubric = _e3_case()
    client = FakeLLMClient(responses=_responses(rubric, {}))
    reviewer = SingleRuleReviewer(client=client)

    result = run_case(reviewer, case, rubric)

    assert result.passed is False
    assert RuleId.R7 not in result.actual_rule_ids
    assert result.actual_verdict == Verdict.APPROVE
    assert result.expected_verdict == Verdict.BLOCK
