from __future__ import annotations

from argus.config import load_all_configs
from argus.domain import Verdict
from argus.llm import FakeLLMClient
from argus.orchestrator import parse_diff, review_diff
from argus.reviewers import SingleRuleReviewer

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
    client = FakeLLMClient(
        responses=['{"passed": true, "finding": null}'] * len(rubric.rules) * n_blocks
    )
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
    responses = ['{"passed": true, "finding": null}'] * len(rubric.rules) * n_blocks
    responses[0] = "not json"
    client = FakeLLMClient(responses=responses)
    reviewer = SingleRuleReviewer(client=client)

    report = review_diff(reviewer, _DIFF, rubric)

    assert len(report.rule_errors) == 1
    assert len(report.rule_results) == len(rubric.rules) * n_blocks - 1
    assert report.verdict == Verdict.REQUEST_CHANGES
