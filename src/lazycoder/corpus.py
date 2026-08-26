"""Scoring for a corpus of real diff hunks, as opposed to toy eval snippets.

The two labels are not scored the same way, and that asymmetry is the point:

- A **clean** hunk has a known answer. Anything the reviewer says about it is
  noise, no judgement required. This is where the honest precision number
  comes from.
- A **defective** hunk has one known defect and an unknown number of real ones
  beside it. A finding that is not the labelled one is *unlabelled*, not false
  — calling it a false positive would be inventing data we do not have.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lazycoder.config.models import ReviewRulesConfig
from lazycoder.domain import CodeBlock, RuleId, Verdict
from lazycoder.reviewers import SingleRuleReviewer


class Label(StrEnum):
    CLEAN = "clean"
    DEFECTIVE = "defective"


class HunkSource(BaseModel):
    """Where this hunk came from, so any number is traceable to real code."""

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1, description="owner/name")
    pr: int | None = None
    sha: str = Field(min_length=1)
    url: str | None = None


class CorpusHunk(BaseModel):
    # No str_strip_whitespace here: `code` is indentation-sensitive and the
    # line numbering downstream depends on it byte for byte.
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    source: HunkSource
    file: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    code: str = Field(min_length=1)
    label: Label
    expect_rules: list[RuleId] = Field(default_factory=list)
    note: str | None = None

    def model_post_init(self, _: object) -> None:
        if self.label is Label.CLEAN and self.expect_rules:
            msg = "a clean hunk cannot expect findings"
            raise ValueError(msg)
        if self.label is Label.DEFECTIVE and not self.expect_rules:
            msg = "a defective hunk must name the rule that should catch it"
            raise ValueError(msg)

    def block(self) -> CodeBlock:
        return CodeBlock(file=self.file, start_line=self.start_line, code=self.code)


class CorpusLoadError(Exception):
    """Raised when a corpus file is malformed or still holds unlabelled hunks."""


def load_corpus(path: Path) -> list[CorpusHunk]:
    """Read a JSONL corpus. Unlabelled candidates are refused, not skipped.

    Scoring against a partly-labelled corpus would silently report a number
    computed over a different set than the one you think you measured.
    """
    hunks: list[CorpusHunk] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"{path}:{number}: invalid JSON: {exc}"
            raise CorpusLoadError(msg) from exc
        if payload.get("label") is None:
            msg = (
                f"{path}:{number}: hunk {payload.get('id', '?')!r} is not labelled"
                " yet — label it clean or defective, or drop the line"
            )
            raise CorpusLoadError(msg)
        try:
            hunks.append(CorpusHunk.model_validate(payload))
        except ValidationError as exc:
            msg = f"{path}:{number}: {exc}"
            raise CorpusLoadError(msg) from exc

    ids = [hunk.id for hunk in hunks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        msg = f"{path}: duplicate hunk ids {sorted(duplicates)}"
        raise CorpusLoadError(msg)
    return hunks


@dataclass(frozen=True)
class HunkResult:
    hunk_id: str
    label: Label
    expected: frozenset[RuleId]
    fired: frozenset[RuleId]
    abstained: frozenset[RuleId]
    verdict: Verdict
    errored: frozenset[RuleId]

    @property
    def noise(self) -> frozenset[RuleId]:
        """Findings that are definitely wrong. Only knowable on clean hunks."""
        return self.fired if self.label is Label.CLEAN else frozenset()

    @property
    def unlabelled(self) -> frozenset[RuleId]:
        """Findings on a defective hunk that are not the labelled defect.

        Might be real, might be noise. Not counted either way — look at them.
        """
        if self.label is Label.CLEAN:
            return frozenset()
        return self.fired - self.expected

    @property
    def caught(self) -> frozenset[RuleId]:
        return self.expected & self.fired

    @property
    def missed(self) -> frozenset[RuleId]:
        return self.expected - self.fired

    @property
    def is_quiet(self) -> bool:
        """A clean hunk the reviewer left alone — the thing users actually feel."""
        return self.label is Label.CLEAN and not self.fired


def score_hunk(
    reviewer: SingleRuleReviewer, hunk: CorpusHunk, rubric: ReviewRulesConfig
) -> HunkResult:
    report = reviewer.review_rubric(hunk.block(), rubric)
    return HunkResult(
        hunk_id=hunk.id,
        label=hunk.label,
        expected=frozenset(hunk.expect_rules),
        fired=frozenset(f.rule_id for f in report.findings),
        abstained=frozenset(r.rule_id for r in report.abstentions),
        verdict=report.verdict,
        errored=frozenset(e.rule_id for e in report.rule_errors),
    )


@dataclass(frozen=True)
class RuleVerdict:
    """What the corpus says about one rule. The input to keeping or cutting it."""

    rule_id: RuleId
    clean_hunks: int
    fired_on_clean: int
    caught: int
    missed: int
    unlabelled: int
    abstained: int
    evaluated: int

    @property
    def clean_noise_rate(self) -> float:
        """How often this rule interrupts on code with nothing wrong with it."""
        return self.fired_on_clean / self.clean_hunks if self.clean_hunks else 0.0

    @property
    def abstention_rate(self) -> float:
        return self.abstained / self.evaluated if self.evaluated else 0.0


@dataclass(frozen=True)
class CorpusReport:
    clean_hunks: int
    defective_hunks: int
    quiet_clean_hunks: int
    noise_findings: int
    caught: int
    missed: int
    per_rule: dict[RuleId, RuleVerdict] = field(default_factory=dict)

    @property
    def quiet_rate(self) -> float:
        """Share of clean hunks the reviewer said nothing about.

        The headline number: how often it keeps its mouth shut when it should.
        """
        return self.quiet_clean_hunks / self.clean_hunks if self.clean_hunks else 1.0

    @property
    def noise_per_clean_hunk(self) -> float:
        return self.noise_findings / self.clean_hunks if self.clean_hunks else 0.0

    @property
    def recall(self) -> float:
        expected = self.caught + self.missed
        return self.caught / expected if expected else 1.0


def report(results: list[HunkResult], rubric: ReviewRulesConfig) -> CorpusReport:
    clean = [r for r in results if r.label is Label.CLEAN]
    defective = [r for r in results if r.label is Label.DEFECTIVE]

    noise: Counter[RuleId] = Counter()
    caught: Counter[RuleId] = Counter()
    missed: Counter[RuleId] = Counter()
    unlabelled: Counter[RuleId] = Counter()
    abstained: Counter[RuleId] = Counter()
    for result in results:
        noise.update(result.noise)
        caught.update(result.caught)
        missed.update(result.missed)
        unlabelled.update(result.unlabelled)
        abstained.update(result.abstained)

    per_rule = {
        rule.id: RuleVerdict(
            rule_id=rule.id,
            clean_hunks=len(clean),
            fired_on_clean=noise[rule.id],
            caught=caught[rule.id],
            missed=missed[rule.id],
            unlabelled=unlabelled[rule.id],
            abstained=abstained[rule.id],
            evaluated=len(results),
        )
        for rule in rubric.rules
    }
    return CorpusReport(
        clean_hunks=len(clean),
        defective_hunks=len(defective),
        quiet_clean_hunks=sum(1 for r in clean if r.is_quiet),
        noise_findings=sum(noise.values()),
        caught=sum(caught.values()),
        missed=sum(missed.values()),
        per_rule=per_rule,
    )
