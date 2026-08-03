"""The 12 regression cases for the v7 accuracy-banded verdict rule
(misconception_verdict_rule_spec section 9).

The rule has two pure pieces, both shared with the engine (no reimplementation):
  - wants_misconception_extra: the floor + reachability gate (Phase 1/2)
  - misconception_verdict:      the accuracy-band verdict (Phase 3)
`apply_sequence` drives an answer sequence through the gate exactly as the
controller does (called once per served answer), then takes the verdict - the
same logic the live engine runs, exercised in isolation.
"""
import pytest
from engine.misconception import (
    wants_misconception_extra, misconception_verdict,
    SIGNAL_LIKELY_ABSENT, SIGNAL_LIKELY_PRESENT, SIGNAL_UNSURE, SIGNAL_NOT_APPLICABLE,
    derive_misconception_signals, MISCONCEPTIONS,
)


def apply_sequence(answers, *, target=2, extra=2):
    """Consume answers (True=correct) while the gate wants another ask; return
    (final_asks, final_correct, verdict). Mirrors the controller's per-question
    loop: ask iff wants_misconception_extra, then re-evaluate."""
    asked = correct = 0
    for ans in answers:
        if not wants_misconception_extra(asked, correct, target=target, extra=extra):
            break
        asked += 1
        correct += 1 if ans else 0
    return asked, correct, misconception_verdict(asked, correct, target=target)


C, W = True, False


@pytest.mark.parametrize("seq, exp_asks, exp_correct, exp_verdict", [
    ([C, C],          2, 2, SIGNAL_LIKELY_ABSENT),    # 1  clear pass, stop at floor (2c)
    ([W, W],          2, 0, SIGNAL_LIKELY_PRESENT),   # 2  clear fail, stop at floor (2b)
    ([C, W, C, C],    4, 3, SIGNAL_LIKELY_ABSENT),    # 3a bubble -> cap, 3/4 (2c)
    ([C, W, C, W],    4, 2, SIGNAL_UNSURE),           # 3b bubble -> cap, 2/4 (2a)
    ([C, W, W],       3, 1, SIGNAL_LIKELY_PRESENT),   # 4  early 2nd wrong, unreachable (2b)
    ([W, C, C, C],    4, 3, SIGNAL_LIKELY_ABSENT),    # 5  recover to 3/4 (2c)
])
def test_standard_cases(seq, exp_asks, exp_correct, exp_verdict):
    asks, correct, verdict = apply_sequence(seq)
    assert (asks, correct, verdict) == (exp_asks, exp_correct, exp_verdict)


def test_case6_overask_3_of_6_unsure():
    # 6 opportunistic asks before pass B: asked >= cap, no extras, band on all.
    assert wants_misconception_extra(6, 3, target=2, extra=2) is False
    assert misconception_verdict(6, 3, target=2) == SIGNAL_UNSURE          # 50%


def test_case7_overask_4_of_5_absent():
    assert wants_misconception_extra(5, 4, target=2, extra=2) is False
    assert misconception_verdict(5, 4, target=2) == SIGNAL_LIKELY_ABSENT   # 80%


def test_case8_carrier_shortfall_forces_unsure():
    # Only 1 carrier exists -> 1 ask, below target -> unsure (shortfall override).
    assert misconception_verdict(1, 1, target=2) == SIGNAL_UNSURE


def test_case9_reserve_exhausted_after_split_floor():
    # Reserve spent right after the floor (1C 1W); no extra served -> 1/2 -> unsure.
    assert misconception_verdict(2, 1, target=2) == SIGNAL_UNSURE


def test_case10_x0_clear_pass():
    asks, correct, verdict = apply_sequence([C, C], target=2, extra=0)
    assert (asks, correct, verdict) == (2, 2, SIGNAL_LIKELY_ABSENT)


def test_case11_x0_split_unsure():
    asks, correct, verdict = apply_sequence([C, W], target=2, extra=0)
    assert (asks, correct, verdict) == (2, 1, SIGNAL_UNSURE)


def test_case12_not_applicable():
    class _S:
        misconception_applicable = set()  # nothing applicable
        misconception_asked = {m: 0 for m in MISCONCEPTIONS}
        misconception_correct = {m: 0 for m in MISCONCEPTIONS}
    sigs = derive_misconception_signals(_S(), misconception_target=2)
    assert all(s.state == SIGNAL_NOT_APPLICABLE for s in sigs)


def test_likely_absent_only_from_clearing_not_from_cap_or_unreachable():
    # Property from spec section 3: rules 2a/2b never yield likely_absent.
    for seq in ([C, W, C, W], [C, W, W], [W, W]):
        _, _, verdict = apply_sequence(seq)
        assert verdict != SIGNAL_LIKELY_ABSENT


# --- selection-spec test case 6: misconception_target = 3 switch ----------
@pytest.mark.parametrize("seq, exp_asks, exp_correct, exp_verdict", [
    ([C, C, C],       3, 3, SIGNAL_LIKELY_ABSENT),    # cleared at floor 3 (2c)
    ([C, C, W, C],    4, 3, SIGNAL_LIKELY_ABSENT),    # 3/4=75% after one extra (2c)
    ([C, C, W, W],    4, 2, SIGNAL_UNSURE),           # 2/4, then unreachable (2b)
    ([W, W, W],       3, 0, SIGNAL_LIKELY_PRESENT),   # 0/3 unreachable at floor (2b)
])
def test_target3_switch(seq, exp_asks, exp_correct, exp_verdict):
    asks, correct, verdict = apply_sequence(seq, target=3, extra=2)  # cap = 5
    assert (asks, correct, verdict) == (exp_asks, exp_correct, exp_verdict)


def test_below_target3_forces_unsure():
    assert misconception_verdict(2, 2, target=3) == SIGNAL_UNSURE     # 2<3 even at 100%


# --- thresholds are config-tunable (defaults preserved when unset) --------
def test_verdict_honors_custom_thresholds():
    # 3/5 = 60%: unsure at default 0.75 clear; absent if clear lowered to 0.60.
    assert misconception_verdict(5, 3, target=2) == SIGNAL_UNSURE
    assert misconception_verdict(5, 3, target=2, clear_threshold=0.60) == SIGNAL_LIKELY_ABSENT
    # 2/5 = 40%: present at default 0.50; unsure if present lowered to 0.30.
    assert misconception_verdict(5, 2, target=2) == SIGNAL_LIKELY_PRESENT
    assert misconception_verdict(5, 2, target=2, present_threshold=0.30) == SIGNAL_UNSURE


def test_gate_honors_custom_clear_threshold():
    # 2/3 = 67%: with default 0.75 the gate wants another (reachable); with clear
    # lowered to 0.60 the misconception is already cleared, so no extra.
    assert wants_misconception_extra(3, 2, target=2, extra=2) is True
    assert wants_misconception_extra(3, 2, target=2, extra=2, clear_threshold=0.60) is False
