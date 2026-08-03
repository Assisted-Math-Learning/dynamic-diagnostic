"""Phase E (mixed-mode v11 decision 9): the retain-calibration guard is enforced.

Every item-scope retirement must either keep its calibration row, or be on the
documented allow-list of pre-artifact retirements that NO shipped tree
references. This runs the guard against the real bank + shipped artifacts and
asserts zero violations, plus unit-checks the guard logic itself.
"""
import gzip
import json
from pathlib import Path

import pytest

from tests import DATA_DIR
from engine.retirement_guard import (
    DECALIBRATED_ALLOWLIST,
    check_retirement_calibration,
)

PROJECT = DATA_DIR
ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "Delhi"
RETIRED = Path(__file__).resolve().parents[1] / "inputs" / "retired_questions_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists() and (PROJECT / "question_parameters.csv").exists()
         and RETIRED.exists() and ARTIFACT.exists()),
    reason="real project data / artifacts not present",
)


def _load_real():
    import pandas as pd
    params = pd.read_csv(PROJECT / "question_parameters.csv")
    ret = pd.read_csv(RETIRED)
    calibrated_items = set(params["item"])
    retired_items = set(ret[ret["scope"] == "item"]["key"])
    # Items referenced by any shipped tree (map tree q_x_id -> item via params).
    qxid_to_item = dict(zip(params["q_x_id"], params["item"]))
    tree_items = set()
    for f in ARTIFACT.glob("g*.json.gz"):
        doc = json.loads(gzip.open(f, "rb").read())
        for op in doc["trees"].values():
            for qx in op["questions"]:
                it = qxid_to_item.get(qx)
                if it is not None:
                    tree_items.add(it)
    return calibrated_items, retired_items, tree_items


def test_guard_holds_on_shipped_data():
    calibrated_items, retired_items, tree_items = _load_real()
    report = check_retirement_calibration(calibrated_items, retired_items, tree_items)
    # Invariant: no retired item is both uncalibrated and not allow-listed...
    assert report["uncalibrated_not_allowlisted"] == []
    # ...and no allow-listed item is referenced by a shipped tree.
    assert report["allowlisted_but_referenced_by_tree"] == []


def test_allowlist_is_exactly_the_decalibrated_set():
    calibrated_items, retired_items, _ = _load_real()
    decalibrated = {i for i in retired_items if i not in calibrated_items}
    # The allow-list must match the actual decalibrated retirements exactly -
    # no stale entries, and nothing decalibrated left off.
    assert set(DECALIBRATED_ALLOWLIST) == decalibrated


def test_guard_flags_a_new_uncalibrated_retirement():
    # A newly retired item that is decalibrated but NOT allow-listed is a
    # violation (its historical answers could not be scored).
    report = check_retirement_calibration(
        calibrated_items={"A|s|Fib||1|1"},
        retired_items={"A|s|Fib||1|1", "Z|new|Fib||9|9"},
        tree_items=set(),
    )
    assert report["uncalibrated_not_allowlisted"] == ["Z|new|Fib||9|9"]


def test_guard_flags_allowlisted_item_in_a_tree():
    some = next(iter(DECALIBRATED_ALLOWLIST))
    report = check_retirement_calibration(
        calibrated_items=set(),
        retired_items={some},
        tree_items={some},          # a tree references an allow-listed item
    )
    assert report["allowlisted_but_referenced_by_tree"] == [some]
