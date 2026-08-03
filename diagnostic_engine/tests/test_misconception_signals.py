"""Unit tests for the v7 accuracy-band misconception signal (verdict-rule spec).

derive_misconception_signals is a pure function of the ledger + applicable set,
so these run without data fixtures. A lightweight stub supplies only the three
attributes the function reads.
"""
from engine.misconception import (
    MISCONCEPTIONS,
    SIGNAL_LIKELY_ABSENT,
    SIGNAL_LIKELY_PRESENT,
    SIGNAL_NOT_APPLICABLE,
    SIGNAL_UNSURE,
    derive_misconception_signals,
)


class _LedgerStub:
    def __init__(self, applicable, asked, correct):
        self.misconception_applicable = set(applicable)
        self.misconception_asked = {m: 0 for m in MISCONCEPTIONS}
        self.misconception_correct = {m: 0 for m in MISCONCEPTIONS}
        self.misconception_asked.update(asked)
        self.misconception_correct.update(correct)


def _state(applicable, asked, correct, target=2):
    sigs = derive_misconception_signals(
        _LedgerStub(applicable, {"x_plus_0": asked}, {"x_plus_0": correct}),
        misconception_target=target)
    return {s.misconception: s for s in sigs}["x_plus_0"]


def test_emits_all_eleven_in_canonical_order():
    sigs = derive_misconception_signals(_LedgerStub([], {}, {}), misconception_target=2)
    assert [s.misconception for s in sigs] == list(MISCONCEPTIONS)
    assert len(sigs) == 11


def test_signal_has_no_shortfall_field():
    s = _state(["x_plus_0"], 2, 1)
    assert not hasattr(s, "shortfall")
    assert (s.asked, s.correct, s.wrong) == (2, 1, 1)


def test_not_applicable():
    s = _state([], 0, 0)
    assert s.state == SIGNAL_NOT_APPLICABLE


def test_likely_absent_at_or_above_75pct():
    assert _state(["x_plus_0"], 2, 2).state == SIGNAL_LIKELY_ABSENT   # 100%
    assert _state(["x_plus_0"], 4, 3).state == SIGNAL_LIKELY_ABSENT   # 75%
    assert _state(["x_plus_0"], 5, 4).state == SIGNAL_LIKELY_ABSENT   # 80%


def test_likely_present_below_50pct():
    assert _state(["x_plus_0"], 2, 0).state == SIGNAL_LIKELY_PRESENT  # 0%
    assert _state(["x_plus_0"], 3, 1).state == SIGNAL_LIKELY_PRESENT  # 33%
    assert _state(["x_plus_0"], 4, 1).state == SIGNAL_LIKELY_PRESENT  # 25%


def test_unsure_in_the_50_to_75_band():
    assert _state(["x_plus_0"], 2, 1).state == SIGNAL_UNSURE          # 50%
    assert _state(["x_plus_0"], 4, 2).state == SIGNAL_UNSURE          # 50%
    assert _state(["x_plus_0"], 3, 2).state == SIGNAL_UNSURE          # 66.7%
    assert _state(["x_plus_0"], 6, 3).state == SIGNAL_UNSURE          # 50% (over-ask)


def test_below_target_forces_unsure():
    assert _state(["x_plus_0"], 0, 0).state == SIGNAL_UNSURE          # zero asks
    assert _state(["x_plus_0"], 1, 1).state == SIGNAL_UNSURE          # 1<target, even 100%


def test_wrong_is_asked_minus_correct():
    sigs = derive_misconception_signals(
        _LedgerStub(["x_plus_0", "x_into_0"], {"x_plus_0": 5, "x_into_0": 3},
                    {"x_plus_0": 2, "x_into_0": 3}), misconception_target=2)
    for s in sigs:
        assert s.wrong == s.asked - s.correct
