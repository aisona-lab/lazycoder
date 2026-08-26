from __future__ import annotations

from conftest import PASS_RESPONSE, fail_response
from lazycoder.config import load_all_configs
from lazycoder.domain import RuleId, Verdict
from lazycoder.llm import FakeLLMClient
from lazycoder.orchestrator import parse_diff, review_diff
from lazycoder.reviewers import SingleRuleReviewer

_DIFF = """\
diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,3 @@
 def average(xs):
-    return sum(xs) / len(xs)
+    if not xs:
+        return 0
diff --git a/util.py b/util.py
--- a/util.py
+++ b/util.py
@@ -10,0 +11,1 @@
+CONST = 1
"""


def test_parse_diff_splits_hunks_by_file_and_start_line() -> None:
    blocks = parse_diff(_DIFF)

    assert [(b.file, b.start_line) for b in blocks] == [("calc.py", 1), ("util.py", 11)]
    # Added + context lines kept, '-' removals dropped, markers stripped.
    assert blocks[0].code == "def average(xs):\n    if not xs:\n        return 0"
    assert blocks[1].code == "CONST = 1"


_TSX_DIFF = """\
diff --git a/src/Component.tsx b/src/Component.tsx
--- a/src/Component.tsx
+++ b/src/Component.tsx
@@ -1,4 +1,7 @@
 export function Foo({ bar }: Props) {
+  if (!bar) {
+    return null;
+  }
   return <div>{bar}</div>;
 }
"""


def test_parse_diff_handles_typescript_tsx_hunks() -> None:
    blocks = parse_diff(_TSX_DIFF)

    assert len(blocks) == 1
    assert blocks[0].file == "src/Component.tsx"
    assert "if (!bar)" in blocks[0].code
    assert blocks[0].code.startswith("export function Foo({ bar }: Props)")


def test_review_diff_aggregates_every_block_into_one_report() -> None:
    config = load_all_configs()
    rubric = config.review_rules
    n_blocks = len(parse_diff(_DIFF))
    client = FakeLLMClient(responses=[PASS_RESPONSE] * len(rubric.rules) * n_blocks)
    reviewer = SingleRuleReviewer(client=client)

    report = review_diff(reviewer, _DIFF, rubric)

    assert len(report.rule_results) == len(rubric.rules) * n_blocks
    assert report.findings == []
    assert report.rule_errors == []
    assert report.verdict == Verdict.APPROVE


def test_review_diff_survives_a_single_rule_parse_failure() -> None:
    config = load_all_configs()
    rubric = config.review_rules
    n_blocks = len(parse_diff(_DIFF))
    responses = [PASS_RESPONSE] * len(rubric.rules) * n_blocks
    responses[0] = "not json"
    client = FakeLLMClient(responses=responses)
    reviewer = SingleRuleReviewer(client=client)

    report = review_diff(reviewer, _DIFF, rubric)

    assert len(report.rule_errors) == 1
    assert len(report.rule_results) == len(rubric.rules) * n_blocks - 1
    assert report.verdict == Verdict.REQUEST_CHANGES


def test_review_diff_cites_the_file_and_line_the_hunk_actually_came_from() -> None:
    # Regression guard for the bug this hardening pass exists to fix: the
    # orchestrator used to hand the reviewer bare code and drop file/start_line,
    # so every citation was invented. util.py's hunk starts at line 11.
    config = load_all_configs()
    rubric = config.review_rules
    n_rules = len(rubric.rules)
    responses = [PASS_RESPONSE] * n_rules * 2
    r7_index = next(i for i, r in enumerate(rubric.rules) if r.id == RuleId.R7)
    responses[n_rules + r7_index] = fail_response(11, "invented locations are over")
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))

    report = review_diff(reviewer, _DIFF, rubric)

    assert len(report.findings) == 1
    assert report.findings[0].location.file == "util.py"
    assert report.findings[0].location.line == 11


def test_review_diff_turns_an_unanchored_citation_into_a_rule_error() -> None:
    config = load_all_configs()
    rubric = config.review_rules
    n_rules = len(rubric.rules)
    responses = [PASS_RESPONSE] * n_rules * 2
    # util.py's hunk is a single line at 11; line 400 is not in it.
    responses[n_rules] = fail_response(400, "somewhere else entirely")
    reviewer = SingleRuleReviewer(client=FakeLLMClient(responses=responses))

    report = review_diff(reviewer, _DIFF, rubric)

    assert report.findings == []
    assert len(report.rule_errors) == 1
    assert "outside the reviewed hunk" in report.rule_errors[0].message
    assert report.verdict == Verdict.REQUEST_CHANGES


_BLANK_CONTEXT_DIFF = (
    "--- a/m.py\n"
    "+++ b/m.py\n"
    "@@ -1,3 +1,4 @@\n"
    " def a():\n"
    "     return 1\n"
    "\n"  # blank context line, leading space stripped by the diff producer
    "+def b():\n"
)


def test_parse_diff_keeps_blank_context_lines_so_numbering_does_not_shift() -> None:
    # Dropping the blank line reported `def b():` at line 3 when it is line 4
    # in the new file — an anchored citation pointing at the wrong line.
    block = parse_diff(_BLANK_CONTEXT_DIFF)[0]

    assert block.start_line == 1
    assert block.end_line == 4
    assert block.code.split("\n") == ["def a():", "    return 1", "", "def b():"]
    assert block.numbered().splitlines()[-1] == "4\tdef b():"
