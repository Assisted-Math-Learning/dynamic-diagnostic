"""Decision-9 retain-calibration guard (mixed-mode v11 decision 9).

Retiring a question removes it from selection but must KEEP its calibration row,
so any historical answer to it stays scoreable on the ingest's full replay
(section 9, step 3). The one documented exception is a fixed allow-list of
PRE-ARTIFACT retirements that were decalibrated before any offline tree was
built and are referenced by NO shipped tree - so they can never appear in a
question_history and are harmless (the harmlessness rests on the verified
tree-reference fact, not on retirement dates).

This module makes the invariant enforceable rather than assumed (the shipped data
has been inconsistent: of 27 item-scope retirements, 17 retain a calibration row
and these 10 were decalibrated). `check_retirement_calibration` is a pure check;
`tests/test_retirement_guard.py` runs it against the real bank + artifacts and
asserts zero violations.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Set

# The 10 pre-artifact decalibrated item-scope retirements (1 dated 2026-06-08,
# 9 dated 2026-06-17). No shipped tree references any of them - the check below
# verifies that - so they cannot enter a question_history. If you decalibrate a
# NEW retirement, do NOT add it here to silence the guard: keep its calibration
# row instead. This allow-list is only for retirements that predate every
# offline artifact.
DECALIBRATED_ALLOWLIST: frozenset = frozenset({
    "Division|Division using Distribution|Fib||4|2",
    "Division|Relationship between Multiplication and Division|Fib||6|3",
    "Multiplication|Repeated addition|Fib||2|4",
    "Multiplication|Repeated addition|Fib||2|7",
    "Multiplication|Repeated addition|Fib||2|9",
    "Multiplication|Repeated addition|Fib||3|3",
    "Multiplication|Repeated addition|Fib||5|3",
    "Multiplication|Repeated addition|Fib||5|5",
    "Multiplication|Tables 1 to 9|Fib||5|9",
    "Subtraction|2-digit Subtraction with borrowing|Fib||18|9",
})


def check_retirement_calibration(
    calibrated_items: Set[str],
    retired_items: Iterable[str],
    tree_items: Set[str],
) -> Dict[str, List[str]]:
    """Enforce decision 9. Returns a report with two lists, both empty when the
    invariant holds:

    - ``uncalibrated_not_allowlisted``: retired items that have NO calibration row
      and are NOT on the allow-list. This is a real violation - a historical
      answer to such an item could not be scored.
    - ``allowlisted_but_referenced_by_tree``: allow-listed items that ARE
      referenced by a shipped tree. This breaks the allow-list's premise (that
      no tree references them, so they can never appear in a history) and means
      the item must be recalibrated, not allow-listed.
    """
    retired = set(retired_items)
    uncalibrated_not_allowlisted = sorted(
        i for i in retired
        if i not in calibrated_items and i not in DECALIBRATED_ALLOWLIST
    )
    allowlisted_but_referenced = sorted(
        i for i in DECALIBRATED_ALLOWLIST if i in tree_items
    )
    return {
        "uncalibrated_not_allowlisted": uncalibrated_not_allowlisted,
        "allowlisted_but_referenced_by_tree": allowlisted_but_referenced,
    }
