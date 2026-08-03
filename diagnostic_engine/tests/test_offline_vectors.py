"""Phase E (mixed-mode v11 decision 10): the shared offline-walk vectors are
reproduced by the reference walk against the SHIPPED artifacts.

These vectors bind the app team's TypeScript walk to this Python reference. Each
grade carries several answer patterns (all-correct, all-wrong, seeded mixes),
each with a fresh and a resumed case, so the port is pinned across many tree
paths. This test loads the shipped trees and re-runs `follow_capped` for every
pattern/case, asserting it reproduces the golden sequence/count - the vectors and
reference cannot drift, and a walk regression fails immediately.
"""
import gzip
import json
from pathlib import Path

import pytest

ART = Path(__file__).resolve().parents[1] / "artifact" / "Delhi"
VECTORS = Path(__file__).resolve().parents[1] / "vectors" / "offline_walk_vectors.json"

pytestmark = pytest.mark.skipif(
    not (ART.exists() and VECTORS.exists()),
    reason="shipped artifacts / vector file not present",
)

from offline_follow import follow_capped                 # noqa: E402


class _T:
    def __init__(self, d):
        self.root, self.questions, self.nodes = d["root"], d["questions"], d["nodes"]


def test_offline_vectors_reproduce():
    doc = json.loads(VECTORS.read_text())
    op_order = doc["op_order"]
    assert doc["tree_compat_version"] == 1
    checked = 0
    for grade_str, gd in doc["grades"].items():
        adoc = json.loads(gzip.open(ART / f"g{grade_str}.json.gz", "rb").read())
        trees = {op: _T(adoc["trees"][op]) for op in op_order}
        items = {op: adoc["trees"][op]["items"] for op in op_order}
        for pat in gd["patterns"]:
            answers, default = pat["answers"], pat["default_answer"]
            for case in pat["cases"]:
                seq = []

                def answer_fn(qid, op, _s=seq, _a=answers, _d=default):
                    _s.append(qid)
                    return _a.get(qid, _d), qid

                follow_capped(trees, gd["budget"] - len(case["initial_answered_items"]),
                              answer_fn, op_order=op_order,
                              answered=dict(case["initial_answered_items"]) or None,
                              items=items,
                              unavailable=set(case.get("unavailable") or ()) or None)
                label = f"g{grade_str}/{pat['name']}/{case['name']}"
                assert seq == case["expected_sequence"], f"{label} sequence drift"
                assert len(seq) == case["expected_count"], f"{label} count drift"
                # Section 6b: a skipped (unavailable) question is never asked.
                for u in (case.get("unavailable") or ()):
                    assert u not in seq, f"{label} asked an unavailable question"
                checked += 1
    assert checked == 36
