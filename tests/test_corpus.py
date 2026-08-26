from __future__ import annotations

import pytest
from pydantic import ValidationError

from conftest import PASS_RESPONSE, abstain_response, fail_response
from lazycoder.config.models import ReviewRulesConfig
from lazycoder.corpus import (
    CorpusHunk,
    CorpusLoadError,
    HunkSource,
    Label,
    load_corpus,
    report,
    score_hunk,
)
from lazycoder.domain import RuleId, Verdict
from lazycoder.llm import FakeLLMClient
from lazycoder.reviewers import SingleRuleReviewer

INDENTED = "def total(items):\n    return sum(\n        i.price for i in items\n    )"


def _source() -> HunkSource:
    return HunkSource(repo="acme/widgets", pr=42, sha="deadbeef")


def _hunk(
    label: Label, expect: list[RuleId] | None = None, hid: str = "C1"
) -> CorpusHunk:
    return CorpusHunk(
        id=hid,
        source=_source(),
        file="src/total.py",
        start_line=10,
        code=INDENTED,
        label=label,
        expect_rules=expect or [],
    )


def _responses(rubric: ReviewRulesConfig, fires: dict[RuleId, str]) -> list[str]:
    return [fires.get(rule.id, PASS_RESPONSE) for rule in rubric.rules]


def test_hunk_preserves_indentation_byte_for_byte() -> None:
    # The strict config models strip whitespace; a corpus hunk must not, or the
    # line numbering the citations depend on stops matching the source.
    block = _hunk(Label.CLEAN).block()

    assert block.code == INDENTED
    assert block.start_line == 10
    assert block.end_line == 13
    assert block.numbered().splitlines()[1] == "11\t    return sum("


def test_a_clean_hunk_may_not_declare_expected_findings() -> None:
    with pytest.raises(ValidationError, match="clean hunk cannot expect findings"):
        _hunk(Label.CLEAN, [RuleId.R7])


def test_a_defective_hunk_must_name_the_rule_that_should_catch_it() -> None:
    with pytest.raises(ValidationError, match="must name the rule"):
        _hunk(Label.DEFECTIVE, [])


def test_every_finding_on_a_clean_hunk_is_noise(rubric: ReviewRulesConfig) -> None:
    client = FakeLLMClient(
        responses=_responses(rubric, {RuleId.R12: fail_response(10, "vague")})
    )

    result = score_hunk(SingleRuleReviewer(client=client), _hunk(Label.CLEAN), rubric)

    assert result.noise == {RuleId.R12}
    assert result.unlabelled == frozenset()
    assert result.is_quiet is False


def test_an_unlabelled_finding_on_a_defective_hunk_is_not_called_noise(
    rubric: ReviewRulesConfig,
) -> None:
    # R7 is the labelled defect; R12 also fired. We do not know whether R12 is
    # right, so it is reported apart rather than scored as a false positive.
    client = FakeLLMClient(
        responses=_responses(
            rubric,
            {
                RuleId.R7: fail_response(10, "injectable"),
                RuleId.R12: fail_response(11, "maybe real, maybe not"),
            },
        )
    )
    hunk = _hunk(Label.DEFECTIVE, [RuleId.R7])

    result = score_hunk(SingleRuleReviewer(client=client), hunk, rubric)

    assert result.caught == {RuleId.R7}
    assert result.missed == frozenset()
    assert result.unlabelled == {RuleId.R12}
    assert result.noise == frozenset()


def test_quiet_rate_counts_clean_hunks_the_reviewer_left_alone(
    rubric: ReviewRulesConfig,
) -> None:
    quiet = _responses(rubric, {})
    noisy = _responses(rubric, {RuleId.R3: fail_response(10, "unclear io")})
    client = FakeLLMClient(responses=quiet + noisy + quiet)
    reviewer = SingleRuleReviewer(client=client)

    results = [
        score_hunk(reviewer, _hunk(Label.CLEAN, hid=f"C{n}"), rubric) for n in range(3)
    ]
    summary = report(results, rubric)

    assert summary.clean_hunks == 3
    assert summary.quiet_clean_hunks == 2
    assert summary.quiet_rate == pytest.approx(2 / 3)
    assert summary.noise_per_clean_hunk == pytest.approx(1 / 3)
    assert summary.per_rule[RuleId.R3].clean_noise_rate == pytest.approx(1 / 3)
    assert summary.per_rule[RuleId.R12].clean_noise_rate == 0.0


def test_recall_is_measured_only_against_labelled_defects(
    rubric: ReviewRulesConfig,
) -> None:
    caught = _responses(rubric, {RuleId.R7: fail_response(10, "injectable")})
    silent = _responses(rubric, {})
    client = FakeLLMClient(responses=caught + silent)
    reviewer = SingleRuleReviewer(client=client)

    results = [
        score_hunk(reviewer, _hunk(Label.DEFECTIVE, [RuleId.R7], "D1"), rubric),
        score_hunk(reviewer, _hunk(Label.DEFECTIVE, [RuleId.R4], "D2"), rubric),
    ]
    summary = report(results, rubric)

    assert summary.recall == pytest.approx(0.5)
    assert summary.per_rule[RuleId.R7].caught == 1
    assert summary.per_rule[RuleId.R4].missed == 1
    # No clean hunks in this set, so the noise numbers stay honest at zero.
    assert summary.clean_hunks == 0
    assert summary.quiet_rate == 1.0


def test_abstentions_are_tracked_apart_from_silence(rubric: ReviewRulesConfig) -> None:
    # A rule that abstains is not the same as a rule that passed: one is
    # quiet because there is nothing wrong, the other because it cannot tell.
    client = FakeLLMClient(
        responses=_responses(rubric, {RuleId.R16: abstain_response("no callers here")})
    )

    result = score_hunk(SingleRuleReviewer(client=client), _hunk(Label.CLEAN), rubric)
    summary = report([result], rubric)

    assert result.abstained == {RuleId.R16}
    assert result.is_quiet is True
    assert summary.per_rule[RuleId.R16].abstention_rate == 1.0
    # R16 is medium, so its abstention is neutral: the hatch does not become
    # a second way to withhold approval from code with nothing wrong with it.
    assert result.verdict is Verdict.APPROVE


def _line(**overrides: object) -> str:
    import json

    payload = {
        "id": "C1",
        "source": {"repo": "acme/widgets", "pr": 42, "sha": "deadbeef"},
        "file": "src/total.py",
        "start_line": 10,
        "code": INDENTED,
        "label": "clean",
        "expect_rules": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_load_corpus_refuses_unlabelled_hunks(tmp_path) -> None:
    # Skipping them would report a number computed over a different set than
    # the one you think you measured.
    path = tmp_path / "corpus.jsonl"
    path.write_text(_line() + "\n" + _line(id="C2", label=None) + "\n")

    with pytest.raises(CorpusLoadError, match="C2.*not labelled"):
        load_corpus(path)


def test_load_corpus_refuses_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "corpus.jsonl"
    path.write_text(_line() + "\n" + _line() + "\n")

    with pytest.raises(CorpusLoadError, match="duplicate hunk ids"):
        load_corpus(path)


def test_load_corpus_keeps_code_verbatim_and_skips_blank_lines(tmp_path) -> None:
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n" + _line() + "\n\n")

    hunks = load_corpus(path)

    assert len(hunks) == 1
    assert hunks[0].code == INDENTED
    assert hunks[0].source.repo == "acme/widgets"
