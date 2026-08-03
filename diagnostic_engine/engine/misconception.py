"""Canonical misconception identifiers for the coverage-selection layer.

These are the 11 Fib-only misconception tags carried on each question item
(misconception_coverage_selection_spec section 3.2). The tuple is the single
source of truth for: the per-misconception session ledger (engine.session),
the applicability computation and tag carrying (engine.question_pool), and the
storage round-trip (engine.storage.documents). The names match the misconception
flag columns produced by the question-lookup build step, so the pool's loaded
flags align with this list one-to-one.

MCQ questions carry no tags today; when the content team adds MCQ tags the same
machinery applies with no logic change (spec section 10).
"""

from __future__ import annotations

# Order groups by operation (Addition, Subtraction, Multiplication, Division)
# for readability; the layer never relies on the order, only on membership.
MISCONCEPTIONS = (
    # Addition
    "x_plus_0",
    "x_plus_x",
    # Subtraction
    "x_minus_0",
    "zero_minus_x",
    "x_minus_x",
    # Multiplication
    "x_into_x",
    "x_into_0",
    # Division
    "zero_end_n1",
    "zero_mid_n1",
    "zero_end_quotient_no_zero_n1",
    "zero_mid_quotient_no_zero_n1",
)

MISCONCEPTION_SET = frozenset(MISCONCEPTIONS)

assert len(MISCONCEPTIONS) == 11, "expected exactly 11 misconceptions"
assert len(MISCONCEPTION_SET) == 11, "misconception names must be unique"


# --- The three-state signal (spec section 7) -------------------------------
# A triage prior for MainD, NOT a verdict. `unsure` is a legitimate output.
# State identifiers use the underscore form to match the other code-facing
# identifiers in this module (the spec writes "not-applicable" in prose).
SIGNAL_NOT_APPLICABLE = "not_applicable"
SIGNAL_LIKELY_PRESENT = "likely_present"
SIGNAL_LIKELY_ABSENT = "likely_absent"
SIGNAL_UNSURE = "unsure"

# v7 accuracy-band thresholds (misconception_verdict_rule_spec section 5). Shared
# by the verdict derivation here and the controller's reachability gate so the
# two never drift. Accuracy = correct / asked over ALL tagged asks; "correct"
# means the learner did NOT exhibit the error, so high accuracy => absent.
MISCONCEPTION_CLEAR_THRESHOLD = 0.75    # accuracy >= this -> likely_absent
MISCONCEPTION_PRESENT_THRESHOLD = 0.50  # accuracy <  this -> likely_present

from dataclasses import dataclass  # noqa: E402
from typing import TYPE_CHECKING, List  # noqa: E402

if TYPE_CHECKING:  # avoid a runtime import cycle (session imports this module)
    from engine.session import Session


@dataclass(frozen=True)
class MisconceptionSignal:
    """Per-misconception triage signal emitted at session end (verdict-rule spec).

    `wrong` is always `asked - correct`. The verdict (`state`) is an accuracy band
    over all tagged asks (v7): cleared (`likely_absent`) only at >=75% accuracy,
    flagged (`likely_present`) below 50%, else `unsure`; below `target` asks also
    forces `unsure`. There is no separate shortfall flag - a carrier shortfall is
    simply reported as `unsure`.
    """
    misconception: str
    state: str
    asked: int
    correct: int
    wrong: int


def misconception_verdict(
    asked: int, correct: int, *, target: int,
    clear_threshold: float = MISCONCEPTION_CLEAR_THRESHOLD,
    present_threshold: float = MISCONCEPTION_PRESENT_THRESHOLD,
) -> str:
    """The v7 accuracy-band verdict for one APPLICABLE misconception.

    `correct/asked` over all tagged asks: >= clear_threshold -> likely_absent,
    < present_threshold -> likely_present, else unsure. Below `target` asks (or
    zero) forces unsure. Thresholds default to the module constants but are
    config-tunable (selection spec 3.5); single source of truth, used by the
    signal derivation and by the reachability gate's "cleared" test.
    """
    if asked < target or asked == 0:
        return SIGNAL_UNSURE
    accuracy = correct / asked
    if accuracy >= clear_threshold:
        return SIGNAL_LIKELY_ABSENT
    if accuracy < present_threshold:
        return SIGNAL_LIKELY_PRESENT
    return SIGNAL_UNSURE


def wants_misconception_extra(
    asked: int, correct: int, *, target: int, extra: int,
    clear_threshold: float = MISCONCEPTION_CLEAR_THRESHOLD,
) -> bool:
    """The v7 reachability gate (verdict-rule spec section 6.1): does an applicable
    misconception want one more tagged ask?

    Below the floor (`asked < target`) it always wants one (Phase 1 fill). At or
    above the floor it wants one iff not yet cleared (accuracy < clear_threshold)
    AND clear_threshold is still reachable within the cap (`cap = target + extra`):
    every remaining allowed question correct would reach it. Stops on cap reached
    (2a), unreachable (2b), or already cleared (2c). Threshold is config-tunable.
    """
    cap = target + extra
    if asked < target:
        return True
    if asked >= cap:
        return False
    if correct / asked >= clear_threshold:
        return False
    if (correct + (cap - asked)) / cap < clear_threshold:
        return False
    return True


def derive_misconception_signals(
    session: "Session", *, misconception_target: int,
    clear_threshold: float = MISCONCEPTION_CLEAR_THRESHOLD,
    present_threshold: float = MISCONCEPTION_PRESENT_THRESHOLD,
) -> List[MisconceptionSignal]:
    """Compute the three-state signal for all 11 misconceptions (verdict-rule spec).

    Pure function of the session ledger and the applicable set. The verdict is the
    v7 accuracy band on `correct / asked` over all tagged asks (opportunistic +
    backfill): the asymmetric bands make clearing harder than flagging, the right
    bias for a triage prior to MainD. An applicable misconception below `target`
    asks (a carrier/reserve shortfall) is forced to `unsure`; MainD is the backstop.
    Thresholds default to the module constants but are config-tunable.
    """
    applicable = session.misconception_applicable
    out: List[MisconceptionSignal] = []
    for m in MISCONCEPTIONS:
        asked = session.misconception_asked.get(m, 0)
        correct = session.misconception_correct.get(m, 0)
        wrong = asked - correct
        if m not in applicable:
            state = SIGNAL_NOT_APPLICABLE
        else:
            state = misconception_verdict(
                asked, correct, target=misconception_target,
                clear_threshold=clear_threshold, present_threshold=present_threshold,
            )
        out.append(MisconceptionSignal(m, state, asked, correct, wrong))
    return out
