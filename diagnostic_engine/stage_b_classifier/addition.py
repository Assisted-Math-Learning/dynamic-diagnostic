"""
Addition misconception classifier (codes A01–A26), v17.

v17 — Promotion to a clean integer version. No behavioral or code change:
  consolidates the v16 cascade renumber (every code at its cascade position)
  and the v16.1 compound double+zero polarity flip (A21 ZERO_RULE_ERROR is
  Final when both identities co-occur, A22 retained as a marker) under one
  version label.

v16.1 — Compound double+zero polarity flip. When one answer fails BOTH the
  x+0 (zero) and x+x (double) identities — detected by the existing
  _compound_double_zero_traces simulator (zero_compound) — A21 ZERO_RULE_ERROR
  now fires and is the Final code, with A22 DOUBLE_RULE_ERROR retained as a
  marker. v15/v16 did the reverse (A22 Final, A21 marker). Akshay's call: the
  zero rule is the headline misconception when both co-occur, matching the
  subtraction convention (S26 X_MINUS_ZERO is Final over S27). Per-column tests
  and pure double / pure zero cases are unchanged; only compound traces move
  A22->A21. Example: 201+292='203' -> Final A21, markers A21+A22.

Cumulative changes over v13:

  NOTE — v16 renumbered every code to its cascade position (entry T has the
  full v15 -> v16 map). All code identifiers BELOW, including in historical
  entries A–S, cite each misconception under its CURRENT v16 identifier, not
  the identifier it carried at the time of that entry. Example: entry A
  describes a change to DOUBLE_RULE_ERROR, shown here as A22 (its v16 code),
  though it was A18 when the change shipped in v14.

  A. A22 — width=1 relaxation of the `<5` doubled-digit guard. (v14)
  B. A22 — same-length subcase requires width >= 2. (v14)
  C. A22 — restricted subcase (iii): fires only if units col is doubled
     OR operands have equal width. (v14)
  D. A21 Tier 2 — padding zeros beyond the operand stack don't count. (v14)
  E. A12 — grid permutations enumerate ALL split widths. (v14.1)
  F. A18 — accepts wi one digit wider than `correct`. (v14.1)
  G. A19 — same treatment as A18. (v14.2)
  H. A22 — drop the `<5` guard for equal-width problems. (v14.2)
  I. A22 — same-length subcase defers to A23 mode (c) boundary slip. (v14.3)
  J. A22 — variants C and D require full simulated answer to equal wi. (v14.4)
  K. A22 — same-length subcase requires equal operand widths. The
     audit revealed FP1 (350 rows / 1,797 freq, sheet=A24) and FP3
     (20 rows / 305 freq, sheet=A23) were 100% unequal-width problems
     where variants A or B coincidentally matched at one doubled
     column. The corpus contains ZERO sheet-A22 same-length cases
     with unequal widths. (v14.5)
  L. A22 — variants C and D simulate with PROPAGATED carry (the
     variant sets carry_out=0 at each doubled col), not the natural
     carries_in. Fixes the 26+26=36 family where the natural-carry
     check was permissive enough to fire even though the kid couldn't
     have produced wi by consistent variant application. Applies to
     both same-length subcase and subcase (ii). (v14.5)
  M. A03 — defers to A22 when A22 also fires. When wi coincidentally
     equals |n1-n2| AND a doubled-column variant matches, the corpus
     prefers A22 (e.g. 64+34=30: |64-34|=30 and variant B at units
     predicts 0). Matches A03's existing deferrals to A09/A10/A11. (v14.5)
  N. A16/A15 — first attempt at the "kid didn't extend the carry into a
     new place value" split via a predicate-level gate inside _rule_A16.
     (v14.6)
  O. A16/A15 — replaced the v14.6 gate by moving A15 above A16 in
     ADDITION_CASCADE_ORDER, so the marker columns honestly reflect
     "all patterns matched" while Final routes to the more cognitively
     specific A15 (e.g. 89+78='67' → Final A15, markers A16+A15). (v14.7)
  P. v15 release:
     - A08 — defers to A21. When the answer equals an operand because a
       +0 column was annihilated (e.g. 3+60='60', expected 63), it is a
       zero-rule error, not a partial-operand copy. (item 5)
     - A23 — mode (a) defers to A04. A single-digit "product" answer is a
       wrong-operation error, not a slip (e.g. 2+3='6', 3+4='12'). (item 6)
     - A22 — gains a width-guarded compound double/zero simulation path.
       Fires when a per-column trace reproducing wi uses >=1 double rule
       AND (>=2 special columns OR a doubled digit x>=5), with a mandatory
       n_digits(wi)==n_digits(correct) guard that excludes degenerate
       width-collapse ('wrote 0') answers (e.g. recovers 998+88='1078',
       26+26='46', 123+123='223'). Legacy variant paths are untouched, but
       NOTE this REVERSES the v14.1/v14.2 exclusion of x>=5 unequal-width
       doubles (~1,070 freq now A22, e.g. 7+27='20', 89+9='80'): the exact
       full-trace reproduction is a stronger test than the old one-column
       coincidence check that the veto guarded against. Corpus: +1,366 freq
       across A03/A26/A24 -> A22. (items 1+2)
     - A21 — added as a MARKER (not primary) on compound double+zero
       answers: when an A22 row also has a width-guarded trace using a
       +0 annihilation (e.g. 201+292='203' → Final A22, markers A22+A21).
       Cascade primary is unchanged. (item 4)
     - A22 — also fires (item 7, adopted) on a single doubled column with
       x<5 where the learner wrote the addend ("x+x=x", e.g. 21+328='329'
       2+2->2, 6954+324='7274' 4+4->4 at units), every other column correct.
       Guarded against partial-operand copies (wi == an operand stays A08,
       e.g. 30+31='31'). Net corpus impact: 237 freq, A23 -> A22, no A08
       cannibalisation.
     - Housekeeping: dedup the doubled `equal_widths` assignment in
       _rule_A22; corrected the stale A22 docstring bullet that still
       claimed x>=5 always falls to A23 (false since v14.2 Fix H).
     - NOT adopted: A21 Tier 4 pure-zero trace (item 3, low value /
       overlaps A16). A21 Tier 2 is deliberately LEFT INTACT (item 8
       rejected): a wrong value at a carry-free +0 column is a conceptual
       additive-identity failure, not an arithmetic slip.
  Q. v15 — drop the A22 "x+x=0" family; route it to A03/A16 (pedagogy call):
     - A22 now fires ONLY for the "write the doubled digit" family (variants
       A/C). Variants B/D (x+x=0) were removed from every path (the simulator
       double moves and all three legacy variant loops). Rationale: x+x ends
       in 0 only at x=5, so writing 0 at a doubled column has no doubling
       reading — it is subtraction or a dropped carry.
     - A03 gains an equal-operands-zero path: N1==N2 AND wi==0 -> A03
       (x-x=0, e.g. 1+1='0', 3+3='0', 9+9='0', 123+123='0'); the N1>1 and
       wi>0 guards do not apply to this path.
     - A03 now defers to A16 (carry-ignore) in place of the old defer-to-A22
       (Fix M): the carry-drop family (e.g. 5+55='50' == |55-5|) stays A16.
     - Net: A22 ~23,392 -> ~13,804; the dropped =0 mass splits into A03
       (clean subtraction 7+27='20'=27-7, plus equal-operand zeros), A16
       (x=5 carry drops), A23/A24 (slips), and ~3,880 freq of genuine noise
       (wrote 0 with no structure, e.g. 30+31='0') -> A26.
  R. v15 — A04 allows equal operands (pedagogy call): the N1 != N2 guard was
     removed so x+x written as the product is wrong-op multiplication, e.g.
     5+5='25' (=5x5), 4+4='16', 26+26='676'. 2+2='4' stays CORRECT (product ==
     sum). Net corpus: +1,612 freq to A04 (654 from A26 clear products, 958
     from A23 via item 6, e.g. 3+3='9'=3x3). NOTE: 9+9='81' stays A02 because
     81 is also the digit-reversal of the sum 18 and A02 sits earlier in the
     cascade — an A02-vs-A04 priority question left open (resolved in S).
  S. v15 — "exact product wins" over soft coincidental readings (closes the
     A02-vs-A04 question from R). When the answer is EXACTLY n1*n2 (A04 fires),
     four earlier codes now defer to A04 instead of pre-empting it:
       - A02 (transposition): 9+9='81' is 9x9, not a digit-swap of 18. (1,570)
       - A24 (multi-column slip): 13+6='78' is 13x6, far from the sum 19 — a
         "slip" that lands exactly on the product is multiplication. (733)
       - A12 (place-value): 11+2='22' is 11x2, not a place permutation. (145)
       - A21 (zero-rule): 8+10='80' is 8x10, 10+8='80' — pedagogy call to treat
         the exact product as decisive even when an operand has a 0 column. (129)
     A23's item-6 A04 deferral (previously 1D+1D only) is lifted to ALL modes so
     a multi-digit slip landing exactly on the product also routes to A04 (e.g.
     32+2='64' = 32x2, far from the sum 34; would otherwise read as a single-
     column tens slip). After this, EVERY row where wi == n1*n2 (and A04's guards
     pass) routes to A04 — zero remaining pre-emptions.
     Mechanism is the same forward-deferral item 6 introduced (A23->A04);
     ADDITION_CASCADE_ORDER is unchanged. Net corpus: +2,577 freq to A04.

  T. v16 — cascade-order renumber (no behavioral change; pure relabel). Two
     parts: (1) A23 (multiplication) moved to sit between A22 (subtraction) and
     A24 (division) in ADDITION_CASCADE_ORDER, grouping the three wrong-operation
     codes — verified a behavioral no-op (the entry-S deferrals already route
     every exact product to A23, so its position does not affect any tag); and
     (2) all codes renumbered so the identifier number EQUALS the cascade
     position, making ADDITION_CASCADE_ORDER the trivial sorted A01..A26.
     Every learner's diagnosis is identical to v15 under the mapping below;
     only the labels change. Verified: new_tag == map(old_tag) for all 169,165
     unique corpus rows. Old -> new code map:
       A01->A01  A02->A02  A22->A03  A23->A04  A24->A05  A03->A06  A04->A07
       A05->A08  A06->A09  A07->A10  A08->A11  A09->A12  A10->A13  A11->A14
       A21->A15  A12->A16  A13->A17  A14->A18  A15->A19  A16->A20  A17->A21
       A18->A22  A19->A23  A20->A24  A25->A25  A26->A26
     (Downstream consumers — tagged workbooks, Metabase queries, the SCERT
     deck — must migrate via this map; old and new code spaces overlap, so a
     stale 'A17' reference now silently means a different misconception.)

  U. v16.1 — two code-name relabels (name-only; no predicate, no tag change):
     A17 DIRECTION_ERROR -> CARRY_FLOWS_RIGHT (the carry is carried rightward into
     the lower place, e.g. 89+78='58'); A18 SPURIOUS_CARRY -> CARRY_ADDED_NO_NEED
     (a carry added to a column that neither received nor generated one, e.g.
     30+50='90'). Also: ADDITION_PRIORS_ALL, _FREQ_TABLE and ADDITION_ERROR_NAMES
     re-sorted into ascending code order (cosmetic; dict lookups are key-based).

  V. v16.2 — _FREQ_TABLE and ADDITION_PRIORS_ALL refreshed from live v16 tagging.
     The frozen v14.7 snapshot was stale on 11 codes after the v15 rule changes
     (e.g. A04 WRONG_OP_MULTIPLICATION 3,212 -> 11,297 from the entry-S product
     routing; A22 DOUBLE_RULE_ERROR 21,789 -> 13,804). Counts and priors now
     reflect actual primary-win frequency over the 169,165-row corpus; total
     unchanged at 1527611 (frequency only moved between codes). No tag changes:
     priors feed ranked-list scoring, not the order-based cascade primary.

All other rules are unchanged from v13.

Empirical validation (v15 addition corpus, 157,786 rows / 1,368,721 freq):
  v13   → 98.41% row / 97.40% freq
  v14   → 98.57% row / 97.91% freq  (+258 rows, +6,981 freq, 0 regressions)
  v14.1 → 98.83% row / 98.15% freq  (+417 rows, +3,306 freq, 0 regressions)
  v14.2 → 99.18% row / 98.47% freq  (+544 rows, +4,452 freq, -20 rows / -42 freq)
  v14.3 → 99.18% row / 98.48% freq  (+1 row, +78 freq, 0 regressions)
  v14.4 → 99.27% row / 98.56% freq  (+139 rows, +1,071 freq, 0 regressions)
  v14.5 → 99.58% row / 98.75% freq  (+502 rows, +2,707 freq, -2 rows / -24 freq)
"""

__version__ = "17"

from dataclasses import dataclass, field
from typing import Optional, Callable

from utils import (
    parse_response, parse_operand, normalize_raw,
    digits, n_digits, digit_sum, concat_int,
    is_digit_permutation_strs,
    column_sums_units_first, carries_units_first, carries_in_units_first,
    has_any_carry, is_no_carry_problem,
    carry_dropped_all_variant, carry_dropped_one_variant_candidates,
    place_value_permutations,
    digit_position_mismatches,
    is_strict_prefix,
    right_align_digits,
)


# ---------------------------------------------------------------------------
# Corpus-derived priors (from Addition_tagged_Combined_TS_Kalika_v14_7.xlsx,
# 1,527,611 error frequency = 1,528,038 - 427 CORRECT; v14.7 tagging; sum = 1.0)
# ---------------------------------------------------------------------------

ADDITION_PRIORS_ALL: dict[str, float] = {
    "A01": 0.013681,
    "A02": 0.034403,
    "A03": 0.016903,
    "A04": 0.007395,
    "A05": 0.001811,
    "A06": 0.010683,
    "A07": 0.001529,
    "A08": 0.040994,
    "A09": 0.013988,
    "A10": 0.027631,
    "A11": 0.008994,
    "A12": 0.048063,
    "A13": 0.010249,
    "A14": 0.001576,
    "A15": 0.008699,
    "A16": 0.020440,
    "A17": 0.000286,
    "A18": 0.007278,
    "A19": 0.007071,
    "A20": 0.001492,
    "A21": 0.071602,
    "A22": 0.008991,
    "A23": 0.181724,
    "A24": 0.071762,
    "A25": 0.014629,
    "A26": 0.368126,
}

# Raw frequencies from v16 corpus tagging (Combined TS+KA+Pvt) — kept alongside priors
# so priors can be re-derived deterministically. Update both when re-tagging.
_FREQ_TABLE: dict[str, int] = {
    "A01": 20_900,
    "A02": 52_554,
    "A03": 25_821,
    "A04": 11_297,
    "A05": 2_766,
    "A06": 16_320,
    "A07": 2_335,
    "A08": 62_623,
    "A09": 21_368,
    "A10": 42_210,
    "A11": 13_740,
    "A12": 73_421,
    "A13": 15_657,
    "A14": 2_407,
    "A15": 13_289,
    "A16": 31_225,
    "A17": 437,
    "A18": 11_118,
    "A19": 10_801,
    "A20": 2_279,
    "A21": 109_380,
    "A22": 13_735,
    "A23": 277_603,
    "A24": 109_624,
    "A25": 22_348,
    "A26": 562_353,
}

_TOTAL_FREQ: int = 1_527_611


# ---------------------------------------------------------------------------
# Spec-derived error names (from Addition_Error_Rules_v13.docx, Table 0)
# ---------------------------------------------------------------------------

ADDITION_ERROR_NAMES: dict[str, str] = {
    "A01": "RANDOM_OR_INVALID",
    "A02": "INPUT_ORDERING_ERROR",
    "A03": "WRONG_OP_SUBTRACTION",
    "A04": "WRONG_OP_MULTIPLICATION",
    "A05": "WRONG_OP_DIVISION",
    "A06": "CONCAT_FORWARD",
    "A07": "CONCAT_REVERSE",
    "A08": "PARTIAL_OPERAND_COPY",
    "A09": "UNITS_ONLY_ADDITION",
    "A10": "DIGIT_SUM_STRATEGY",
    "A11": "PARTIAL_DIGIT_SUM",
    "A12": "PLACE_VALUE_ERROR",
    "A13": "CARRY_APPENDED",
    "A14": "CARRY_APPENDED_REVERSED",
    "A15": "INCOMPLETE_ANSWER_WIDTH",
    "A16": "CARRY_IGNORED",
    "A17": "CARRY_FLOWS_RIGHT",
    "A18": "CARRY_ADDED_NO_NEED",
    "A19": "CARRY_DOUBLED",
    "A20": "CARRY_RESULT_SWAP",
    "A21": "ZERO_RULE_ERROR",
    "A22": "DOUBLE_RULE_ERROR",
    "A23": "SINGLE_COLUMN_SLIP",
    "A24": "MULTI_COLUMN_SLIP",
    "A25": "INCOMPLETE_ENTRY",
    "A26": "UNCLASSIFIED_ERROR",
}


# ---------------------------------------------------------------------------
# Cascade priority order (per the spec's Firing-order document)
# ---------------------------------------------------------------------------

ADDITION_CASCADE_ORDER: list[str] = [
    "A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09",
    "A10", "A11", "A12", "A13", "A14", "A15", "A16", "A17", "A18",
    "A19", "A20", "A21", "A22", "A23", "A24", "A25", "A26",
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ClassifyResult:
    """
    Result of a classification.

    Fields:
        cascade_code: The spec-defined cascade output (top of the ranked list).
                      A code like "A20", "CORRECT", or "A26" (fallback).
        cascade_name: Human-readable error name for cascade_code (e.g.
                      "CARRY_RESULT_SWAP"). Empty string for "CORRECT".
        ranked:       List of (code, name, score) triples for ALL rules that fired,
                      ranked by score (descending). Top entry is always cascade_code.
        debug:        Optional dict with computed signals (only populated if
                      classify(..., return_debug=True)).
    """
    cascade_code: str
    cascade_name: str = ""
    ranked: list[tuple[str, str, float]] = field(default_factory=list)
    debug: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        ranked_str = ", ".join(f"{c}:{s:.3f}" for c, _, s in self.ranked)
        return (f"ClassifyResult(cascade={self.cascade_code} "
                f"({self.cascade_name}), ranked=[{ranked_str}])")


# ---------------------------------------------------------------------------
# Per-rule predicate functions
# Each takes a `signals` dict with all pre-computed inputs and returns True
# iff that rule's spec condition is satisfied.
# ---------------------------------------------------------------------------

def _rule_A01(s: dict) -> bool:
    """
    A01 RANDOM_OR_INVALID — learner answer cannot be interpreted as a valid
    whole non-negative integer. Fires if ANY of:
      (1) contains a period (.) — decimal or partial entry
      (2) cannot be parsed as integer after stripping whitespace and quotes
      (3) parsed integer < 0
    """
    return s["wi"] is None


def _rule_A02(s: dict) -> bool:
    """
    A02 INPUT_ORDERING_ERROR — correct digits in wrong order.
    Two branches (either triggers):
      (a) Parsed-integer: sorted(str(wi)) == sorted(str(correct)) AND
          len(str(wi)) == len(str(correct))
      (b) Raw-input: raw is all digits AND
          sorted(raw) == sorted(str(correct)) AND
          len(raw) == len(str(correct))
    Exclusion: A02 does NOT fire if A20 also fires (carry-result-swap takes priority).
    """
    if s["wi"] is None or s["wi"] == s["correct"]:
        return False
    correct_str = str(s["correct"])
    # Branch (a): parsed integer
    a_match = is_digit_permutation_strs(str(s["wi"]), correct_str)
    # Branch (b): raw input string
    b_match = False
    if s["raw"] is not None and s["raw"].isdigit():
        b_match = is_digit_permutation_strs(s["raw"], correct_str)
    if not (a_match or b_match):
        return False
    # v15: defer to A04 when the answer is exactly the product. 9+9='81' is
    # 9x9 AND coincidentally a digit-reversal of the sum 18; the multiplication
    # reading is preferred for these product/transposition coincidences.
    if _rule_A04(s):
        return False
    # Exclusion (A20 guard): defer to A20 if it also fires
    return not _rule_A20(s)


def _rule_A06(s: dict) -> bool:
    """
    A06 CONCAT_FORWARD: wi == int(str(N1) + str(N2)).

    Per v14 reviewer verdict (call #1, REJECTED): no zero-operand exclusion.
    7+0=70 fires A06 — the response is exactly concat(7, 0), the literal
    mechanical signature of CONCAT_FORWARD. A21 has no mechanism producing
    70 from 7+0, so A06 wins on mechanical specificity.
    """
    if s["wi"] is None: return False
    return s["wi"] == concat_int(s["n1"], s["n2"])


def _rule_A07(s: dict) -> bool:
    """
    A07 CONCAT_REVERSE: wi == int(str(N2) + str(N1)).

    Per v14 reviewer verdict (call #2, REJECTED): no zero-operand exclusion.
    Symmetric to A06 — 0+7=70 is exactly concat(7, 0), the mechanical signature
    of CONCAT_REVERSE.
    """
    if s["wi"] is None: return False
    return s["wi"] == concat_int(s["n2"], s["n1"])


def _rule_A08(s: dict) -> bool:
    """
    A08 PARTIAL_OPERAND_COPY: wi equals one operand.
    Detection: N1 != N2 AND NOT (wi == 0 AND (N1 == 0 OR N2 == 0)) AND
               (wi == N1 OR wi == N2).
    Exclusions: N1==N2 → A22; wi==0 with zero operand → A21.
    v15 (item 5): also defer to A21 whenever the zero-rule fires. An answer
    that equals an operand because a +0 column was annihilated (e.g.
    3+60='60', expected 63) is a zero-rule error, not a partial-operand copy.
    """
    if s["wi"] is None: return False
    if _rule_A21(s):
        return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if n1 == n2:
        return False
    if wi == 0 and (n1 == 0 or n2 == 0):
        return False
    return wi == n1 or wi == n2


def _rule_A09(s: dict) -> bool:
    """
    A09 UNITS_ONLY_ADDITION: wi == (N1 mod 10) + (N2 mod 10).

    Per v14 reviewer verdict (call #3, ACCEPTED in narrow form): A09 defers
    to A21 only when wi == 0 AND one operand is zero (the annihilation
    misconception "x + 0 = 0"). A09 here is a coincidental match because the
    units sum is 0; annihilation is the documented zero-rule misconception.
    Other A09 cases (e.g., 23+15=8) still fire A09.
    """
    if s["wi"] is None: return False
    if s["wi"] == 0 and (s["n1"] == 0 or s["n2"] == 0):
        return False
    return s["wi"] == (s["n1"] % 10) + (s["n2"] % 10)


def _rule_A10(s: dict) -> bool:
    """A10 DIGIT_SUM_STRATEGY: wi == digit_sum(N1) + digit_sum(N2)."""
    if s["wi"] is None: return False
    return s["wi"] == digit_sum(s["n1"]) + digit_sum(s["n2"])


def _rule_A11(s: dict) -> bool:
    """
    A11 PARTIAL_DIGIT_SUM: digit-sum reduction applied to ONE operand only.
    Variant A: wi == N1 + digit_sum(N2) AND digit_sum(N2) != N2
    Variant B: wi == digit_sum(N1) + N2 AND digit_sum(N1) != N1
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    ds1, ds2 = digit_sum(n1), digit_sum(n2)
    var_a = (wi == n1 + ds2 and ds2 != n2)
    var_b = (wi == ds1 + n2 and ds1 != n1)
    return var_a or var_b


def _rule_A12(s: dict) -> bool:
    """
    A12 PLACE_VALUE_ERROR: digit place-value mis-placement.
    Detection: NOT 1D+1D AND rules A01–A11 all failed AND wi in pvp_wrong_answers.
    The "A01–A11 failed" guard is enforced by cascade ordering, not here —
    this predicate just checks the candidate-set membership.

    Exclusion (carry-priority guard): if the answer also matches A20
    CARRY_RESULT_SWAP, A12 defers — the carry misconception is the more
    fundamental diagnosis (parallel to A02's A20 deferral).
    """
    if s["wi"] is None: return False
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    if s["wi"] not in s["pvp_candidates"]:
        return False
    # v15: defer to A04 when the answer is exactly the product. e.g. 11+2='22'
    # is 11x2 — multiplication, not a place-value permutation of the sum 13.
    if _rule_A04(s):
        return False
    # A20 deferral
    return not _rule_A20(s)


def _rule_A13(s: dict) -> bool:
    """
    A13 CARRY_APPENDED: column sums concatenated MSB-first (no carrying).
    Detection: at least one NON-LEFTMOST column sum >= 10 AND
               wi == int(concat of col_sums as strings, MSB-first).
    """
    if s["wi"] is None: return False
    cs = s["col_sums"]                           # units-first
    if len(cs) <= 1: return False
    # Non-leftmost column sum >= 10 means: any column except the LAST (leftmost) has >=10
    non_leftmost = cs[:-1]
    if not any(c >= 10 for c in non_leftmost):
        return False
    # Concatenate MSB-first
    msb_first = list(reversed(cs))
    parts = [str(c) for c in msb_first]
    return s["wi"] == int("".join(parts))


def _rule_A14(s: dict) -> bool:
    """
    A14 CARRY_APPENDED_REVERSED: column sums concatenated UNITS-first.
    Detection: at least one non-leftmost col sum >= 10 AND
               wi == int(concat of col_sums as strings, units-first).
    """
    if s["wi"] is None: return False
    cs = s["col_sums"]
    if len(cs) <= 1: return False
    if not any(c >= 10 for c in cs[:-1]):
        return False
    parts = [str(c) for c in cs]                 # units-first concat
    return s["wi"] == int("".join(parts))


def _rule_A16(s: dict) -> bool:
    """
    A16 CARRY_IGNORED: two variants.
    Variant A: each column sum mod 10 written; leftmost writes full sum.
    Variant B: exactly ONE column's carry-out dropped, others propagate normally.
              Requires >=2 real carries in the problem to make "selectively
              drop one" meaningful — single-carry problems where dropping the
              one carry yields a leading-drop are A15 territory.

    v14.7: Reverted v14.6's predicate-level gate. Both A16 and A15 patterns
    are now reported as markers independently; cascade order (A15 before A16)
    handles which one becomes Final_Error_Code when both fire. Overlap cases
    (e.g. 89+78='67') now show A16=1 AND A15=1 in markers, with Final=A15.
    See ADDITION_CASCADE_ORDER for the priority.

    OLD NOTE (now obsolete): Defers to A15 when the problem creates a new leading digit
    (Lc == max_op_len + 1) AND the kid's answer is the units-portion of
    correct (wi == correct % 10^max_op_len). This pattern is cognitively
    "kid didn't extend the answer to the new place value" — A15's story —
    regardless of how many carries the problem has. Other A16 patterns
    that happen to occur in width-expanding problems (e.g. kid wrote the
    leading digit but mishandled interior carry propagation, like
    89+78='157') still fire A16 because the kid HAS engaged with the new
    leading column, just with broken column-sum mechanics.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    # Variant A
    var_a = carry_dropped_all_variant(s["n1"], s["n2"])
    if var_a is not None and s["wi"] == var_a and var_a != s["correct"]:
        return True
    # Variant B — only meaningful with >=2 real carries
    n_real_carries = sum(s["carries"])
    if n_real_carries >= 2:
        if s["wi"] in s["carry_drop_one_candidates"] and s["wi"] != s["correct"]:
            return True
    return False


def _rule_A17(s: dict) -> bool:
    """
    A17 CARRY_FLOWS_RIGHT: L-to-R column addition with carry flowing rightward.
    Detection: NOT 1D+1D AND simulated L-to-R sum (carry = sum//10 flows right,
                final carry lost) matches wi.
    """
    if s["wi"] is None: return False
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False

    cs = s["col_sums"]                           # units-first
    cs_msb = list(reversed(cs))                  # MSB-first
    out_digits_msb = []
    carry_in = 0
    for col_sum in cs_msb:
        total = col_sum + carry_in
        out_digits_msb.append(total % 10)
        carry_in = total // 10
    # Final carry is LOST per spec (no place to write it)
    answer_str = "".join(str(d) for d in out_digits_msb)
    if not answer_str: return False
    answer = int(answer_str)
    return s["wi"] == answer and answer != s["correct"]


def _rule_A18(s: dict) -> bool:
    """
    A18 CARRY_ADDED_NO_NEED: phantom +1 in a column with no carry context.
    Detection: NOT 1D+1D AND wi == correct + 10^k (k >= 1) AND
               (wi mod 10^k) == (correct mod 10^k)  — low digits match AND
               carry_in at column k == 0 AND
               digit_N1[k] + digit_N2[k] < 10
    Note (v14.1): wi may be one digit WIDER than correct when the phantom
    carry is added to a column where correct's digit is 9 (creates a new
    leading digit). E.g. 415+550=1065 (correct 965, diff 100, k=2):
    correct's hundreds digit 9 plus the phantom 1 carries over to a new
    thousands digit. The arithmetic check below handles this uniformly
    without an explicit length compare.
    """
    if s["wi"] is None: return False
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    diff = s["wi"] - s["correct"]
    if diff <= 0:
        return False
    # diff must be exactly 10^k for some k >= 1
    width = n_digits(s["correct"])
    cs = s["col_sums"]
    carries_in = s["carries_in"]
    # Allow k up to and INCLUDING width (the leftmost column case where
    # the phantom carry creates a new leading digit).
    for k in range(1, width + 1):
        if diff != 10 ** k:
            continue
        # Low digits of wi must match low digits of correct
        if s["wi"] % (10 ** k) != s["correct"] % (10 ** k):
            continue
        # carry_in at column k must be 0 (if column k exists in the
        # operand stack; if k is beyond the stack, there's no real carry
        # context by definition).
        if k < len(carries_in) and carries_in[k] != 0:
            continue
        # col_sum at column k must be < 10 (if column k exists in the
        # operand stack; beyond the stack, col_sum is effectively 0).
        if k < len(cs) and cs[k] >= 10:
            continue
        return True
    return False


def _rule_A19(s: dict) -> bool:
    """
    A19 CARRY_DOUBLED: incoming carry of 1 added twice.
    Detection: NOT 1D+1D AND wi == correct + 10^k (k >= 1) AND
               all digits at positions 0..k-1 match correct AND
               carry_in at column k > 0
    """
    if s["wi"] is None: return False
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    diff = s["wi"] - s["correct"]
    if diff <= 0:
        return False
    width = n_digits(s["correct"])
    carries_in = s["carries_in"]
    # v14.1: same arithmetic comparison as A18 — allow k up to width
    # inclusive so cases like 19+71=100 (doubled carry creates a new
    # leading digit) are caught. correct=90, wi=100, diff=10=10^1; the
    # tens column has carries_in=1, so the doubled carry would add
    # another 1 there, resulting in 10 at tens → write 0, carry 1 to a
    # new hundreds position, producing 100. The old length check
    # rejected this; the new check just verifies low digits match.
    for k in range(1, width + 1):
        if diff != 10 ** k:
            continue
        if s["wi"] % (10 ** k) != s["correct"] % (10 ** k):
            continue
        # carry_in at column k must be > 0 (a real carry to double)
        if k >= len(carries_in) or carries_in[k] == 0:
            continue
        return True
    return False


def _rule_A20(s: dict) -> bool:
    """
    A20 CARRY_RESULT_SWAP: in a non-leftmost column where sum >= 10, learner
    writes the carry digit and propagates the units digit (swapped roles).
    Detection: for each non-leftmost col with col_sum = 10*c + u, the swapped
    version writes c and carries u; wi matches result of EXACTLY ONE such swap.
    """
    if s["wi"] is None or s["wi"] == s["correct"]:
        return False
    cs = s["col_sums"]                           # units-first
    if len(cs) <= 1: return False

    matches = 0
    # For each non-leftmost column k (i.e., k < len(cs)-1) where col_sum >= 10
    for k in range(len(cs) - 1):
        if cs[k] < 10:
            continue
        # Compute the swapped variant
        out_digits_units_first: list[int] = []
        carry_in = 0
        for i, col_sum in enumerate(cs):
            total = col_sum + carry_in
            if i == k:
                # SWAP: write tens-digit, carry units-digit
                out_digits_units_first.append(total // 10)
                carry_in = total % 10
            else:
                if total >= 10:
                    out_digits_units_first.append(total % 10)
                    carry_in = total // 10
                else:
                    out_digits_units_first.append(total)
                    carry_in = 0
        if carry_in > 0:
            out_digits_units_first.append(carry_in)
        parts = [str(d) for d in reversed(out_digits_units_first)]
        candidate = int("".join(parts)) if parts else 0
        if candidate == s["wi"]:
            matches += 1
    return matches >= 1


def _rule_A21(s: dict) -> bool:
    """
    A21 ZERO_RULE_ERROR — three tiers (any matches).

    Tier 1 (whole-operand zero): (n1 == 0 OR n2 == 0) AND wi != correct.
    Tier 2 (column-level zero):
        len(str(wi)) == len(str(correct)) AND
        ALL mismatched digit positions are zero-containing columns AND
        for each wrong column:
            if carry_in == 0: any wrong value qualifies
            if carry_in > 0:  only when learner wrote 0 (zero-rule with carry reset)
    Tier 3 (units-column 0+0 skip):
        n1 % 10 == 0 AND n2 % 10 == 0 AND correct >= 100 AND
        len(str(wi)) == len(str(correct)) - 1 AND
        wi == correct // 10 AND correct % 10 == 0
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]

    # v15 (entry S): exact-product wins. When the answer is exactly n1*n2 the
    # multiplication reading is preferred over the zero-rule reading, e.g.
    # 8+10='80' (=8x10), 10+8='80' -> A04, not a zero-placement error.
    if _rule_A04(s):
        return False

    # --- v16.1: compound double+zero is a zero-rule failure (primary) ---
    # When a width-guarded trace reproduces wi using BOTH a doubling rule AND a
    # +0 annihilation (signals["zero_compound"], from _compound_double_zero_traces),
    # the zero-rule identity genuinely failed in this answer, so A21 fires. Since
    # A21 precedes A22 in the cascade, A21 becomes the Final code and A22 (which
    # still fires via its own a18_sim path) drops to a marker — the deliberate
    # inverse of v15/v16, where A22 was Final and A21 the marker (Akshay's call:
    # the zero rule is the headline misconception when both co-occur, matching
    # subtraction S26). Lower-numbered codes (A04 above, A08, A12, ...) still win
    # if they fire, so this never overrides a more specific diagnosis. Example:
    # 201+292='203' (tens 0+9 written 0 = zero-rule; hundreds 2+2 written 2 =
    # double-rule) -> Final A21, markers A21+A22.
    if s.get("zero_compound"):
        return True

    # --- Tier 1 ---
    if (n1 == 0 or n2 == 0) and wi != correct:
        return True

    # --- Tier 3 ---
    if (n1 % 10 == 0 and n2 % 10 == 0 and correct >= 100
            and n_digits(wi) == n_digits(correct) - 1
            and wi == correct // 10
            and correct % 10 == 0):
        return True

    # --- Tier 2 ---
    # FIX (v14): padding zeros that lie BEYOND the operand stack
    # (i.e., at column i >= max(n_digits(n1), n_digits(n2))) are NOT
    # cognitively part of the problem and must not count as zero columns.
    # The original code padded operand-digit arrays to match `correct`'s
    # width, and then read those padding zeros as real — causing A21 to
    # fire on cases like 9+9=88 where neither operand has any zero anywhere.
    # Padding within the operand stack (e.g., 21's implicit 0 at hundreds in
    # 21+328) is preserved as a real "0" because the kid does right-align
    # the shorter operand against the wider one.
    max_op_width = max(n_digits(n1), n_digits(n2))
    if n_digits(wi) == n_digits(correct):
        # Right-aligned digits, units-first comparison
        wi_units = str(wi)[::-1]
        correct_units = str(correct)[::-1]
        d1, d2 = right_align_digits(n1, n2)
        d1_units = list(reversed(d1))
        d2_units = list(reversed(d2))
        carries_in = s["carries_in"]
        # Pad operand-digit lists if wi/correct are wider than operand stack
        while len(d1_units) < len(correct_units):
            d1_units.append(0)
            d2_units.append(0)
        while len(carries_in) < len(correct_units):
            carries_in = list(carries_in) + [0]

        any_mismatch = False
        all_zero_col = True
        for i in range(len(correct_units)):
            if wi_units[i] == correct_units[i]:
                continue
            any_mismatch = True
            # Mismatched column: zero-col only if WITHIN the operand stack
            within_stack = (i < max_op_width)
            is_zero_col = within_stack and (d1_units[i] == 0 or d2_units[i] == 0)
            if not is_zero_col:
                all_zero_col = False
                break
            cin = carries_in[i] if i < len(carries_in) else 0
            if cin == 0:
                pass
            else:
                if wi_units[i] != "0":
                    all_zero_col = False
                    break

        if any_mismatch and all_zero_col:
            return True

    return False


def _compound_double_zero_traces(n1: int, n2: int, wi: Optional[int],
                                 correct: int) -> tuple[bool, bool]:
    """
    v15 (items 1/2/4): width-guarded compound zero/double simulator.

    Searches per-column traces that reproduce `wi` exactly, where each column
    may take one of: normal arithmetic; a double variant A/B/C/D (write d / 0 /
    d+carry / carry, always suppressing carry_out) at a column where the two
    operand digits are equal and non-zero; or a +0 annihilation (write 0,
    suppress carry) at a column where exactly one operand digit is zero.

    Returns (a18_sim, zero_compound):
      a18_sim       — a reproducing trace exists that uses >=1 double rule AND
                      (>=2 special columns OR a doubled digit x>=5). This is the
                      A22 simulation firing condition (item 2).
      zero_compound — a reproducing trace exists that uses BOTH >=1 double rule
                      AND >=1 +0 annihilation (the compound double+zero pattern
                      that earns an A21 marker, item 4).

    Mandatory width guard: only traces with n_digits(wi) == n_digits(correct)
    are admitted. Without it the search would admit width-collapsing answers
    (5+55='0', 9+99='0') that satisfy "uses a rule" but represent
    non-engagement, not a misconception.
    """
    if wi is None:
        return (False, False)
    if n_digits(wi) != n_digits(correct):          # width guard
        return (False, False)
    # v15: an answer equal to an operand (n1 != n2) is an A08 partial-operand
    # copy; any doubling/zero trace that reproduces it is coincidental, so the
    # simulator declines (keeps A08 rows clean of spurious A22/A21 markers).
    # n1 == n2 is exempt — there A08 never fires and x+x=x is the real story.
    if n1 != n2 and (wi == n1 or wi == n2):
        return (False, False)

    d1, d2 = right_align_digits(n1, n2)
    d1u = list(reversed(d1))
    d2u = list(reversed(d2))
    width = len(d1u)

    # Pre-gate: need at least one special-capable column, else nothing to do.
    has_special = any(
        (d1u[i] == d2u[i] and d1u[i] != 0) or ((d1u[i] == 0) != (d2u[i] == 0))
        for i in range(width)
    )
    if not has_special:
        return (False, False)

    found = {"a18": False, "zero": False}
    cap = {"n": 0}
    NODE_CAP = 20000

    def dfs(i: int, carry: int, units: list[int],
            n_double: int, n_special: int, max_dx: int, used_zero: bool) -> None:
        if found["a18"] and found["zero"]:
            return
        cap["n"] += 1
        if cap["n"] > NODE_CAP:
            return
        if i == width:
            digs = list(units)
            c = carry
            while c > 0:
                digs.append(c % 10)
                c //= 10
            if not digs:
                digs = [0]
            sim_int = int("".join(str(x) for x in reversed(digs)))
            if sim_int == wi and n_double >= 1:
                if n_special >= 2 or max_dx >= 5:
                    found["a18"] = True
                if used_zero:
                    found["zero"] = True
            return

        d1i, d2i = d1u[i], d2u[i]

        # Move 1 — normal arithmetic (always available).
        total = d1i + d2i + carry
        dfs(i + 1, total // 10, units + [total % 10],
            n_double, n_special, max_dx, used_zero)

        # Move 2 — double variants. v15: only the "write the doubled digit"
        # family survives — A (write d) and C (write d+carry). The "=0" family
        # (B: write 0, D: write carry) was dropped: x+x ends in 0 only at x=5,
        # so writing 0 at a doubled column is subtraction (x-x=0) — routed to
        # A03 — or, at x=5, a dropped carry (A16), never a doubling misconception.
        if d1i == d2i and d1i != 0:
            d = d1i
            for vdig in (d, d + carry):           # variants A, C only
                if 0 <= vdig <= 9:
                    dfs(i + 1, 0, units + [vdig],
                        n_double + 1, n_special + 1, max(max_dx, d), used_zero)

        # Move 3 — +0 annihilation (exactly one operand digit is zero).
        if (d1i == 0) != (d2i == 0):
            dfs(i + 1, 0, units + [0],
                n_double, n_special + 1, max_dx, True)

    dfs(0, 0, [], 0, 0, 0, False)
    return (found["a18"], found["zero"])


def _single_double_addend_le4(n1: int, n2: int, wi: Optional[int],
                              correct: int) -> bool:
    """
    v15 (item 7, adopted): a single doubled column with x<5 where the learner
    wrote the ADDEND ("x+x=x", variant A) and every other column is correct.

    For x<5 the column never carries (2+2=4, 4+4=8), so "wrote x instead of 2x"
    is arithmetically indistinguishable from a single-column slip by carry
    behaviour — but writing exactly the addend at an x+x column is the doubling
    signature, so the pedagogy call (Akshay) is to tag these A22. Examples:
    21+328='329' (2+2->2), 6954+324='7274' (4+4->4 at units).

    Guarded against partial-operand copies: if wi equals an operand, the answer
    is an A08 copy that only coincidentally matches this trace (e.g. 30+31='31'
    where 31 IS n2), so this path declines and A08 keeps the row.
    """
    if wi is None:
        return False
    if n_digits(wi) != n_digits(correct):          # width guard
        return False
    if wi == n1 or wi == n2:                        # operand copy -> leave to A08
        return False
    d1, d2 = right_align_digits(n1, n2)
    d1u = list(reversed(d1))
    d2u = list(reversed(d2))
    width = len(d1u)
    doubles = [i for i in range(width) if d1u[i] == d2u[i] and d1u[i] != 0]
    if len(doubles) != 1:                           # exactly one doubled column
        return False
    col = doubles[0]
    x = d1u[col]
    if x >= 5:                                       # x>=5 is handled by the simulator
        return False
    # Simulate: variant A at the doubled column (write x, suppress carry),
    # normal arithmetic everywhere else; require an exact reproduction of wi.
    carry = 0
    sim: list[int] = []
    for i in range(width):
        if i == col:
            sim.append(x)
            carry = 0
        else:
            total = d1u[i] + d2u[i] + carry
            sim.append(total % 10)
            carry = total // 10
    if carry > 0:
        sim.append(carry)
    sim_int = int("".join(str(d) for d in reversed(sim))) if sim else 0
    return sim_int == wi


def _rule_A22(s: dict) -> bool:
    """
    A22 DOUBLE_RULE_ERROR — x+x=x in double columns (the "write the
    doubled digit" misconception).

    Surviving variants (v15 dropped the "=0" family B/D):
      (A) x+x=x, ignore carry_in: write d, carry_out = 0
      (C) x+x=x, absorb carry_in: write d+c, carry_out = 0
    Dropped (v15): (B) x+x=0 and (D) x+x=0+carry. x+x ends in 0 only at x=5,
      so "wrote 0 at a doubled column" is never a doubling misconception:
      it is subtraction (x-x=0, -> A03) or, at x=5, a dropped carry (-> A16).
    Extension: same-length wi, double-cols match variant-expected, non-double
      cols can have ANY wrong value (per spec).
    Shorter-wi extensions:
      Subcase (ii): wi_len == # double cols AND wi == concat of variant-expected
      Subcase (iii): wi_len == 1 AND wi equals variant-expected at ANY single double col
    Exclusions (LEGACY variant paths only — the v15 sim path below can override):
      - 0+0 columns NOT treated as doubles
      - In the legacy variant logic, doubles where x>=5 fire only for
        EQUAL-WIDTH operands (since v14.2 Fix H); unequal-width x>=5 doubles
        were treated as coincidental right-alignment.
    v15 (item 2): A22 also fires via a width-guarded compound simulation path
    (signals["a18_sim"], computed by _compound_double_zero_traces) — see the
    early `if s.get("a18_sim")` check below. IMPORTANT: this path is a
    deliberate reversal of the legacy x>=5 unequal-width exclusion above. When
    a full per-column trace EXACTLY reproduces wi using >=1 double rule and
    (>=2 special columns OR a doubled digit x>=5), A22 fires regardless of
    operand widths (e.g. 7+27='20' 7+7->0, 89+9='80' 9+9->0, 998+88='1078'
    8+8->8). The exact-reproduction + width-guard requirements make this a
    stronger test than the old "coincidental match at one column", so the
    blanket unequal-width veto is no longer warranted. v15 (item 7) additionally
    fires on a single x<5 doubled column written as the addend (see
    _single_double_addend_le4). All legacy variant logic below is unchanged.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct:
        return False

    # v15 (item 2): width-guarded compound double/zero simulation path.
    # Checked here, before the double_cols early-returns below, so it can
    # fire on cases the legacy paths skip (unequal-width / x>=5 / multi-double).
    if s.get("a18_sim"):
        return True

    d1, d2 = right_align_digits(n1, n2)
    d1_units = list(reversed(d1))
    d2_units = list(reversed(d2))
    width = len(d1_units)
    # Identify double-column indices (units-first), excluding only 0+0.
    # v14.1: refined guard — x>=5 fires A22 only when operands have equal
    # widths. Unequal-width cases (e.g. 9+99=109) are tagged as slips by
    # the corpus, not A22, because the shorter operand's "doubled" column
    # is only a coincidence of right-alignment (the kid doesn't see two
    # equally-prominent x's). For x<5 the guard doesn't matter
    # cognitively, so we let it fire in any width configuration.
    # (width==1 implies equal widths, so this subsumes v14 Fix A.)
    equal_widths = (n_digits(n1) == n_digits(n2))
    double_cols = [i for i in range(width)
                   if d1_units[i] == d2_units[i]
                   and d1_units[i] != 0
                   and (d1_units[i] < 5 or equal_widths)]
    if not double_cols:
        return False

    correct_units = str(correct)[::-1]
    carries_in = s["carries_in"]
    while len(carries_in) < len(correct_units):
        carries_in = list(carries_in) + [0]

    # For each variant, compute the expected per-column digit at each double col
    # and check if wi matches under the same-length OR shorter-length subcases.
    def variant_expected_at(i: int, variant: str) -> int:
        d = d1_units[i]
        c = carries_in[i] if i < len(carries_in) else 0
        if variant == "A": return d
        if variant == "B": return 0
        if variant == "C": return d + c
        if variant == "D": return c
        return -1  # unreachable

    # Same-length wi: check every variant.
    # v14.3: defer to A23 mode (c) "boundary slip" when |wi - correct| == 1
    # with exactly 2 digit mismatches.
    # v14.4: variants C and D fire only if sim == wi.
    # v14.5 Fix K: require operand widths to be equal. Audit revealed
    # ~2,100 freq of FP1+FP3 (sheet=A24 or A23) and ~900 freq of FP2
    # (sheet=A26) are unequal-width problems where variants A or B
    # coincidentally match at one doubled column. The corpus contains
    # ZERO sheet-A22 same-length cases with unequal widths — making
    # this restriction strictly net-positive.
    # v14.5 Fix L: variants C and D simulation uses PROPAGATED carry
    # (variant sets carry_out=0 at each doubled col), not the natural
    # carries_in. Fixes 26+26=36 (variant C predicts 6 at units, then 2
    # at tens under propagated carry — sim=26, wi=36, reject) while
    # preserving 29+28=37 (variant C at tens predicts 3 from natural
    # carry 1 — sim=37, wi=37, fire).
    # (v15 housekeeping: `equal_widths` already computed above for double_cols;
    # the duplicate assignment that used to sit here was removed.)
    if (n_digits(wi) == n_digits(correct) and width >= 2 and equal_widths):
        is_boundary_slip = (
            abs(wi - correct) == 1
            and digit_position_mismatches(wi, correct) == 2
        )
        if not is_boundary_slip:
            wi_units = str(wi)[::-1]
            for variant in "AC":   # v15: B/D (x+x=0) dropped
                if variant in "AB":
                    # Permissive per-col check (no carry context needed)
                    ok = True
                    for i in double_cols:
                        expected = variant_expected_at(i, variant)
                        if expected < 0 or expected > 9:
                            ok = False; break
                        if int(wi_units[i]) != expected:
                            ok = False; break
                    if ok:
                        return True
                else:  # variants C, D — strict simulation with propagated carry
                    sim_units: list[int] = []
                    carry = 0
                    valid = True
                    for i in range(width):
                        if i in double_cols:
                            d = d1_units[i]
                            exp = (d + carry) if variant == 'C' else carry
                            if exp < 0 or exp > 9:
                                valid = False; break
                            sim_units.append(exp)
                            carry = 0
                        else:
                            total = (d1_units[i] + d2_units[i]) + carry
                            sim_units.append(total % 10)
                            carry = total // 10
                    if not valid:
                        continue
                    if carry > 0:
                        sim_units.append(carry)
                    sim_int = int("".join(str(x) for x in reversed(sim_units))) if sim_units else 0
                    if sim_int == wi:
                        return True

    # Shorter-wi subcase (ii): wi corresponds to a per-column variant
    # application at EVERY column (n_double == width). We accept wi values
    # narrower than the column count if the missing leading digits would
    # have been zeros (e.g., 22+22=0 written as "00", which parses to 0).
    # v14.5: variants C and D use propagated carry (consistent with the
    # same-length subcase's Fix L). Variants A and B remain carry-
    # independent so this only affects multi-doubled-col cases.
    n_double = len(double_cols)
    if n_double == width and n_digits(wi) <= n_double:
        wi_units = str(wi)[::-1]
        wi_units_padded = wi_units + '0' * (n_double - len(wi_units))
        sorted_doubles = sorted(double_cols)
        for variant in "AC":   # v15: B/D (x+x=0) dropped
            ok = True
            propagated_carry = 0
            for idx, col in enumerate(sorted_doubles):
                if variant in "AB":
                    expected = variant_expected_at(col, variant)
                else:  # C, D — use propagated carry
                    d = d1_units[col]
                    expected = (d + propagated_carry) if variant == 'C' else propagated_carry
                if expected < 0 or expected > 9:
                    ok = False; break
                if int(wi_units_padded[idx]) != expected:
                    ok = False; break
                # Variant sets carry_out = 0 at the doubled col
                propagated_carry = 0
            if ok:
                return True

    # Shorter-wi subcase (iii) — restricted form (v14).
    # Original subcase (iii) fired whenever a single-digit wi matched a
    # variant-expected value at ANY doubled column. That over-fired on
    # 21+328=0 type cases (operands of unequal width; the doubled col
    # is buried inside the wider operand; single-digit wi is implausible
    # as "applied rule once").
    # Restricted firing condition (any of):
    #   (a) the units column is among the doubled columns — captures
    #       "kid applied rule at units and stopped" (e.g. 64+34=0).
    #   (b) the operands have equal width — captures "kid applied rule at
    #       the only doubled column among equally-wide operands"
    #       (e.g. 30+31=3, 26+26=0, 201+292=0).
    # The combined restriction excludes only the unequal-width / non-units
    # case (21+328=0), which is where the original over-firing happened.
    if n_digits(wi) == 1:
        units_doubled = 0 in double_cols
        equal_width = n_digits(n1) == n_digits(n2)
        if units_doubled or equal_width:
            for col in double_cols:
                for variant in "AC":   # v15: B/D (x+x=0) dropped
                    expected = variant_expected_at(col, variant)
                    if 0 <= expected <= 9 and wi == expected:
                        return True

    return False


def _rule_A23(s: dict) -> bool:
    """
    A23 SINGLE_COLUMN_SLIP — single arithmetic mistake.
    Three modes:
      (a) 1D+1D: |correct - wi| <= 5
      (b) Multi-digit: same length AND exactly 1 digit-position mismatch
      (c) Boundary slip: same length AND exactly 2 mismatches AND |diff| == 1
    """
    if s["wi"] is None or s["wi"] == s["correct"]:
        return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]

    # v15 (item 6 + entry S): an answer equal to exactly n1*n2 is a wrong-
    # operation error, not a slip — defer to A04 across ALL modes (e.g. 2+3='6',
    # 3+4='12' in 1D+1D; 32+2='64' = 32x2 in multi-digit, far from the sum 34).
    # Implemented as defer-to-A04 (not a bare wi != n1*n2) so products that fail
    # A04's guards (e.g. n1==n2 below the A04 floor) stay A23 rather than fall
    # through to A26.
    if _rule_A04(s):
        return False

    # Mode (a): 1D+1D
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return abs(correct - wi) <= 5

    # Modes (b) and (c) require same length
    if n_digits(wi) != n_digits(correct):
        return False
    mismatches = digit_position_mismatches(wi, correct)
    if mismatches == 1:
        return True
    if mismatches == 2 and abs(wi - correct) == 1:
        return True
    return False


def _rule_A24(s: dict) -> bool:
    """
    A24 MULTI_COLUMN_SLIP — restricted to NO-CARRY problems with 2+ mismatches.
    Detection: NOT 1D+1D AND len(wi) == len(correct) AND
               digit_position_mismatches >= 2 AND
               every column sum < 10 (no-carry problem).
    Carry-required problems with 2+ mismatches fall to A26 per spec.
    """
    if s["wi"] is None or s["wi"] == s["correct"]:
        return False
    n1, n2 = s["n1"], s["n2"]
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if n_digits(s["wi"]) != n_digits(s["correct"]):
        return False
    if not is_no_carry_problem(n1, n2):
        return False
    # v15: defer to A04 when the answer is exactly the product. e.g. 13+6='78'
    # is 13x6 (far from the sum 19) — multiplication, not a multi-column slip.
    if _rule_A04(s):
        return False
    return digit_position_mismatches(s["wi"], s["correct"]) >= 2


def _rule_A15(s: dict) -> bool:
    """
    A15 INCOMPLETE_ANSWER_WIDTH — answer is correct with one digit removed.
    Requires: len(str(correct)) == max(len(str(n1)), len(str(n2))) + 1.
    Three branches:
      (a) Leading-drop integer: wi == correct % 10^max_operand_len
      (b) Leading-drop raw: raw_input == str(correct)[1:]
      (c) Trailing-drop, 1D+1D only: wi == correct // 10

    v14.7: A15 sits above A16 in ADDITION_CASCADE_ORDER, so when both
    patterns match the same row (e.g. 89+78='67' matches A16's "selective
    carry drop" AND A15's branch (a)), A15 wins cascade priority while
    both markers remain True. This preserves A16's pattern-matching signal
    in the marker column while routing the more cognitively-specific
    diagnosis (didn't extend to new place value) to Final_Error_Code.
    Cognitive story: kid did the column arithmetic but didn't realize the
    answer extends into a new place value column — they wrote the
    "operand-width portion" of the result and stopped. Differentiated
    remediation: teach that when the leftmost column produces a carry-out,
    that carry BECOMES a new place value in the answer (the answer is
    wider than the operands by exactly one digit).

    History: v14.6 attempted the same goal via predicate-level gate in
    _rule_A16; v14.7 moved that decision into cascade order so marker
    columns honestly reflect "all patterns matched" rather than "the
    pattern chosen as final."
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    max_op_len = max(n_digits(n1), n_digits(n2))
    if n_digits(correct) != max_op_len + 1:
        return False

    # Branch (a)
    if wi == correct % (10 ** max_op_len):
        return True
    # Branch (b)
    if s["raw"] is not None and s["raw"] == str(correct)[1:]:
        return True
    # Branch (c) — 1D+1D only
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        if wi == correct // 10 and correct >= 10:
            return True
    return False


def _rule_A03(s: dict) -> bool:
    """
    A03 WRONG_OP_SUBTRACTION — learner subtracted instead.

    Two paths:
      (1) Unequal operands: wi == |N1 - N2| AND wi != correct AND
          N1 > 1 AND N2 > 1 AND N1 != N2 AND wi != N1 AND wi != N2 AND wi > 0.
      (2) v15 — equal operands written as zero: N1 == N2 AND wi == 0.
          "Wrote 0 on two equal operands" is x-x=0 (e.g. 1+1='0', 3+3='0',
          9+9='0', 123+123='0'). This is the home for the dropped A22 x+x=0
          family on equal operands — there is no doubling story, only
          subtraction-to-zero. No N1>1 guard here: 1+1='0' is 1-1=0.

    Deferrals: to A09/A10/A11 (more-specific procedural patterns), and — v15 —
    to A16 (carry-ignore). The A16 deferral replaces the old defer-to-A22 (Fix
    M) for the carry-drop family: now that A22 no longer fires for x+x=0, a
    coincidental |N1-N2| match that is really a dropped carry (e.g. 5+55='50':
    5+5=10 write 0, tens carry dropped -> '50' == |55-5|) stays A16, and at
    x=5 the column-zero reading (5+5='0') prefers carry-ignore when A16 fits.
    A22 (now the "write the doubled digit" family only) is still deferred to.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False

    # Path (2): equal-operands subtraction-to-zero.
    if n1 == n2 and n1 >= 1 and wi == 0:
        # Yield to the SAME more-specific diagnoses the general path below
        # defers to (A09/A10/A11 procedural, A16 carry-ignore, A22 doubling),
        # plus A15 incomplete-width — so e.g. 20+20='0' reads as units-only
        # (A09) and 5+5='0' as incomplete-width (A15), not subtraction. Only
        # equal operands with no such reading (x != 5, units sum != 0, e.g.
        # 9+9='0', 3+3='0', 1+1='0') are genuine x-x=0 subtraction.
        if (_rule_A09(s) or _rule_A10(s) or _rule_A11(s)
                or _rule_A16(s) or _rule_A22(s) or _rule_A15(s)):
            return False
        return True

    # Path (1): general unequal-operand subtraction.
    if n1 <= 1 or n2 <= 1: return False
    if n1 == n2: return False
    if wi <= 0: return False
    if wi == n1 or wi == n2: return False
    if wi != abs(n1 - n2): return False
    # Defer to more-specific procedural patterns
    if _rule_A09(s) or _rule_A10(s) or _rule_A11(s):
        return False
    # v15: defer to A16 (carry-ignore) — keeps the carry-drop family (e.g.
    # 5+55='50') as A16 now that A22 no longer fires for x+x=0. Also still
    # defer to A22 (the surviving "write the doubled digit" family).
    if _rule_A16(s) or _rule_A22(s):
        return False
    return True


def _rule_A04(s: dict) -> bool:
    """
    A04 WRONG_OP_MULTIPLICATION — learner multiplied instead of added.
    Detection: wi == N1 * N2 AND wi != correct AND
               N1 > 1 AND N2 > 1 AND wi != N1 AND wi != N2

    v15: the old N1 != N2 guard was removed. Equal operands written as their
    product are still multiplication (e.g. 5+5='25'=5x5, 4+4='16', 9+9='81',
    26+26='676'); the 2+2='4' coincidence is caught by the wi != correct guard
    (2x2 == 2+2). For 1D+1D this combines with item 6 (A23 mode (a) defers to
    A04), so 3+3='9' (=3x3) joins 2+3='6' as a product rather than a slip.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if n1 <= 1 or n2 <= 1: return False
    if wi == n1 or wi == n2: return False
    if wi == correct: return False
    return wi == n1 * n2


def _rule_A05(s: dict) -> bool:
    """
    A05 WRONG_OP_DIVISION — exact division only.
    Detection: wi == max(N1,N2) // min(N1,N2) AND
               max(N1,N2) mod min(N1,N2) == 0 AND wi != correct AND
               N1 > 1 AND N2 > 1 AND N1 != N2 AND
               wi != N1 AND wi != N2 AND wi > 1
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if n1 <= 1 or n2 <= 1: return False
    if n1 == n2: return False
    if wi <= 1: return False
    if wi == n1 or wi == n2: return False
    if wi == correct: return False
    big, small = max(n1, n2), min(n1, n2)
    if big % small != 0:
        return False
    return wi == big // small


def _rule_A25(s: dict) -> bool:
    """
    A25 INCOMPLETE_ENTRY — wi is leading-prefix of correct (UX artefact).
    Detection: len(str(wi)) < len(str(correct)) AND
               str(correct) starts with str(wi)
    """
    if s["wi"] is None: return False
    return is_strict_prefix(s["wi"], s["correct"])


def _rule_A26(s: dict) -> bool:
    """A26 UNCLASSIFIED_ERROR — fallback. Always fires if wi is parseable and != correct."""
    return s["wi"] is not None and s["wi"] != s["correct"]


# Predicate registry
_PREDICATES: dict[str, Callable[[dict], bool]] = {
    "A01": _rule_A01, "A02": _rule_A02, "A06": _rule_A06, "A07": _rule_A07,
    "A08": _rule_A08, "A09": _rule_A09, "A10": _rule_A10, "A11": _rule_A11,
    "A12": _rule_A12, "A13": _rule_A13, "A14": _rule_A14, "A16": _rule_A16,
    "A17": _rule_A17, "A18": _rule_A18, "A19": _rule_A19, "A20": _rule_A20,
    "A21": _rule_A21, "A22": _rule_A22, "A23": _rule_A23, "A24": _rule_A24,
    "A15": _rule_A15, "A03": _rule_A03, "A04": _rule_A04, "A05": _rule_A05,
    "A25": _rule_A25, "A26": _rule_A26,
}


# ---------------------------------------------------------------------------
# Cascade traversal
# ---------------------------------------------------------------------------

def _cascade_first_match(signals: dict) -> str:
    for code in ADDITION_CASCADE_ORDER:
        if _PREDICATES[code](signals):
            return code
    return "A26"  # safety fallback


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _priority_weight(code: str) -> float:
    pos = ADDITION_CASCADE_ORDER.index(code) + 1   # 1-indexed
    return 1.0 / (pos ** 0.5)


def _compute_scores(
    matched: list[str],
    cascade_primary: str,
    priors: dict[str, float],
) -> list[tuple[str, float]]:
    """
    Returns a list of (code, score) tuples — names are attached later in classify()
    so this function stays focused on the math and doesn't need to know about names.
    """
    if not matched:
        return []
    n_matched = len(matched)
    specificity = 1.0 / n_matched
    raw_scores = {}
    for code in matched:
        prior = priors.get(code, 0.0)
        priority = _priority_weight(code)
        raw_scores[code] = specificity * prior * priority

    # Guarantee cascade-primary is on top
    max_score = max(raw_scores.values())
    if raw_scores[cascade_primary] < max_score:
        raw_scores[cascade_primary] = max_score * 1.0001

    total = sum(raw_scores.values())
    if total == 0:
        return [(c, 1.0 / n_matched) for c in matched]
    normalized = [(code, raw_scores[code] / total) for code in raw_scores]
    normalized.sort(key=lambda x: (-x[1], ADDITION_CASCADE_ORDER.index(x[0])))
    return normalized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SCORE_INCLUSION_THRESHOLD = 0.01

ADDITION_PRIORS_BY_GRADE: dict[Optional[int], dict[str, float]] = {
    None: ADDITION_PRIORS_ALL,
}


def classify(
    n1: int | str,
    n2: int | str,
    learner_response: object,
    learner_grade: Optional[int] = None,
    *,
    return_debug: bool = False,
) -> ClassifyResult:
    """
    Classify an Addition response into one or more misconception codes.

    Args:
        n1, n2: Operands. Strings (with optional commas) are parsed.
        learner_response: The learner's submitted answer.
        learner_grade: Optional learner grade for prior lookup.
        return_debug: If True, includes computed signals in the result.
    """
    # --- Parse operands (handles "1,006" → 1006) ---
    n1_p = parse_operand(n1)
    n2_p = parse_operand(n2)
    if n1_p is None or n2_p is None:
        # Operand parse failure is an upstream data issue, not a learner misconception.
        return ClassifyResult(
            cascade_code="A26",
            cascade_name=ADDITION_ERROR_NAMES["A26"],
            ranked=[("A26", ADDITION_ERROR_NAMES["A26"], 1.0)],
            debug={"error": "operand parse failed"} if return_debug else {},
        )

    # --- Pre-compute signals ---
    raw = normalize_raw(learner_response)
    wi = parse_response(learner_response)
    correct = n1_p + n2_p

    signals: dict = {
        "n1": n1_p,
        "n2": n2_p,
        "wi": wi,
        "raw": raw,
        "correct": correct,
        "col_sums": [],
        "carries": [],
        "carries_in": [],
        "pvp_candidates": set(),
        "carry_drop_one_candidates": set(),
        "a18_sim": False,
        "zero_compound": False,
    }
    if wi is not None:
        signals["col_sums"] = column_sums_units_first(n1_p, n2_p)
        signals["carries"] = carries_units_first(n1_p, n2_p)
        signals["carries_in"] = carries_in_units_first(n1_p, n2_p)
        if not (n_digits(n1_p) == 1 and n_digits(n2_p) == 1):
            signals["pvp_candidates"] = place_value_permutations(n1_p, n2_p)
        signals["carry_drop_one_candidates"] = carry_dropped_one_variant_candidates(n1_p, n2_p)
        # v15 (items 1/2/4): width-guarded compound double/zero simulation.
        a18_sim, zero_compound = _compound_double_zero_traces(n1_p, n2_p, wi, correct)
        # v15 (item 7, adopted): single x<5 doubled column written as the addend.
        if not a18_sim and _single_double_addend_le4(n1_p, n2_p, wi, correct):
            a18_sim = True
        signals["a18_sim"] = a18_sim
        signals["zero_compound"] = zero_compound

    # --- Correct answer fast path ---
    if wi is not None and wi == correct:
        return ClassifyResult(
            cascade_code="CORRECT",
            cascade_name="",
            ranked=[],
            debug=signals if return_debug else {},
        )

    # --- A01 fast path: invalid input bypasses everything ---
    if wi is None:
        return ClassifyResult(
            cascade_code="A01",
            cascade_name=ADDITION_ERROR_NAMES["A01"],
            ranked=[("A01", ADDITION_ERROR_NAMES["A01"], 1.0)],
            debug=signals if return_debug else {},
        )

    # --- Cascade primary ---
    cascade_primary = _cascade_first_match(signals)

    # --- All matching rules (no suppression) ---
    matched = [code for code in ADDITION_CASCADE_ORDER if _PREDICATES[code](signals)]
    # Drop A26 from matched unless it's the only one
    if "A26" in matched and len(matched) > 1:
        matched = [c for c in matched if c != "A26"]

    # --- v16.1: compound double+zero — A21 is now the PRIMARY (see _rule_A21).
    # A21 fires on its own for compound traces, so it is already in `matched`
    # and wins the cascade primary; A22 remains as a marker via its a18_sim
    # path. This block is now only a fallback: if A21 was vetoed as primary
    # (e.g. by the A04 exact-product rule) it still surfaces A21 as a marker.
    if signals.get("zero_compound") and "A22" in matched and "A21" not in matched:
        matched.append("A21")

    # --- Score and rank ---
    priors = ADDITION_PRIORS_BY_GRADE.get(learner_grade) or ADDITION_PRIORS_ALL
    ranked_full = _compute_scores(matched, cascade_primary, priors)
    # Decorate with names and apply threshold
    ranked = [
        (c, ADDITION_ERROR_NAMES.get(c, ""), s)
        for c, s in ranked_full
        if s >= SCORE_INCLUSION_THRESHOLD
    ]

    return ClassifyResult(
        cascade_code=cascade_primary,
        cascade_name=ADDITION_ERROR_NAMES.get(cascade_primary, ""),
        ranked=ranked,
        debug=signals if return_debug else {},
    )
