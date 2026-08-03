"""
Multiplication misconception classifier (codes M01–M46), v20.

v20 changes (label-only promotion; no rule changes):
  - No detection logic changed. v18, v19, and v20 produce byte-identical
    classifications. v20 marks a SEMANTIC pin for the tagged workbook's
    flag columns: the v19 workbook's M01–M46 flags were built from the raw
    pre-threshold `matched` list (every predicate fire), while classify()'s
    public contract — and the HTML widget — expose `ranked` (post-deferral,
    score >= SCORE_INCLUSION_THRESHOLD). The two disagree on 444 of 63,389
    rows (e.g. 13×30='39' correct 390: M23/M24 genuinely fire but score
    below threshold, so ranked excludes them; M34/M39 likewise account for
    297 of the 444). All 444 are losing fires — Final codes are identical
    under both semantics. From v20 the workbook flag columns == ranked,
    so workbook, classify(), and UI agree row-for-row.

Originally derived from Multiplication_Error_Rules_v11.docx, but the code set and
detection rules have evolved across later versions (see changelog), so individual
code assignments and meanings can differ from v11. Notably, M26 is now the
tens-row-tens-digit error (TENS_ROW_TENS_DIGIT_ONLY); the column-wise error that
v11 labelled M26 is this engine's M27 (COLUMN_WISE_MUL).

Each rule's detection condition is rooted in v11's "Detection rule:" text, refined
in later versions. Cascade order is M01 → M02 → ... → M46
sequential, with conflict-resolution guards stated in individual rules
(e.g. M15 "fires after M14", M17 guard "N2 must be multi-digit", M44 fires
only after M01–M43; M46 is the unclassified-error fallback). The "Fires after X" notes are
implicitly honoured by sequential cascade traversal.

API
---
    classify(n1, n2, learner_response, learner_grade=None,
             *, return_debug=False) -> ClassifyResult

Returns ClassifyResult with:
    - cascade_code: the spec-defined cascade output (top of the ranked list)
    - cascade_name: human-readable error name for cascade_code
    - ranked: list of (code, name, score) triples, ranked by score descending
    - debug: optional dict with computed signals

Score formula (same as Addition / Subtraction)
==============================================
For each input, the classifier computes a single cascade winner and a
ranked list of candidate codes with normalized scores in [0, 1] that
sum to 1.0.

Computation pipeline (across classify() and _compute_scores()):

  1. Collect all codes whose predicate returns True for the input
     signals. If M46 is among them and any other code also matches,
     M46 is dropped from the candidate set (M46 is strictly a fallback).

  2. For each candidate code c, compute a raw score:
       raw_score[c] = specificity * prior[c] * priority_weight(c)
     where
       - specificity      = 1.0 / n_candidates    (uncertainty penalty)
       - prior[c]         = corpus frequency of c divided by total
                            errors, taken from MULTIPLICATION_PRIORS_ALL
       - priority_weight  = 1.0 / pos**0.5
                            (pos is 1-indexed cascade position; gives
                             earlier codes a higher base weight)

  3. Boost the cascade winner so it always ranks first even when its
     raw score is not the highest:
       raw_score[cascade_primary] = max(raw_scores.values()) * 1.0001

  4. Normalize raw scores so they sum to 1.0:
       score[c] = raw_score[c] / sum(raw_scores.values())

  5. Drop codes whose normalized score is below
     SCORE_INCLUSION_THRESHOLD (0.01, i.e., 1%) from the returned
     `ranked` list.

  6. Return cascade_primary as ClassifyResult.cascade_code; return the
     filtered/sorted list as ClassifyResult.ranked.

Special-case returns from classify()
------------------------------------
  - CORRECT answer (wi == correct): cascade_code="CORRECT", ranked=[]
  - Unparseable wi:                  cascade_code="M01",     score=1.0
  - Operand parse failure:           cascade_code="M46",     score=1.0





v19 changes (M26 guard + rename; TAG CHANGE on 3-digit M26 rows):
  • M26 renamed ORDER_OF_MUL → TENS_ROW_TENS_DIGIT_ONLY. The formula models the
    tens-row partial product using only N1's tens digit (not multiplication order),
    so the old name was misleading.
  • M26 now guarded to 2-digit operands (added "or n1>=100 or n2>=100 → return
    False"). Its fixed two-row formula cannot represent a 3-row product, so on
    3-digit operands it only ever matched degenerate small candidates
    (e.g. 410×190='90', candidate = 410×0 + 1×9×10 = 90). Corpus impact: 59 rows
    lost a spurious M26 flag; 11 where M26 was the winner re-classified
    (6 → M36 PARTIAL_PRODUCT, 4 → M46, 1 → M27). 2-digit M26 rows unaffected.
  • _FREQ_TABLE synced to the retagged corpus (M26 208→180, M27 3427→3429,
    M36 2356→2372, M46 183409→183419; _TOTAL_FREQ unchanged at 336,582). Priors
    derive from _FREQ_TABLE, so this only shifts base rates by ~0.008%; the cascade
    winner is forced first regardless, so it is tag-neutral.
  No other classification, cascade, or label change.

v18 changes (M03 misuse-fallback phrasing; no tag change):
  • The M03 sub-step generic fallback no longer implies a zero column exists
    ("in a zero column instead of 0" → "applied the 0×d=d substitution at a
    partial product"). This branch is unreachable in the normal classify→label
    flow (M03 is only tagged when a zero is present, so the named-column branch
    always fires); the change only affects how a forced/misused M03 label reads.
  No classification, cascade, label-on-real-data, or tag change.

v17 changes (M03/M21 detailed-label refinement; no tag change):
  • M21 detailed label now distinguishes whole-problem identity from sub-step
    and names the triggering column/partial product (e.g. "applied 2×2=2 at
    the units column of the ×2 partial product in 12×23=276").
  • M21 sub-step column finder excludes d=1 no-ops (1×1=1 is correct, not an
    error), dedupes repeated columns, and enumerates all real (d>=2) columns.
  • M03 sub-step label names the zero column and its mechanism (e.g. "wrote the
    non-zero digit in the units column; treated 0×4 as 4"). Its generic
    fallback no longer asserts "contains 0 digit" (which was false if the label
    function is ever forced onto a no-zero problem under misuse).
  Detailed Error Label text only — classification, cascade, and tags unchanged.

v16 changes (M21 whole-problem identity priority):
  • _rule_M17 and _rule_M18 now defer to M21 when n1==n2 and the learner
    wrote n1 (the whole-problem "n×n=n identity" case). Previously these
    same-digit cases (e.g. 10×10='10', 50×50='50', 88×88='88') were tagged
    M17/M18, forcing a contrived multi-error story (e.g. 88×88='88' as five
    independent shift/carry slips). M21 explains them as one misconception.
  • Whole-problem only (n1==n2 AND wi==n1); the M21 sub-step branch is NOT
    used for deferral, so genuine shift/carry errors on differing operands are
    untouched. M19/M20 cannot fire on identity; M23/M24 sit after M21, so once
    M17/M18 step aside the cascade reaches M21 first.
  No predicate logic changed beyond these two deferrals.

v15.0.2 changes (final code hygiene):
  • Removed dead function `_find_drop_carry_match` (defined but never
    called; superseded by `_find_intra_row_drop_match` and
    `_find_addition_drop_match` which are actually used in
    make_detailed_label).
  • Removed unused import `digits_ltr` from utils.
  • Refined v15.0.1's Score formula docstring header to accurately
    reflect that the pipeline spans both classify() and _compute_scores()
    (not just _compute_scores).
  No behavior impact — purely code hygiene.

v15.0.1 changes (documentation patch):
  • Filled in the empty "Score formula" section in the module docstring.
    The formula was already implemented (see _compute_scores at the bottom
    of the file), but the docstring header had blank lines beneath it
    where the formula description should have been. No behavior change —
    purely documentation.

v15.0 changes (cleanup release):
  • Change A: M14 STEP_OP_ADDITION — removed "M11" from defer tuple.
    M11 is at cascade position 10, M14 at position 13. If M11 fires, the
    cascade stops at M11 and M14 is never reached, so M14's defer-to-M11
    was dead code. Functionally a no-op; cleanup only.

  • Change B: M18 CARRYING_SHIFT — removed defer-to-M37 for consistency
    with v14.7's M17 fix. M18 is the compound M10+M17 misconception; same
    logical relationship to M37 branch 1 (digit-sum substitution) as M17.
    The "kid forgot to shift + drop carry" diagnosis is the simpler cognitive
    story than the contrived "digit-sum substitution" re-framing.

    Corpus impact: small number of rows (~13 freq) flip M37 → M18.

  • Changes C-E: Updated WHAT_IT_MEANS for M02, M16, M17 to mention their
    respective v14.x changes:
      - M02 now mentions v14.6 deferral to M05 for N1==N2 cases
      - M16 now mentions v14.3 carry_in > 0 guard
      - M17 now mentions v14.7 fix (no-shift cases that coincide with M37)
    These propagate to the "What It Means" column for all affected rows.

  • Changes F-G: Taxonomy sheet sub-skill re-categorization (xlsx-only):
      - M21 SAME_DIGIT_IDENTITY: "Partial/incomplete output"
        → "Conceptual rule misconceptions" (n×n=n is a rule misconception,
        not a partial-output pattern; aligns with M02, M03 which are also
        rule-misconception codes)
      - M15 STEP_WRONG_MULTIPLIER: "Multi-step procedural"
        → "Arithmetic fluency" (single-step ±1/±2 perturbation is a
        times-table fluency slip, aligning with M44 NEAR_MISS)

v14.9 changes:
  • Taxonomy sheet completion (xlsx-only change). No predicate logic
    or _FREQ_TABLE changes — v14.9 == v14.8 for classification behavior.

    Three improvements to the Taxonomy sheet:

    1. Column 5 "Detection Rule + Top-5 Examples": now contains a clear
       plain-English detection rule (refreshed to reflect v14.2–v14.8
       changes) AND the top-5 actual corpus examples per code with their
       frequencies. Previously only the WHAT_IT_MEANS string was there;
       no examples.

    2. Column 6 "Remedial Action": now filled for all 46 codes with
       2–3 sentence pedagogical interventions aligned to AML/MPA
       (Manipulative-Pictorial-Abstract) pedagogy. Previously empty.

    3. Banner updated to reflect v14.9.

    Refreshed descriptions mention version-specific changes where relevant
    (e.g., M02 mentions v14.6 deferral, M17 mentions v14.7 fix, M35
    mentions v14.8 carry guard).

v14.8 changes:
  • M34 renamed: LEADING_UNITS_APPEND → LEAD_X_UNITS_APPEND_UNITS.
    The new name parses more clearly: "Leading-digit (of N1) × Units-digit
    (of N2), then Append Units-digit (of N2)." No predicate changes.

  • M35 ROW1_CARRY_DROPPED: added carry-needed guard. The predicate
    previously fired for both "kid wrote N1 × units(N2) and dropped carries"
    (genuine carry-dropping) AND "kid wrote N1 × units(N2) where no carry
    exists" (vacuous — dropping zero is a no-op). For the no-carry cases,
    wi is just a partial product (M36's territory).

    Now M35 requires at least one digit step in row 0 to have an actual
    carry (i.e., some d × units(N2) >= 10), making "dropped" meaningful.

    Corpus impact: ~13 rows / ~114 freq move M35 → M36 PARTIAL_PRODUCT.
    Examples: 33×12='66', 23×32='46', 423×12='846'. Genuine carry-dropped
    cases (e.g., 27×34='88') remain M35.

v14.7 changes:
  • M17 SHIFT_INDENTATION: removed the "defer to M37 if M37 fires" guard.
    M37 branch 1 (wi = N1 × digit_sum(N2)) is algebraically identical to
    M17 with shift_offsets=(0, 0, ..., 0) — they catch the same coincidence
    with different framings. M17 ("kid forgot to shift") is the simpler
    cognitive story; M37 ("kid used digit-sum substitution") is a contrived
    re-framing.

    The fix also resolves an inconsistency exposed by 31×12='93' vs
    31×12='651': both are shift errors, but '93' was tagged M23 (because
    M17 deferred to M37, then M23 won by ordering since M23 has no M37
    deferral) while '651' was tagged M17 (M37 didn't fire). Removing the
    guard makes M17 win consistently for all shift errors.

    Corpus impact: ~213 rows / ~3,885 freq move from M23 (74 rows) and
    M37 (139 rows) into M17. M23 retains its genuinely-unique LTR catches
    (where LTR produces a different result than standard direction). M37
    retains branches 2 and 3 (digit_sum(N1)×N2, digit_sum(N1)×digit_sum(N2))
    and its 1D-N2 catches, which M17 cannot diagnose.

v14.6 changes:
  • M02 ZERO_ANSWER: added deferral to M05 WRONG_OP_SUBTRACTION. When
    N1==N2 and wi==0, both predicates fire (since |N1-N2|=0 matches M05).
    M02 wins by cascade position in v14.5, but M05 is the more specific
    diagnosis — it identifies the subtraction misconception rather than
    just noting "the answer is 0". M02 now defers when M05 also fires.

    Corpus impact: ~24 rows / ~1,595 freq move from M02 to M05. Examples:
    5×5='0', 2×2='0', 3×3='0', 7×7='0', 4×4='0'.

    Marker semantics: M02 marker becomes 0 for deferring rows (matches the
    consistent convention used by all other deferrals — v14.3 M14→M16,
    v14.4 M17→M45, etc.).

v14.5 changes:
  • M21 SAME_DIGIT_IDENTITY: moved the 1D×1D guard below the
    whole-problem branch. Previously the guard at the top of the predicate
    blocked the whole-problem check (N1==N2 AND wi==N1) for 1D×1D inputs,
    even though that branch was designed specifically to catch canonical
    "n×n=n identity confusion" patterns like 4×4='4', 7×7='7'.

    The 1D×1D guard was defensively added to prevent step-machinery
    false-positives, but only the step-machinery sub-step branch
    needs that protection. The whole-problem branch is a direct
    structural check that's safe at any size.

    Corpus impact: ~13 rows / ~1,593 freq move into M21 (mostly from
    M40 / M30 / M46). The pedagogical signal for "n×n=n identity"
    is now correctly attributed to M21 instead of being scattered.

v14.4 changes:
  • M45 ROW_RESULT_CONCAT: removed "defer to M17 if single-row-shift
    also matches" guard from the reversed-order branch. The guard was
    historically added to prevent false positives against M17 for
    asymmetric N2, but cognitive analysis showed it was over-deferring:
    the M45 concat story (kid skipped addition entirely) is strictly
    simpler than M17's shift+add interpretation, which requires precise
    addition of large numbers after a layout error.

    Now: when both M17's structural test and M45's reversed-concat match
    the wi, M45 fires. M17's "defers to M45" check (which already exists)
    handles the routing correctly: M17 sees M45 firing and defers.

    Corpus impact: 21 rows / 223 freq shift from M17 to M45 (examples:
    33×12='3366', 34×21='6834', 30×24='60120', 50×17='50350').

v14.3 changes:
  • M16 STEP_CARRY_ADD_ERROR: added carry_in > 0 guard.
    Corpus audit found 63% of M16 frequency had carry_in = 0 at the
    perturbed step — these were "phantom carry" interpretations where
    the kid had no carry coming in but the predicate's delta range
    happened to match the wi arithmetically. The misconception
    "added the wrong carry" is incoherent when there's no carry,
    so these now correctly route to other codes (mostly M46 UNCLASSIFIED;
    some to M44 NEAR_MISS when close-to-correct).

    Implementation: added _carry_in_at_step(n1, n2, j, i) helper that
    computes carry_in via standard long-multiplication simulation. M16's
    coord loop now skips steps where this returns 0.

    Corpus impact: ~1,262 freq shifts out of M16 (was 1,996, now ~734).
    Remaining M16 catches are the cognitively meaningful cases where
    a real carry was added with the wrong magnitude.

v14.2 changes:
  • EXTENDED M03 ZERO_PROPERTY_ERROR sub-step branch from
    "n1 >= 10 AND n2 >= 10" to "n1 >= 10 OR n2 >= 10". This catches
    2D×1D and 3D×1D zero-property cases like 30×4='124'
    (kid did 0×4=4 in tens column) that previously fell through
    to M15 STEP_WRONG_MULTIPLIER (wrong remediation: M15 says practice
    a table fact, but the real issue is the 0×n=n misconception).
    Corpus impact: ~778 freq shifts from M15 to M03.

  • REMOVED M46 COMPOUND_DUAL_TABLE. Audit revealed the predicate
    was firing on arithmetic coincidences rather than real misconceptions:
    100% of M46 catches had implausible deltas (|Δ| ≥ 3 on at
    least one slip; 80% had |Δ| ≥ 7). The delta range ±12
    was too permissive, allowing nonsensical interpretations like
    "kid recalled 5×3=6" or "kid recalled 0×2=-9". The predicate
    has been removed entirely.

  • RENUMBERED: old M47 UNCLASSIFIED_ERROR becomes new M46. Total
    codes: 47 → 46. The fallback (unclassified) is now M46.

  • Corpus impact: 31,808 freq formerly M46 (now M46 = fallback) +
    150,858 freq formerly M47 (now M46) = 182,666 freq in the new M46
    UNCLASSIFIED_ERROR. About 54% of total error frequency falls into
    "we can't confidently diagnose" — honest reflection of the
    fact that many wrong answers don't match any clean cognitive procedure.

v14.1 changes:
  • RENAMED M10 CARRYING_ERROR → CARRY_IGNORED (more accurate: the
    simulation treats dropped carries as 0, i.e., ignored rather than
    miscomputed).
  • EXTENDED M10 predicate to also catch addition-step carry drops.
    Previously only intra-row multiplication carry drops were simulated;
    now both intra-row (Type A) and cross-row addition carries (Type B)
    are searched. This catches errors like 89×17='1413' (addition
    tens-carry dropped) that previously fell through to other codes.
  • ENRICHED M10 Detailed Error Label to disclose which interpretation(s)
    match: "Multiplication Carry Ignored: Row1(×3) ...", "Addition step:
    missing carry between tens and hundreds", or "ambiguous: could be X OR Y"
    when both interpretations produce the same wi.
  • Corpus impact: 38 rows shifted from other codes (M14, M15, M16, M44, M46)
    to M10 — these were errors where the addition-drop interpretation matches
    but the intra-row interpretation does not. M10 corpus total: 2,880 → 3,005
    frequency; 298 → 336 rows. Label-type distribution: 79% intra-row only,
    11% addition only, 10% ambiguous (both match).
  • Polish: WHAT_IT_MEANS['M18'] and docstrings of M18/M24 updated to use
    "carry ignored" terminology consistent with the M10 rename.

v14.0 changes:
  • SPLIT M12 into two distinct misconceptions (pedagogical refinement):
      - NEW M12 TENS_NOT_MULTIPLIED: kid skipped multiplication in upper
        columns, just wrote N2 there. Units step had no carry.
      - M13 CARRY_ADD_TO_MULTIPLIER (formerly M12 CARRY_ADD_N2_SKIP_DIGIT):
        kid added carry to N2 instead of multiplying. Units step had a carry.
    These were observationally indistinct at the predicate level (both produce
    the same wi via the same simulation) but represent different cognitive
    procedures requiring different remediation. The split is based on whether
    (N1 % 10) * N2 >= 10 at the units step (carry generated or not).
  • Code renumbering: old M12 → new M13; old M13 → new M14; ...; old M46 → new M47.
    Total codes: 46 → 47.
  • Corpus impact (from v13.1 tagging): old M12 freq 488 splits ~278 (new M12)
    and ~210 (new M13). All other codes shift labels but keep frequencies.

v13.1 changes:
  • Added 1D×1D guards to 13 multi-step procedural rules
    (M10, M11, M13, M14, M15, M16, M18, M19, M20, M21, M23, M24, M35)
    to fix false-positives where long_multiply_simulate's modular
    arithmetic accidentally matched single-digit wrong answers.
    Example fixed: 0×6='7' was M16 (false), now M47 (honest).
  • _FREQ_TABLE updated from corpus tagging (was spec-derived);
    corpus-derived _TOTAL_FREQ is 336,582.
  • Largest corpus insight: M46 COMPOUND_DUAL_TABLE freq 2,417 → 31,809
    (spec under-counted dual-table errors by 13×).

"""

__version__ = "20"

from dataclasses import dataclass, field
from typing import Optional, Callable
from itertools import product as iproduct

from utils import (
    parse_response, parse_operand, normalize_raw,
    digits, n_digits, concat_int,
    digit_sum, digits_rtl,
    long_multiply_simulate, column_wise_digit_mul,
    digit_concat_rtl_product, digit_concat_ltr_product,
    row_concat_digit_mul,
)


# ---------------------------------------------------------------------------
# Corpus-derived priors (from Multiplication_tagged_TS_Kalika_Pvt_v14_1.xlsx,
# 336,582 error frequency; v14.1 extended M10 to catch addition-step carry drops)
# ---------------------------------------------------------------------

_TOTAL_FREQ = 336_582  # sum of all M01..M46 frequencies (corpus-derived)
_FREQ_TABLE = {
    "M01":   9_501, "M02":  18_620, "M03":   5_055, "M04":  23_074,
    "M05":   6_834, "M06":   2_787, "M07":  11_740, "M08":   3_473,
    "M09":     948, "M10":   3_005, "M11":     324, "M12":     278,
    "M13":     206, "M14":     792, "M15":   7_436, "M16":     734,
    "M17":   4_290, "M18":     509, "M19":     801, "M20":     376,
    "M21":   1_799, "M22":     606, "M23":     127, "M24":      73,
    "M25":      29, "M26":     180, "M27":   3_429, "M28":     384,
    "M29":   1_592, "M30":   8_965, "M31":   2_196, "M32":     288,
    "M33":     249, "M34":     482, "M35":     218, "M36":   2_372,
    "M37":   1_213, "M38":   1_571, "M39":     151, "M40":  11_792,
    "M41":     924, "M42":     322, "M43":   1_305, "M44":  11_733,
    "M45":     380, "M46": 183_419,
}
MULTIPLICATION_PRIORS_ALL: dict[str, float] = {
    code: freq / _TOTAL_FREQ for code, freq in _FREQ_TABLE.items()
}


# ---------------------------------------------------------------------------
# Spec-derived error names (from Multiplication_Error_Rules_v11.docx, Table 0)
# ---------------------------------------------------------------------------

MULTIPLICATION_ERROR_NAMES: dict[str, str] = {
    "M01": "RANDOM_OR_INVALID",
    "M02": "ZERO_ANSWER",
    "M03": "ZERO_PROPERTY_ERROR",
    "M04": "WRONG_OP_ADDITION",
    "M05": "WRONG_OP_SUBTRACTION",
    "M06": "WRONG_OP_DIVISION",
    "M07": "PARTIAL_OPERAND_COPY",
    "M08": "DIGIT_CONCAT_RTL",
    "M09": "DIGIT_CONCAT_LTR",
    "M10": "CARRY_IGNORED",
    "M11": "CARRY_ADD_BEFORE_MUL",
    "M12": "TENS_NOT_MULTIPLIED",
    "M13": "CARRY_ADD_TO_MULTIPLIER",
    "M14": "STEP_OP_ADDITION",
    "M15": "STEP_WRONG_MULTIPLIER",
    "M16": "STEP_CARRY_ADD_ERROR",
    "M17": "SHIFT_INDENTATION",
    "M18": "CARRYING_SHIFT",
    "M19": "CARRY_WRITE_SWAP",
    "M20": "CARRY_PROPAGATION_CONFUSION",
    "M21": "SAME_DIGIT_IDENTITY",
    "M22": "LTR_DIRECTION",
    "M23": "LTR_SHIFT",
    "M24": "LTR_CARRYING_SHIFT",
    "M25": "TRAILING_ZERO_PREFIX1",
    "M26": "TENS_ROW_TENS_DIGIT_ONLY",
    "M27": "COLUMN_WISE_MUL",
    "M28": "TENS_STEP_ADDITION",
    "M29": "MUL_LEADING_ADD_TRAILING",
    "M30": "TRUNCATED_ANSWER",
    "M31": "OPERAND_CONCATENATION",
    "M32": "REVERSED_N1",
    "M33": "ROW_CONCAT_DIGIT_MUL",
    "M34": "LEAD_X_UNITS_APPEND_UNITS",
    "M35": "ROW1_CARRY_DROPPED",
    "M36": "PARTIAL_PRODUCT",
    "M37": "DIGIT_SUM_SUBSTITUTION",
    "M38": "ALL_DIGIT_SUM",
    "M39": "PLACE_VALUE_ERROR",
    "M40": "WRONG_MULTIPLIER",
    "M41": "DIGIT_REVERSAL_ANSWER",
    "M42": "FINAL_CARRY_REPLACED_BY_N2",
    "M43": "DIGIT_ASSEMBLY_ORDER",
    "M44": "NEAR_MISS",
    "M45": "ROW_RESULT_CONCAT",
    "M46": "UNCLASSIFIED_ERROR",
}


# ---------------------------------------------------------------------------
# Per-code 'What It Means' — cognitive description of each misconception
# (derived from v11 taxonomy; used to populate the 'What It Means' xlsx column)
# ---------------------------------------------------------------------------

WHAT_IT_MEANS: dict[str, str] = {
    "M01": "Repeated/random digits – likely disengaged learner, not a math error",
    "M02": "Learner typed 0 – no attempt or confused about zero multiplication rule. When N1==N2, defers to M05 (subtraction story explains the zero specifically; v14.6).",
    "M03": "Learner applies n×0=n at partial-product step level: instead of writing 0 for digit×0 products, they write the non-zero digit itself. All other steps are computed correctly. Applies symmetrically when 0 is in N1 or N2.",
    "M04": "Wrong operation: used addition instead of multiplication",
    "M05": "Wrong operation: used subtraction instead of multiplication",
    "M06": "Learner divided the operands instead of multiplying. Applied ÷ in place of ×.",
    "M07": "Learner wrote one of the operands as the answer",
    "M08": "Each digit × multiplier computed separately, results joined right-to-left as text",
    "M09": "Each digit × multiplier computed separately, results joined left-to-right as text",
    "M10": "Learner ignored (failed to propagate) one or more carries during long multiplication. Two sub-types: intra-row carry ignored during a partial-product row OR addition-step carry ignored when summing partial-product rows. Both stem from the same underlying gap: unreliable carry propagation. Often observationally identical for 2D×2D problems.",
    "M11": "Learner added carry to digit BEFORE multiplying: step = (digit + carry) × N2 instead of correct (digit × N2) + carry.",
    "M12": "Learner skipped multiplication entirely in upper columns — just wrote N2 there. The units step produced no carry, so the kid never engaged with the carry-propagation step. They appear to think multiplication is a one-time operation, not a per-column procedure.",
    "M13": "Learner correctly multiplied the units digit but, for subsequent digits, added the carry to N2 instead of multiplying the digit by N2. They are engaging with the carry — they just place it in the wrong location (multiplier rather than new product).",
    "M14": "At one step within a partial-product row, learner added instead of multiplied.",
    "M15": "At one step within a partial-product row, learner recalled an adjacent times-table fact.",
    "M16": "Correct multiplication fact, carry addition wrong by ±1–3. v14.3: only fires when an actual carry exists at the perturbed step (no phantom-carry cases).",
    "M17": "Partial product row(s) not indented correctly – missing trailing zero(s) for row position. v14.7: also catches no-shift cases where wi coincides with N1 × digit_sum(N2) (previously routed to M37).",
    "M18": "Both a carry-ignored (M10-type) and an indentation/shift (M17-type) error present in the same response",
    "M19": "Writes tens digit and carries units digit of each 2-digit sub-product (exact reversal of correct rule: write units, carry tens). Procedure and table recall are correct; carry direction is backwards.",
    "M20": "Learner correctly wrote the units digit but then used that same written digit as the carry into the next step, instead of propagating the actual carry (tens digit of the product).",
    "M21": "Learner applies n×n=n at individual algorithm steps where digit_of_N1 == digit_of_N2. All other steps correct; only matched-digit steps use identity shortcut.",
    "M22": "LTR Direction Error",
    "M23": "LTR + Shift Error",
    "M24": "LTR + Carrying + Shift Error",
    "M25": "Learner ignored trailing zero of operand, then prepended '1' to the partial product",
    "M26": "Row 2 (tens row) used only n1.T×n2.T (matching tens digits) instead of full n1×n2.T",
    "M27": "Multiplied only matching digit positions (units×units, tens×tens); no cross-multiplication, results concatenated as text",
    "M28": "Units digit multiplied correctly, but tens step used addition (n1.T + n2 + carry) instead of multiplication",
    "M29": "Multiplied by the leading digit(s) of one operand, then added the trailing digit instead of continuing multiplication",
    "M30": "Learner wrote only part of the correct answer – stopped mid-way or copied partial digits",
    "M31": "Wrote both operands as adjacent digits instead of computing the product",
    "M32": "Digits of N1 reversed before multiplying – e.g. used 24×N2 instead of 42×N2",
    "M33": "Within each partial row, each digit of N1 × N2-digit computed without carry; products joined as text. Rows concatenated as strings (no shift, no addition).",
    "M34": "Multiplied the leading digit of N1 by the units digit of N2, then appended the units digit of N2 as a suffix – misunderstands how partial products combine.",
    "M35": "Computed only Row 1 (N1 × units digit of N2) but dropped the carry at every step, writing only the units digit of each sub-product. Rows 2+ ignored entirely.",
    "M36": "Only one digit of N1 used – rest of N1 ignored",
    "M37": "Replaced N1 with its digit sum before multiplying",
    "M38": "Learner summed all individual digits of both operands instead of multiplying.",
    "M39": "Answer is 10× too large – extra trailing zero(s)",
    "M40": "Recalled answer for N1+1 instead of N1 – adjacent table entry (overshoot by 1)",
    "M41": "Correct digits but written in reversed order",
    "M42": "Learner executed all multiplication and carry steps correctly but wrote N2 (the multiplier) as the leading digit instead of the actual final carry — a working-memory substitution at the last step.",
    "M43": "Learner computed the right digit-products and carry steps but assembled the final number in the wrong order — a place-value sequencing error, not a recall failure.",
    "M44": "Minor arithmetic slip – answer within 5% of correct",
    "M45": "Learner computes each partial-product row correctly (carry included within row) but concatenates the row totals as strings instead of summing with place-value shifts. Distinct from M26 which applies no carry at the digit level.",
    "M46": "No clear pattern detected – random guess or unusual strategy",
    "CORRECT": "Correct answer — no error",
}

# ---------------------------------------------------------------------------
# Per-instance detailed labels — render the actual numbers into a sentence
# ---------------------------------------------------------------------------

def _digit_sum(n: int) -> int:
    """Sum of decimal digits."""
    return sum(int(d) for d in str(abs(n)))


def _reverse_int(n: int) -> int:
    """Integer with digits reversed (e.g., 42 -> 24)."""
    return int(str(abs(n))[::-1])


_PLACES = ["units", "tens", "hundreds", "thousands", "ten-thousands", "lakhs"]


def _place(i: int) -> str:
    """Place-value name for column index i (0=units)."""
    return _PLACES[i] if i < len(_PLACES) else f"col{i}"


def _zero_property_column(n1: int, n2: int):
    """For an M03 sub-step, identify the zero-digit column treated as n\u00d70=n.
    Returns (place_name, the_other_digit) for the first qualifying column, or None.
    A 0 in N1 multiplies against N2's units digit; a 0 in N2 against N1's units."""
    d1 = digits_rtl(n1)
    d2 = digits_rtl(n2)
    for i, d in enumerate(d1):
        if d == 0:
            return (_place(i), d2[0])  # 0 in N1 at this place; row digit = N2 units
    for j, d in enumerate(d2):
        if d == 0:
            return (_place(j), d1[0])  # 0 in N2 at this place; row digit = N1 units
    return None


def _same_digit_identity_columns(n1: int, n2: int):
    """For an M21 sub-step, find columns where a digit of N1 equals a row digit of
    N2 (the n\u00d7n=n trigger). Returns list of (digit, n1_place, row_desc) where
    row_desc names the partial-product row for multi-digit N2 (empty for 1-digit)."""
    d1 = digits_rtl(n1)
    d2 = digits_rtl(n2)
    out = []
    multi = len(d2) >= 2
    seen = set()
    for j, rd in enumerate(d2):          # each N2 digit = one partial-product row
        for i, d in enumerate(d1):        # each N1 digit
            # d=0 gives 0; d=1 is a no-op (1\u00d71=1 is correct), so only d>=2 is an
            # observable identity error worth naming.
            if d == rd and d >= 2:
                row_desc = f"\u00d7{rd}" if multi else ""
                key = (d, _place(i), row_desc)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def _format_drop_carries(drop_set, n2: int) -> str:
    """Render a drop_carries set as 'Row{k}(x{d}): missing carry [{from}->{to}]; ...'."""
    descs = []
    for j, i in sorted(drop_set):
        d_n2 = (n2 // (10 ** j)) % 10
        descs.append(f"Row{j+1}(\u00d7{d_n2}): missing carry [{_place(i)}\u2192{_place(i+1)}]")
    return "; ".join(descs)


def _find_shift_offset_match(n1: int, n2: int, wi: int, ltr: bool = False,
                              drop_set=None):
    """Find shift_offsets tuple making sim equal wi. Returns tuple or None."""
    n_rows = n_digits(n2)
    max_off = n_rows + 2
    default = tuple(range(n_rows))
    for offsets in iproduct(range(max_off + 1), repeat=n_rows):
        if offsets == default:
            continue
        kwargs = {'shift_offsets': offsets}
        if ltr:
            kwargs['ltr_direction'] = True
        if drop_set is not None:
            kwargs['drop_carries'] = drop_set
        if long_multiply_simulate(n1, n2, **kwargs) == wi:
            return offsets
    return None


def _format_shift_offsets(offsets, n2: int) -> str:
    """Convert offsets tuple to label like 'Row2(x3): indented 0 place(s) not 1'."""
    default = tuple(range(len(offsets)))
    descs = []
    for r, off in enumerate(offsets):
        if off != default[r]:
            d_n2 = (n2 // (10 ** r)) % 10
            descs.append(f"Row{r+1}(\u00d7{d_n2}): indented {off} place(s) not {default[r]}")
    return "; ".join(descs) if descs else "shift error"


def _find_combined_match(n1: int, n2: int, wi: int, ltr: bool = False):
    """For M18, M24: find combination of drop_carries + shift_offsets matching wi."""
    coords = _step_coords(n1, n2)
    if not coords or len(coords) > 6:
        return None, None
    n_rows = n_digits(n2)
    max_off = n_rows + 2
    default = tuple(range(n_rows))
    for mask in range(1, 1 << len(coords)):
        drop_set = {coords[k] for k in range(len(coords)) if mask & (1 << k)}
        for offsets in iproduct(range(max_off + 1), repeat=n_rows):
            if offsets == default:
                continue
            kwargs = {'drop_carries': drop_set, 'shift_offsets': offsets}
            if ltr:
                kwargs['ltr_direction'] = True
            if long_multiply_simulate(n1, n2, **kwargs) == wi:
                return drop_set, offsets
    return None, None


def make_detailed_label(
    code: str,
    n1: int,
    n2: int,
    correct: Optional[int] = None,
    wi: Optional[int] = None,
    raw: Optional[str] = None,
) -> str:
    """
    Build a per-instance "Detailed Error Label" - a human-readable diagnosis
    that substitutes the actual N1, N2, correct answer, and wrong answer into
    a code-specific template.

    For procedural codes (M10, M17, M18, M23, M24) the label is computed by
    finding which simulation parameters (drop_carries, shift_offsets) match wi,
    and rendering them as 'Row{k}(x{d}): missing carry [units->tens]' etc.

    Pair with WHAT_IT_MEANS[code] for the per-code description.
    """
    if correct is None:
        correct = int(n1) * int(n2)
    wr = "" if raw is None else str(raw)

    if code == "M01" or code == "RANDOM_OR_INVALID":
        return "Keyboard Mash / Random Entry"
    if code == "M02":
        return "Zero Answer"
    if code == "M03":
        if n1 == 0 or n2 == 0:
            return f"Zero Property Error: {n1}\u00d7{n2}, wrote {wr or wi} instead of 0"
        # Sub-step: name the column where a 0 digit was treated as n\u00d70=n.
        col = _zero_property_column(n1, n2)
        if col:
            place, other = col
            return (f"Sub-step Zero Property: in {n1}\u00d7{n2}, wrote the non-zero digit "
                    f"in the {place} column (treated 0\u00d7{other} as {other} instead of 0)")
        return (f"Sub-step Zero Property: in {n1}\u00d7{n2}, applied the 0\u00d7d=d "
                f"substitution at a partial product")
    if code == "M04":
        return (f"Added Instead of Multiplied (N1+N2 = {n1}+{n2} = "
                f"{wi if wi is not None else n1+n2})")
    if code == "M05":
        return f"Subtracted Instead of Multiplied (|N1-N2| = {abs(n1-n2)})"
    if code == "M06":
        if n2 > 0 and n1 % n2 == 0:
            return f"Wrong Operation: Division (N1\u00f7N2 = {n1}\u00f7{n2} = {n1//n2})"
        if n1 > 0 and n2 % n1 == 0:
            return f"Wrong Operation: Division (N2\u00f7N1 = {n2}\u00f7{n1} = {n2//n1})"
        return f"Wrong Operation: Division ({n1}\u00f7{n2} or {n2}\u00f7{n1})"
    if code == "M07":
        if wi == n1:
            return f"Wrote N1 as Answer ({n1})"
        if wi == n2:
            return f"Wrote N2 as Answer ({n2})"
        return f"Partial Operand Copy (wrote {wr or wi} from N1={n1} or N2={n2})"
    if code == "M08":
        return "Digit-by-Digit Concat RTL (no carry, no shift)"
    if code == "M09":
        return "Digit-by-Digit Concat LTR (no carry, no shift)"
    if code == "M10":
        # v14.1: label now distinguishes intra-row (Type A) vs addition (Type B)
        # vs ambiguous (both match).
        if wi is not None:
            intra = _find_intra_row_drop_match(n1, n2, wi)
            addition = None
            if n_digits(n2) >= 2:
                addition = _find_addition_drop_match(n1, n2, wi)
            if intra and addition:
                return (f"Carry Ignored \u2014 ambiguous: could be "
                        f"{_format_drop_carries(intra, n2)} "
                        f"OR {_format_addition_drops(addition)}. "
                        f"Same underlying gap: carry propagation.")
            elif intra:
                return f"Multiplication Carry Ignored: {_format_drop_carries(intra, n2)}"
            elif addition:
                return f"{_format_addition_drops(addition)} (carry ignored when summing partial-product rows)"
        return f"Carry Ignored: {n1}\u00d7{n2}={correct} \u2192 wrote {wr or wi}"

    if code == "M11":
        return f"Carry Added Before Multiply: ({n1}\u00d7{n2}={correct}) \u2192 wrote {wr or wi}"
    if code == "M12":
        # M12 TENS_NOT_MULTIPLIED (v14.0): kid skipped multiplication in upper columns,
        # just wrote N2. Units step had no carry.
        if n1 >= 10 and n2 < 10:
            u = n1 % 10
            u_step = u * n2
            return (f"Tens Not Multiplied: {n1}\u00d7{n2}={correct}; "
                    f"units {u}\u00d7{n2}={u_step} (no carry), then kid wrote {n2} "
                    f"in tens column instead of multiplying \u2192 {wr or wi}")
        return f"Tens Not Multiplied: kid wrote N2 in upper column(s) \u2192 {wr or wi}"
    if code == "M13":
        # M13 CARRY_ADD_TO_MULTIPLIER (v14.0; was M12 in v13.x): kid added carry to N2
        # instead of multiplying the next digit. Units step DID produce a carry.
        if n1 >= 10 and n2 < 10:
            u = n1 % 10
            u_step = u * n2
            carry_in = u_step // 10
            return (f"Carry Added to Multiplier: units {u}\u00d7{n2}={u_step} "
                    f"(write {u_step%10}, carry {carry_in}); kid did {carry_in}+{n2}={carry_in+n2} "
                    f"in tens column instead of multiplying \u2192 {wr or wi}")
        return f"Carry Added to Multiplier: ({n1}\u00d7{n2}={correct}) \u2192 wrote {wr or wi}"
    if code == "M14":
        return "Sub-step addition in partial-product row: d1+d2_row used instead of d1\u00d7d2_row"
    if code == "M15":
        return "Sub-step wrong multiplier: (d1\u00b11 or \u00b12)\u00d7d2 recalled"
    if code == "M16":
        return "Sub-step carry error: carry_in off by \u00b11\u20133"
    if code == "M17":
        # Phase 2: find which row's shift was wrong
        if wi is not None and n_digits(n2) >= 2:
            offsets = _find_shift_offset_match(n1, n2, wi)
            if offsets:
                return _format_shift_offsets(offsets, n2)
        return (f"Shift/Indentation Error: {n1}\u00d7{n2}={correct} \u2192 wrote {wr or wi} "
                f"(partial row not indented)")
    if code == "M18":
        # Phase 2: find combined drop + shift
        if wi is not None and n_digits(n2) >= 2:
            drop_set, offsets = _find_combined_match(n1, n2, wi)
            if drop_set and offsets:
                return f"{_format_shift_offsets(offsets, n2)}; {_format_drop_carries(drop_set, n2)}"
        return f"Carry + Shift Error: {n1}\u00d7{n2}={correct} \u2192 wrote {wr or wi}"
    if code == "M19":
        return (f"Carry-Write Swap: {n1}\u00d7{n2}={correct} \u2192 writes tens digit, "
                f"carries units digit \u2192 {wr or wi}")
    if code == "M20":
        return "Carry propagation confusion: write digit re-used as carry-in"
    if code == "M21":
        # Whole-problem identity: n1==n2 and the learner wrote n1.
        if n1 == n2 and wi is not None and wi == n1:
            return (f"Same-Digit Identity (whole problem): {n1}\u00d7{n2}={correct}, "
                    f"wrote {wr or wi} \u2014 applied n\u00d7n=n to the whole problem")
        # Sub-step identity: name the column(s) where a digit equals the row digit.
        cols = _same_digit_identity_columns(n1, n2)
        if cols:
            parts = []
            for d, place, rowdesc in cols:
                w = f"the {place} column" + (f" of the {rowdesc} partial product" if rowdesc else "")
                parts.append(f"{d}\u00d7{d}={d} at {w}")
            return (f"Same-Digit Identity (sub-step): applied " + "; ".join(parts) +
                    f" in {n1}\u00d7{n2}={correct} (wrote {wr or wi})")
        return f"Same-Digit Identity: {n1}\u00d7{n2}={correct}, wrote {wr or wi} instead"
    if code == "M22":
        return (f"LTR Direction Error: {n1}\u00d7{n2}={correct} \u2192 wrote {wr or wi} "
                f"(drops final carry)")
    if code == "M23":
        # Phase 2: LTR + shift
        if wi is not None and n_digits(n2) >= 2:
            offsets = _find_shift_offset_match(n1, n2, wi, ltr=True)
            if offsets:
                return f"LTR direction (drop final carry); {_format_shift_offsets(offsets, n2)}"
        return f"LTR + Shift Error: {n1}\u00d7{n2}={correct} \u2192 wrote {wr or wi}"
    if code == "M24":
        # Phase 2: LTR + drop + shift
        if wi is not None and n_digits(n2) >= 2:
            drop_set, offsets = _find_combined_match(n1, n2, wi, ltr=True)
            if drop_set and offsets:
                return (f"LTR direction (drop final carry); "
                        f"{_format_shift_offsets(offsets, n2)}; "
                        f"{_format_drop_carries(drop_set, n2)}")
        return f"LTR + Carrying + Shift Error: {n1}\u00d7{n2}={correct} \u2192 wrote {wr or wi}"
    if code == "M25":
        return f"Trailing-Zero Prefix-1: trailing 0 dropped, '1' prepended \u2192 {wr or wi}"
    if code == "M26":
        # Phase 2: render the row breakdown
        if n1 >= 10 and n2 >= 10:
            n2_units = n2 % 10
            n2_tens = (n2 // 10) % 10
            n1_tens = (n1 // 10) % 10
            row1 = n1 * n2_units
            row2 = n1_tens * n2_tens * 10
            return (f"Tens-Row Tens-Digit-Only: Row1={n1}\u00d7{n2_units}={row1}, "
                    f"Row2=only {n1_tens}\u00d7{n2_tens}\u00d710={row2} \u2192 {row1+row2}")
        return f"Tens-Row Tens-Digit-Only: Row2 used only matching-digit product \u2192 {wr or wi}"
    if code == "M27":
        return f"Column-wise Mul: digits multiplied column-wise, concatenated \u2192 {wr or wi}"
    if code == "M28":
        # Phase 2: render units step + tens step
        if 10 <= n1 < 100 and 1 <= n2 < 10:
            n1_u = n1 % 10
            n1_t = n1 // 10
            units_step = n1_u * n2
            units_digit = units_step % 10
            carry = units_step // 10
            tens_step = n1_t + n2 + carry
            return (f"Tens-Step Addition Error: units {n1_u}\u00d7{n2}={units_step} "
                    f"(write {units_digit}, carry {carry}); "
                    f"tens: {n1_t}+{n2}+{carry}={tens_step} (added, not multiplied) "
                    f"\u2192 {tens_step*10+units_digit}")
        return (f"Tens-Step Addition Error: tens step used addition instead of "
                f"multiplication \u2192 {wr or wi}")
    if code == "M29":
        # Phase 1: figure out which leading-digit pattern matched
        if n2 >= 10:
            l_n2 = n2 // 10
            u_n2 = n2 % 10
            if wi == n1 * l_n2 + u_n2:
                return (f"Mul-Leading+Add-Trailing: {n1}\u00d7{l_n2}={n1*l_n2}, "
                        f"then +{u_n2} \u2192 {wi}")
        if n1 >= 10:
            l_n1 = n1 // 10
            u_n1 = n1 % 10
            if wi == n2 * l_n1 + u_n1:
                return (f"Mul-Leading+Add-Trailing: {n2}\u00d7{l_n1}={n2*l_n1}, "
                        f"then +{u_n1} \u2192 {wi}")
        return (f"Mul-Leading+Add-Trailing: multiplied leading digits, "
                f"added trailing \u2192 {wr or wi}")
    if code == "M30":
        cs = str(correct)
        if wi is not None and str(wi) and str(wi) in cs:
            return (f"Truncated Answer: wrote first {len(str(wi))} digit(s) of "
                    f"{correct} \u2192 {wr or wi}")
        return f"Truncated Answer: wrote partial digits of {correct} \u2192 {wr or wi}"
    if code == "M31":
        return f"Operand Concat: wrote '{n1}' and '{n2}' side-by-side \u2192 {wr or wi}"
    if code == "M32":
        rn1 = _reverse_int(n1)
        return f"Reversed N1: used {rn1}\u00d7{n2}={rn1*n2} instead of {n1}\u00d7{n2}"
    if code == "M33":
        # Phase 2: render the digit-by-digit breakdown
        try:
            from utils import row_concat_digit_mul
            if n_digits(n2) >= 2:
                n2_digits = [int(d) for d in str(n2)[::-1]]   # rtl
                n1_digits = [int(d) for d in str(n1)[::-1]]   # rtl
                row_strs = []
                for d2 in n2_digits:
                    products = [f"{d1}\u00d7{d2}={d1*d2}" for d1 in n1_digits]
                    row_concat = "".join(str(d1*d2) for d1 in reversed(n1_digits))
                    row_strs.append(f"[{','.join(products)}\u2192'{row_concat}']")
                return (f"Row-Concat Digit-Mul (no carry): "
                        f"{' | '.join(row_strs)} concat\u2192{wi}")
        except Exception:
            pass
        return (f"Row-Concat Digit-Mul (no carry): rows concatenated as strings "
                f"\u2192 {wr or wi}")
    if code == "M34":
        # Phase 1: identify leading × units pattern
        if n1 >= 10:
            l_n1 = int(str(n1)[0])
            u_n2 = n2 % 10
            product = l_n1 * u_n2
            if int(str(product) + str(u_n2)) == wi:
                return (f"Leading\u00d7Units+Append: leading({n1})={l_n1}, "
                        f"units({n2})={u_n2} \u2192 {l_n1}\u00d7{u_n2}={product}, "
                        f"append {u_n2} \u2192 {wi}")
        if n2 >= 10:
            l_n2 = int(str(n2)[0])
            u_n1 = n1 % 10
            product = l_n2 * u_n1
            if int(str(product) + str(u_n1)) == wi:
                return (f"Leading\u00d7Units+Append: leading({n2})={l_n2}, "
                        f"units({n1})={u_n1} \u2192 {l_n2}\u00d7{u_n1}={product}, "
                        f"append {u_n1} \u2192 {wi}")
        return (f"Leading\u00d7Units+Append: leading digit \u00d7 units digit, "
                f"append units \u2192 {wr or wi}")
    if code == "M35":
        # Phase 1: show per-step mod-10 computation
        d_n2 = n2 % 10 if n2 >= 10 else n2
        n1_digits_rtl = [int(c) for c in str(n1)[::-1]]
        parts = [f"{d}\u00d7{d_n2}%10={(d*d_n2)%10}" for d in n1_digits_rtl]
        return f"Row1 Carry-Dropped: {', '.join(parts)} \u2192 assembled \u2192 {wi}"
    if code == "M36":
        # Phase 1: identify which digit was used
        if wi is not None:
            for d_str in str(n1):
                if int(d_str) > 0 and n2 * int(d_str) == wi:
                    return (f"Partial Product (N2 \u00d7 digit '{d_str}' of N1 = "
                            f"{n2}\u00d7{d_str} = {wi})")
            for d_str in str(n2):
                if int(d_str) > 0 and n1 * int(d_str) == wi:
                    return (f"Partial Product (N1 \u00d7 digit '{d_str}' of N2 = "
                            f"{n1}\u00d7{d_str} = {wi})")
        return f"Partial Product: only one digit used; rest ignored \u2192 {wr or wi}"
    if code == "M37":
        ds1, ds2 = _digit_sum(n1), _digit_sum(n2)
        if wi == ds1 * n2:
            return f"Digit Sum Error: digitSum(N1) \u00d7 N2 = {ds1}\u00d7{n2} = {wi}"
        if wi == n1 * ds2:
            return f"Digit Sum Error: N1 \u00d7 digitSum(N2) = {n1}\u00d7{ds2} = {wi}"
        if wi == ds1 * ds2:
            return f"Digit Sum Error: digitSum(N1) \u00d7 digitSum(N2) = {ds1}\u00d7{ds2} = {wi}"
        return f"Digit Sum Error: digit-sum substitution \u2192 {wr or wi}"
    if code == "M38":
        ds1, ds2 = _digit_sum(n1), _digit_sum(n2)
        return f"All-Digit Sum: digitSum({n1})+digitSum({n2})={ds1+ds2} \u2192 wrote {wr or wi}"
    if code == "M39":
        if wi and correct and wi > correct and correct > 0:
            ratio = wi // correct
            zeros = len(str(ratio)) - 1 if ratio > 1 else 0
            return f"Place Value Error: answer \u00d7 {ratio} (extra {zeros} zero(s))"
        return f"Place Value Error: {wr or wi} differs from {correct} by power-of-10"
    if code == "M40":
        for delta in (1, -1, 2, -2):
            if wi == n1 * (n2 + delta):
                sign = "+" if delta > 0 else "-"
                return f"Wrong Multiplier: used N2{sign}{abs(delta)} \u2192 {n1}\u00d7{n2+delta} = {wi}"
            if wi == (n1 + delta) * n2:
                sign = "+" if delta > 0 else "-"
                return f"Wrong Multiplier: used N1{sign}{abs(delta)} \u2192 {n1+delta}\u00d7{n2} = {wi}"
        return f"Wrong Multiplier: adjacent table-fact recalled \u2192 {wr or wi}"
    if code == "M41":
        return f"Digit Reversal of Correct Answer ({correct} \u2192 {wr or wi})"
    if code == "M42":
        return "Final carry replaced by multiplier N2 (leading digit error)"
    if code == "M43":
        return "Digit assembly order error: correct digits, wrong place-value sequence"
    if code == "M44":
        if wi is not None and correct > 0:
            pct = abs(wi - correct) / correct * 100
            return f"Near Miss ({pct:.1f}% off)"
        return "Near Miss (small arithmetic slip)"
    if code == "M45":
        # Phase 1: row-result with order
        if n2 >= 10:
            row1 = n1 * (n2 % 10)
            row2 = n1 * (n2 // 10)
            if int(str(row2) + str(row1)) == wi:
                return (f"Row-Result Concat (tens-row first): {n1}\u00d7{n2}, "
                        f"row results [{row2}+{row1}] \u2192 concat \u2192 {wi}")
            if int(str(row1) + str(row2)) == wi:
                return (f"Row-Result Concat (units-row first): {n1}\u00d7{n2}, "
                        f"row results [{row1}+{row2}] \u2192 concat \u2192 {wi}")
        return f"Row-Result Concat: row totals concatenated as strings \u2192 {wr or wi}"
    if code == "M46" or code == "UNCLASSIFIED_ERROR":
        return "Other / Unclassified"
    if code == "CORRECT":
        return "(no error \u2014 correct answer)"
    return f"({code})"

# ---------------------------------------------------------------------------
# Cascade order (M01 → M02 → ... → M46 sequential; v14.2 dropped old M46)
# ---------------------------------------------------------------------------

MULTIPLICATION_CASCADE_ORDER: list[str] = [f"M{i:02d}" for i in range(1, 47)]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ClassifyResult:
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
# ---------------------------------------------------------------------------

def _rule_M01(s: dict) -> bool:
    """
    M01 RANDOM_OR_INVALID: raw is non-numeric / negative / repeated-digit mash
    (>=4 identical consecutive digits) OR non-parseable.

    Deferral: the "repeated-digit mash" branch defers to M02-M45 if any of them
    explain the response. The intent of the mash branch is to catch keyboard-mashing,
    but a legitimate (if wrong) answer like 6666 to 22×33 would technically satisfy
    the >=4-identical-consecutive-digits condition. To avoid false positives, the
    mash branch only fires when no procedural rule explains the response.
    The non-parseable branch (wi is None) is handled by the cascade-level fast path
    in classify(), so it doesn't reach this predicate.
    """
    if s["wi"] is None:
        return True  # safety; classify() typically handles this earlier
    raw = s["raw"]
    if raw is not None and raw.isdigit():
        # >=4 identical consecutive digits
        for i in range(len(raw) - 3):
            if raw[i] == raw[i+1] == raw[i+2] == raw[i+3]:
                # Defer if any other rule (M02 - M45) explains this response
                for other in MULTIPLICATION_CASCADE_ORDER[1:-1]:  # skip M01 and M46 (the fallback)
                    if _PREDICATES[other](s):
                        return False
                return True
    return False


def _rule_M02(s: dict) -> bool:
    """
    M02 ZERO_ANSWER: w == 0 (and at least one operand is non-zero).

    v14.6: Added deferral to M05 WRONG_OP_SUBTRACTION. When N1==N2 and wi==0,
    BOTH M02 (zero answer) and M05 (subtraction: |N1-N2|=0) fire. M05 is the
    more specific diagnosis — it explains WHY the kid wrote 0 (used
    subtraction), whereas M02 only describes the symptom (the answer is 0).
    When both fire, the subtraction story is more pedagogically actionable.

    Corpus impact: ~24 rows / ~1,595 freq move from M02 to M05. Examples:
    5×5='0', 2×2='0', 3×3='0', 7×7='0', 4×4='0'.
    """
    if s["wi"] is None: return False
    if s["wi"] != 0: return False
    # If both operands are zero, the answer 0 is correct, not M02
    if s["n1"] == 0 and s["n2"] == 0: return False
    # If one operand is zero, the correct answer IS 0 — also not M02
    if s["correct"] == 0: return False
    # v14.6: defer to M05 (subtraction explains the zero specifically)
    if _PREDICATES["M05"](s):
        return False
    return True


def _rule_M03(s: dict) -> bool:
    """
    M03 ZERO_PROPERTY_ERROR
    Whole-problem: (N2==0 AND w==N1) OR (N1==0 AND w==N2).
    Sub-step (at least one multi-digit operand has a 0 digit):
        Simulate with zero_property_substep perturbation; if simulated == w, fires.

    v14.2: Sub-step branch extended from "n1 >= 10 AND n2 >= 10" to
    "n1 >= 10 OR n2 >= 10". This catches 2D×1D and 3D×1D cases like
    30×4='124' (kid did 0×4=4 in tens column — zero-property), which
    previously fell through to M15 STEP_WRONG_MULTIPLIER (wrong remediation).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # Whole-problem
    if n2 == 0 and wi == n1 and n1 != 0: return True
    if n1 == 0 and wi == n2 and n2 != 0: return True
    # Sub-step: at least one operand multi-digit, and a 0 digit somewhere
    if n1 >= 10 or n2 >= 10:
        if 0 in digits(n1) or 0 in digits(n2):
            sim = long_multiply_simulate(n1, n2, zero_property_substep=True)
            if sim == wi:
                return True
    return False


def _rule_M04(s: dict) -> bool:
    """M04 WRONG_OP_ADDITION: w == N1 + N2."""
    if s["wi"] is None: return False
    return s["wi"] == s["n1"] + s["n2"]


def _rule_M05(s: dict) -> bool:
    """M05 WRONG_OP_SUBTRACTION: w == |N1 - N2|."""
    if s["wi"] is None: return False
    return s["wi"] == abs(s["n1"] - s["n2"])


def _rule_M06(s: dict) -> bool:
    """
    M06 WRONG_OP_DIVISION
    (N2>0 AND N1%N2==0 AND w==N1//N2) OR (N1>0 AND N2%N1==0 AND w==N2//N1).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n2 > 0 and n1 % n2 == 0 and wi == n1 // n2 and wi != 0:
        return True
    if n1 > 0 and n2 % n1 == 0 and wi == n2 // n1 and wi != 0:
        return True
    return False


def _rule_M07(s: dict) -> bool:
    """M07 PARTIAL_OPERAND_COPY: w in {N1, N2} and N1 != N2."""
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if n1 == n2: return False
    if wi == s["correct"]: return False
    return wi == n1 or wi == n2


def _rule_M08(s: dict) -> bool:
    """
    M08 DIGIT_CONCAT_RTL: each digit of N1 multiplied by N2 individually;
    products joined RTL as text.

    Spec example uses single-digit N2 (897×8 → 567264). When N2 is multi-digit,
    the "each digit × N2" interpretation overlaps so heavily with M45
    (row-result-concat) that the two rules become indistinguishable. To avoid
    false positives, M08 fires only when N2 is single-digit.
    Symmetric branch (digit-of-N2 × N1) fires only when N1 is single-digit.

    Per v11 reviewer verdict (call #3, REJECTED): no deferral to M32. The same
    misconception (digit-concat-RTL) applies whether or not the resulting string
    coincidentally equals rev(N1)×N2. For 23×4=128, the procedure (3×4=12, then
    2×4=8 → "128") is the same digit-concat misconception as 897×8=567264.
    Splitting the diagnosis across M08 and M32 based on a coincidental
    arithmetic overlap (only present for some 2-digit×1-digit cases) would
    fragment the same underlying misconception across two codes.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # Primary: each digit of N1 × N2 (requires single-digit N2)
    if n2 < 10 and n1 >= 10 and wi == digit_concat_rtl_product(n1, n2):
        return True
    # Symmetric: each digit of N2 × N1 (requires single-digit N1)
    if n1 < 10 and n2 >= 10 and wi == digit_concat_rtl_product(n2, n1):
        return True
    return False


def _rule_M09(s: dict) -> bool:
    """
    M09 DIGIT_CONCAT_LTR: same as M08 but joined LTR.
    Same single-digit-multiplier restriction as M08.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if n2 < 10 and n1 >= 10 and wi == digit_concat_ltr_product(n1, n2):
        return True
    if n1 < 10 and n2 >= 10 and wi == digit_concat_ltr_product(n2, n1):
        return True
    return False


# Helper: enumerate the (row, pos) coordinates of every multiplication step
def _carry_in_at_step(n1: int, n2: int, j: int, i: int) -> int:
    """
    Compute carry_in to step (j, i) in standard long multiplication.
    j = row (which digit of n2), i = column (which digit of n1).

    Within row j, columns are processed LTR (units col 0 first). Each step
    computes (d1[k] * d2[j] + carry), writes the ones digit, and propagates
    the tens digit as carry_in to column k+1.

    Used by M16 (v14.3) to skip steps that have no carry_in — a "phantom
    carry add" misconception is incoherent when there's no carry to mis-add.
    """
    d2j = (n2 // 10**j) % 10
    if i == 0:
        return 0
    carry = 0
    n1_digs = digits_rtl(n1)
    for k in range(i):
        if k >= len(n1_digs):
            d1 = 0
        else:
            d1 = n1_digs[k]
        prod = d1 * d2j + carry
        carry = prod // 10
    return carry


def _step_coords(n1: int, n2: int) -> list[tuple[int, int]]:
    coords = []
    n1_digits = n_digits(n1)
    for j in range(n_digits(n2)):
        for i in range(n1_digits):
            coords.append((j, i))
    return coords


def _add_with_drops(rows: list[int], drop_cols: set[int]) -> int:
    """Column-wise addition of multiple integers, dropping carries at specified columns.
    drop_cols = set of column indices where the carry OUT of that column is set to 0.
    Used by M10 to simulate 'kid forgot to carry in the addition step'."""
    if not rows:
        return 0
    max_col = max(len(str(abs(r))) for r in rows) + 2
    carry = 0
    digits = []
    for col in range(max_col):
        col_sum = carry
        for r in rows:
            col_sum += (r // (10 ** col)) % 10
        digits.append(col_sum % 10)
        new_carry = col_sum // 10
        carry = 0 if col in drop_cols else new_carry
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
    return sum(d * 10**i for i, d in enumerate(digits))


def _partial_product_rows(n1: int, n2: int) -> list[int]:
    """Shifted partial-product rows for the standard long-multiplication algorithm."""
    rows = []
    for j in range(n_digits(n2)):
        d_j = (n2 // 10**j) % 10
        rows.append(n1 * d_j * 10**j)
    return rows


def _find_natural_carry_cols(rows: list[int]) -> list[int]:
    """Columns in the addition where a carry would naturally be generated."""
    if not rows:
        return []
    max_col = max(len(str(abs(r))) for r in rows) + 1
    carry = 0
    natural = []
    for col in range(max_col):
        col_sum = carry
        for r in rows:
            col_sum += (r // (10 ** col)) % 10
        if col_sum >= 10:
            natural.append(col)
        carry = col_sum // 10
    return natural


def _find_intra_row_drop_match(n1: int, n2: int, wi: int):
    """Search for intra-row (multiplication-step) carry drops matching wi. Returns matching set or None."""
    coords = _step_coords(n1, n2)
    if not coords or len(coords) > 8:
        return None
    for mask in range(1, 1 << len(coords)):
        drop_set = {coords[k] for k in range(len(coords)) if mask & (1 << k)}
        if long_multiply_simulate(n1, n2, drop_carries=drop_set) == wi:
            return drop_set
    return None


def _find_addition_drop_match(n1: int, n2: int, wi: int):
    """Search for addition-step carry drops matching wi (v14.1 extension).
    Returns matching set of column indices, or None."""
    if n_digits(n2) < 2:
        return None  # Single-row problem: no addition step
    rows = _partial_product_rows(n1, n2)
    natural = _find_natural_carry_cols(rows)
    if not natural or len(natural) > 8:
        return None
    cols = list(natural)
    for mask in range(1, 1 << len(cols)):
        drop_cols = {cols[k] for k in range(len(cols)) if mask & (1 << k)}
        if _add_with_drops(rows, drop_cols) == wi:
            return drop_cols
    return None


def _format_addition_drops(drop_cols: set) -> str:
    """Render addition carry drops as 'Addition step: missing carry between X and Y cols'."""
    places = ["units", "tens", "hundreds", "thousands", "ten-thousands", "lakhs"]
    parts = []
    for col in sorted(drop_cols):
        f = places[col] if col < len(places) else f"col{col}"
        t = places[col+1] if (col+1) < len(places) else f"col{col+1}"
        parts.append(f"between {f} and {t}")
    return "Addition step: missing carry " + "; ".join(parts)


def _rule_M10(s: dict) -> bool:
    """
    M10 CARRY_IGNORED (renamed from CARRYING_ERROR in v14.1)

    Learner ignored (failed to propagate) one or more carries during the long
    multiplication procedure. Two cognitive sub-types are simulated:

    Type A — INTRA-ROW (multiplication step) carry ignored:
        During a partial-product row, the carry from one column to the next
        is dropped. Result: the row is short by the carry value × position.
        Possible in any problem with multi-digit factors.

    Type B — ADDITION step carry ignored (v14.1 extension):
        When summing partial-product rows, a carry between adjacent columns
        of the sum is dropped. Possible only when N2 is multi-digit (otherwise
        there's only one partial-product row and no addition step).

    For 2D×2D problems, the SAME wi often matches both Type A and Type B
    interpretations (e.g., 65×13='745' is reachable by either dropping the
    tens→hundreds carry in Row 1's multiplication step OR the hundreds-column
    carry in the addition step). This rule fires for either match; the
    Detailed Error Label discloses which interpretation(s) match.
    """
    if s["wi"] is None: return False
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    if s["wi"] == s["correct"]: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # Type A: intra-row multiplication carry drops
    if _find_intra_row_drop_match(n1, n2, wi) is not None:
        return True
    # Type B: addition-step carry drops (v14.1, multi-row only)
    if n_digits(n2) >= 2 and _find_addition_drop_match(n1, n2, wi) is not None:
        return True
    return False



def _rule_M11(s: dict) -> bool:
    """
    M11 CARRY_ADD_BEFORE_MUL
    Single-digit N2 only. Simulate RTL: step = (d + carry_in) × N2 instead of d × N2 + carry_in.
    Guard: N1 >= 10, N2 < 10. Fires after M10.
    """
    if s["wi"] is None: return False
    # 1D×1D guard (added to fix step-machinery false-positives)
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n1 < 10 or n2 >= 10: return False
    sim = long_multiply_simulate(n1, n2, carry_add_before_mul=True)
    return sim == wi


def _rule_M12(s: dict) -> bool:
    """
    M12 TENS_NOT_MULTIPLIED (new in v14.0; split from old M12 CARRY_ADD_N2_SKIP_DIGIT)
    Single-digit N2, multi-digit N1. Units step is normal; for upper columns the
    learner just writes N2 (effectively skipping multiplication entirely) because
    no carry was generated to engage with.

    Cognitive story: kid multiplied the units column once, then for upper columns
    has no procedural model. They don't add a carry (there is none); they just
    write N2 in each upper column. The misconception is that multiplication is
    a one-time operation rather than a per-column procedure.

    Boundary: this rule fires only when (N1 % 10) * N2 < 10 (units step has no
    carry). When the units step produces a carry, the observationally-identical
    answer comes from M13 CARRY_ADD_TO_MULTIPLIER — different misconception,
    different remediation.

    Example: 22 × 4 → kid wrote '48'
        Step 0 (units): 2 × 4 = 8 → write 8, carry 0
        Step 1 (tens): kid wrote 4 (which is N2)
        Result: '48' (tens column has no multiplication)
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (multi-step machinery does not apply to trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n1 < 10 or n2 >= 10: return False
    # Boundary guard: only fires when units step has no carry
    if (n1 % 10) * n2 >= 10:
        return False
    sim = long_multiply_simulate(n1, n2, carry_add_n2_skip=True)
    return sim == wi


def _rule_M13(s: dict) -> bool:
    """
    M13 CARRY_ADD_TO_MULTIPLIER (formerly M12 CARRY_ADD_N2_SKIP_DIGIT pre-v14)
    Single-digit N2, multi-digit N1. Units step normal; for upper steps the
    learner ADDS the carry to N2 instead of multiplying the digit by N2.

    Cognitive story: the kid sees a leftover carry from the units step and,
    confused about what to do with it, adds it to the multiplier (N2). They
    ARE engaging with the carry; their procedural rule is just wrong.

    Boundary: this rule fires only when the units step produces a carry
    (i.e., (N1 % 10) * N2 >= 10). When the units step has no carry,
    "carry_in + N2 = 0 + N2 = N2" — observationally identical to "kid just
    wrote N2 in upper columns without engaging with carries at all" — which
    is the M12 TENS_NOT_MULTIPLIED misconception, with different remediation.
    See M12 docstring for the distinction.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n1 < 10 or n2 >= 10: return False
    # v14.0: require units step to actually produce a carry. When (N1 % 10) * N2 < 10,
    # there's no carry to add to N2 — the misconception reduces to M12 TENS_NOT_MULTIPLIED.
    if (n1 % 10) * n2 < 10:
        return False
    sim = long_multiply_simulate(n1, n2, carry_add_n2_skip=True)
    return sim == wi


def _rule_M14(s: dict) -> bool:
    """
    M14 STEP_OP_ADDITION
    At exactly one step, learner uses d1+d2_row instead of d1*d2_row.

    Deferral: defers to M15, M16, M19, M20, M21, M28 if any of them also fire
    (v15.0: removed "M11" from this list — M11 fires earlier in the cascade so the
    defer was dead code).
    M14 (step-uses-addition) and the more specific algorithm-misconception rules
    can coincidentally produce the same response. The spec's M19 example
    (99×9=828) coincidentally satisfies M14's structural test but is meant to
    be M19. Similarly for the "named misconception" rules — they are more
    specific diagnoses than the generic "one step used + instead of ×" pattern.
    """
    if s["wi"] is None: return False
    # 1D×1D guard (added to fix step-machinery false-positives)
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    coords = _step_coords(n1, n2)
    matched = False
    for (j, i) in coords:
        d1 = digits_rtl(n1)[i]
        d2_row = digits_rtl(n2)[j]
        if d1 + d2_row == d1 * d2_row:
            continue
        sim = long_multiply_simulate(n1, n2, step_op_add=(j, i))
        if sim == wi:
            matched = True
            break
    if not matched:
        return False
    # Defer to more specific algorithm-misconception rules.
    # v15.0: removed "M11" from defer list — M11 is at cascade pos 10
    # (earlier than M14 at pos 13), so if M11 fires the cascade stops at M11
    # and M14 is never reached. The defer was dead code.
    for other in ("M15", "M16", "M19", "M20", "M21", "M28"):
        if _PREDICATES[other](s):
            return False
    return True


def _rule_M15(s: dict) -> bool:
    """
    M15 STEP_WRONG_MULTIPLIER
    At exactly one step, learner recalls (d1±1)*d2_row or (d1±2)*d2_row.

    Deferral: defers to M19, M20, M21 if any of them also fire. The spec's M21
    example (52×2=102) coincidentally satisfies M15 with delta=-1 but is meant
    to be M21. Similarly for M19, M20 — these are more specific diagnoses than
    the generic step-perturbation pattern.
    """
    if s["wi"] is None: return False
    # 1D×1D guard (added to fix step-machinery false-positives)
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    coords = _step_coords(n1, n2)
    matched = False
    for (j, i) in coords:
        for delta in (-2, -1, 1, 2):
            d1 = digits_rtl(n1)[i]
            if d1 + delta < 0:
                continue
            sim = long_multiply_simulate(n1, n2, step_mul_delta=(j, i, delta))
            if sim == wi:
                matched = True
                break
        if matched:
            break
    if not matched:
        return False
    # Defer to more specific named-misconception rules
    for other in ("M19", "M20", "M21"):
        if _PREDICATES[other](s):
            return False
    return True


def _rule_M16(s: dict) -> bool:
    """
    M16 STEP_CARRY_ADD_ERROR
    At exactly one step (r, p) WHERE carry_in > 0, the carry addition is wrong:
    step = d1*d2 + carry_in + delta. delta in {-3, -2, -1, 1, 2, 3}.

    v14.3: Added carry_in > 0 guard. Previously 63% of M16 frequency had
    carry_in = 0 at the perturbed step — meaning the predicate was firing on
    "phantom carry" interpretations where there was no carry to mis-add. The
    semantic "kid added the wrong carry" is incoherent when there's no carry,
    so these cases are now correctly excluded (they fall through to M44 NEAR_MISS
    if close-to-correct, or M46 UNCLASSIFIED otherwise).

    Deferral: defers to M19, M20, M21 (more specific named-misconceptions),
    M28 (tens-step-addition for 2-digit N1 × 1-digit N2 — more specific structural pattern),
    and M44 (near-miss — when |w-correct| ≤ 1 the response is more likely a fluency slip
    than a single-step carry-arithmetic error).
    """
    if s["wi"] is None: return False
    # 1D×1D guard (added to fix step-machinery false-positives)
    if n_digits(s["n1"]) == 1 and n_digits(s["n2"]) == 1:
        return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    coords = _step_coords(n1, n2)
    matched = False
    for (j, i) in coords:
        # v14.3: only fire when there's a real carry to mis-add.
        # When carry_in == 0, "added the wrong carry by delta" reduces to
        # "wrote a wrong product" — that's a fluency/recall slip (M15-like
        # territory), not a carry-arithmetic error.
        if _carry_in_at_step(n1, n2, j, i) == 0:
            continue
        for delta in (-3, -2, -1, 1, 2, 3):
            sim = long_multiply_simulate(n1, n2, step_carry_delta=(j, i, delta))
            if sim is not None and sim == wi and sim > 0:
                matched = True
                break
        if matched:
            break
    if not matched:
        return False
    for other in ("M19", "M20", "M21", "M28", "M44"):
        if _PREDICATES[other](s):
            return False
    return True


def _rule_M17(s: dict) -> bool:
    """
    M17 SHIFT_INDENTATION
    Simulation: w reachable when one or more partial-product rows are placed
    at wrong column offset.
    Guard: N2 must be multi-digit.

    Deferrals:
      - Defers to M45 (ROW_RESULT_CONCAT) when M45 also fires.

    v14.7: Removed defer to M37 (DIGIT_SUM_SUBSTITUTION). M37 branch 1
    (wi = N1 × digit_sum(N2)) is algebraically identical to M17 with
    shift_offsets=(0, 0, ..., 0) — every M37 branch-1 firing is also an
    M17 no-shift firing. Cognitive analysis showed "kid forgot to shift"
    (M17) is the simpler, more general diagnosis; "kid used digit-sum
    substitution" (M37) is a contrived re-framing of the same coincidence.
    M37 retains its other branches (digit_sum(N1) × N2 etc.) which M17
    cannot catch, so it remains a useful code for those cases.

    The fix also resolves an inconsistency: M23 (LTR_SHIFT) has no
    defer-to-M37 guard, so it was winning over M17 for the same kind of
    no-shift errors purely due to the guard asymmetry (e.g., 31×12='93'
    was M23, while 31×12='651' was M17 — both are shift errors).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    n_rows = n_digits(n2)
    max_off = n_rows + 2
    default = tuple(range(n_rows))
    matched = False
    if (max_off + 1) ** n_rows > 256:
        for r in range(n_rows):
            for off in range(max_off + 1):
                if off == r:
                    continue
                offsets = tuple(off if k == r else k for k in range(n_rows))
                sim = long_multiply_simulate(n1, n2, shift_offsets=offsets)
                if sim == wi:
                    matched = True
                    break
            if matched:
                break
    else:
        for offsets in iproduct(range(max_off + 1), repeat=n_rows):
            if offsets == default:
                continue
            sim = long_multiply_simulate(n1, n2, shift_offsets=offsets)
            if sim == wi:
                matched = True
                break
    if not matched:
        return False
    # v16: defer to M21 whole-problem identity (n×n=n). When n1==n2 and the
    # learner wrote n1, "the child thinks n×n=n" is a single misconception — far
    # simpler than positing multiple independent shift/carry slips that happen to
    # reproduce the operand exactly. Mirrors the guard M15/M16 already carry.
    if n1 == n2 and wi == n1:
        return False
    # v14.7: only defer to M45 (concat). M37 deferral removed.
    if _PREDICATES["M45"](s):
        return False
    return True


def _rule_M18(s: dict) -> bool:
    """
    M18 CARRYING_SHIFT: combination of M10 (carry ignored) and M17 (indentation error).
    Multi-digit N2 only.

    Deferrals:
      - Defers to M45 (ROW_RESULT_CONCAT) when M45 also fires (combined carry-miss
        + shift can coincide with row-result-concat for symmetric problems).

    v15.0: Removed defer-to-M37 for consistency with v14.7's M17 fix. M18 is the
    compound M10+M17 misconception; same logical relationship to M37 branch 1
    (digit-sum substitution) as M17 — the combined carry+shift interpretation
    is the simpler cognitive story than M37's contrived digit-sum re-framing.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    coords = _step_coords(n1, n2)
    if len(coords) > 6:
        return False
    n_rows = n_digits(n2)
    max_off = n_rows + 2
    default = tuple(range(n_rows))
    matched = False
    for mask in range(1, 1 << len(coords)):
        drop_set = {coords[k] for k in range(len(coords)) if mask & (1 << k)}
        for offsets in iproduct(range(max_off + 1), repeat=n_rows):
            if offsets == default:
                continue
            sim = long_multiply_simulate(n1, n2, drop_carries=drop_set, shift_offsets=offsets)
            if sim == wi:
                matched = True
                break
        if matched:
            break
    if not matched:
        return False
    # v16: defer to M21 whole-problem identity (n×n=n) — see _rule_M17.
    if n1 == n2 and wi == n1:
        return False
    if _PREDICATES["M45"](s):
        return False
    # v15.0: removed defer to M37 for consistency with v14.7's M17 fix.
    # M18 = M10 (carry-ignored) + M17 (shift) compound; same logical relationship
    # to M37 branch 1 (digit-sum substitution) as M17 has — the "kid forgot
    # to shift + drop carry" diagnosis is the simpler cognitive story than the
    # contrived "kid used digit-sum substitution" re-framing.
    return True


def _rule_M19(s: dict) -> bool:
    """
    M19 CARRY_WRITE_SWAP
    Single-digit N2, multi-digit N1. Three variants:
      (1) swap at all steps
      (2) swap only when carry_in == 0
      (3) swap only at first step
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n2 >= 10 or n1 < 10: return False
    # Variant 1: all steps
    if long_multiply_simulate(n1, n2, write_carry_swap=True) == wi:
        return True
    # Variant 2: only when carry_in == 0
    if long_multiply_simulate(n1, n2, write_carry_swap=True,
                              carry_swap_only_when_zero_carry_in=True) == wi:
        return True
    # Variant 3: only at first step
    if long_multiply_simulate(n1, n2, write_carry_swap=True,
                              carry_swap_first_step_only=True) == wi:
        return True
    return False


def _rule_M20(s: dict) -> bool:
    """
    M20 CARRY_PROPAGATION_CONFUSION
    Single-digit N2 (< 10), multi-digit N1. carry_in for step i+1 = write_digit at step i.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n2 >= 10 or n1 < 10: return False
    sim = long_multiply_simulate(n1, n2, carry_propagation_confusion=True)
    return sim == wi


def _rule_M21(s: dict) -> bool:
    """
    M21 SAME_DIGIT_IDENTITY
    Whole-problem: N1==N2 AND w==N1. The canonical "n×n=n identity confusion"
    pattern — applies to all sizes including 1D×1D (e.g. 4×4='4', 7×7='7').
    Sub-step (N1>=10): wherever d1==d2_row, learner writes that digit and carries 0.

    v14.5: Moved the 1D×1D guard below the whole-problem branch. Previously the
    guard sat at the top of the predicate and blocked the whole-problem check
    for 1D×1D inputs — even though the whole-problem branch was designed
    precisely for those cases. The guard is only needed to protect the
    step-machinery sub-step branch, which doesn't apply to 1D×1D inputs.

    Corpus impact (v14.4 → v14.5): ~13 rows / ~1,593 freq move into M21 from
    M40 (~833 freq), M30 (~431 freq), and M46 (~329 freq). Examples: 2×2='2',
    3×3='3', 4×4='4', 5×5='5', 7×7='7'.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    # Whole-problem branch: applies to all sizes (including 1D×1D).
    if n1 == n2 and wi == n1:
        return True
    # 1D×1D guard: only the step-machinery branch below has the false-positive
    # risk on trivial problems. The whole-problem branch is structurally safe.
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    # Sub-step: only fires if N1 >= 10
    if n1 >= 10:
        sim = long_multiply_simulate(n1, n2, same_digit_identity_substep=True)
        if sim == wi:
            return True
    return False


def _rule_M22(s: dict) -> bool:
    """M22 LTR_DIRECTION: w reachable when N1 digits processed LTR."""
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n_digits(n1) < 2: return False  # LTR vs RTL only differ for multi-digit N1
    # Try with both final-carry-dropped and final-carry-prepended options
    sim1 = long_multiply_simulate(n1, n2, ltr_direction=True)
    if sim1 == wi: return True
    sim2 = long_multiply_simulate(n1, n2, ltr_direction=True, final_carry_dropped=True)
    if sim2 == wi: return True
    return False


def _rule_M23(s: dict) -> bool:
    """
    M23 LTR_SHIFT: LTR direction + shift indentation. Multi-digit N2.
    Defers to M45 when M45 also fires.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    n_rows = n_digits(n2)
    max_off = n_rows + 2
    default = tuple(range(n_rows))
    matched = False
    for offsets in iproduct(range(max_off + 1), repeat=n_rows):
        if offsets == default:
            continue
        sim = long_multiply_simulate(n1, n2, ltr_direction=True, shift_offsets=offsets)
        if sim == wi:
            matched = True
            break
    if not matched:
        return False
    if _PREDICATES["M45"](s):
        return False
    return True


def _rule_M24(s: dict) -> bool:
    """
    M24 LTR_CARRYING_SHIFT: LTR + carry ignored + shift. Multi-digit N2.
    Defers to M45 when M45 also fires.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    coords = _step_coords(n1, n2)
    if len(coords) > 6: return False
    n_rows = n_digits(n2)
    max_off = n_rows + 2
    default = tuple(range(n_rows))
    matched = False
    for mask in range(1, 1 << len(coords)):
        drop_set = {coords[k] for k in range(len(coords)) if mask & (1 << k)}
        for offsets in iproduct(range(max_off + 1), repeat=n_rows):
            if offsets == default:
                continue
            sim = long_multiply_simulate(n1, n2, ltr_direction=True,
                                         drop_carries=drop_set, shift_offsets=offsets)
            if sim == wi:
                matched = True
                break
        if matched:
            break
    if not matched:
        return False
    if _PREDICATES["M45"](s):
        return False
    return True


def _rule_M25(s: dict) -> bool:
    """
    M25 TRAILING_ZERO_PREFIX1
    One operand ends in 0: learner drops trailing zero, multiplies, then prepends "1".
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    # N1 ends in 0
    if n1 % 10 == 0 and n1 > 0:
        reduced = n1 // 10
        candidate = int("1" + str(reduced * n2))
        if wi == candidate:
            return True
    # N2 ends in 0
    if n2 % 10 == 0 and n2 > 0:
        reduced = n2 // 10
        candidate = int("1" + str(n1 * reduced))
        if wi == candidate:
            return True
    return False


def _rule_M26(s: dict) -> bool:
    """
    M26 TENS_ROW_TENS_DIGIT_ONLY
    w == N1 * N2_units + N1_tens * N2_tens * 10
    (Row 2 uses only N1_tens × N2_tens instead of full N1 × N2_tens.)
    Implies N1 and N2 both have a tens-position.
    v19: guarded to 2-digit operands — the fixed two-row formula cannot represent
    a 3-row product, so on 3-digit operands it only matched degenerate candidates
    (e.g. 410x190='90'); now requires both operands in 10..99 (2-digit x 2-digit).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n1 < 10 or n2 < 10 or n1 >= 100 or n2 >= 100: return False
    n2_units = n2 % 10
    n2_tens = (n2 // 10) % 10
    n1_tens = (n1 // 10) % 10
    candidate = n1 * n2_units + n1_tens * n2_tens * 10
    return wi == candidate


def _rule_M27(s: dict) -> bool:
    """
    M27 COLUMN_WISE_MUL: matching position digits multiplied, results concatenated.
    """
    if s["wi"] is None: return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    candidate = column_wise_digit_mul(n1, n2)
    return candidate is not None and wi == candidate


def _rule_M28(s: dict) -> bool:
    """
    M28 TENS_STEP_ADDITION
    N1 is 2-digit, N2 is single-digit.
    Units step correct (N1_U × N2). Tens step = N1_T + N2 + carry instead of N1_T × N2 + carry.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if not (10 <= n1 < 100 and 1 <= n2 < 10): return False
    n1_u = n1 % 10
    n1_t = n1 // 10
    units_step = n1_u * n2
    units_digit = units_step % 10
    carry = units_step // 10
    tens_step = n1_t + n2 + carry
    candidate = tens_step * 10 + units_digit
    return wi == candidate


def _rule_M29(s: dict) -> bool:
    """
    M29 MUL_LEADING_ADD_TRAILING
    w == N1 * (N2 // 10) + (N2 % 10)  OR  w == (N1 // 10) * N2 + (N1 % 10).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n2 >= 10 and wi == n1 * (n2 // 10) + (n2 % 10):
        return True
    if n1 >= 10 and wi == (n1 // 10) * n2 + (n1 % 10):
        return True
    return False


def _rule_M30(s: dict) -> bool:
    """
    M30 TRUNCATED_ANSWER
    w == int(str(correct)[:k]) OR w == int(str(correct)[-k:].lstrip("0"))
    for some k < len(str(correct)).
    """
    if s["wi"] is None: return False
    correct = s["correct"]
    wi = s["wi"]
    if wi == correct: return False
    s_correct = str(correct)
    if wi == 0: return False  # Avoid trivial match via stripping
    for k in range(1, len(s_correct)):
        # Front truncation
        if str(wi) == s_correct[:k]:
            return True
        # Back truncation (with leading-zero strip)
        back = s_correct[-k:].lstrip("0")
        if back and str(wi) == back:
            return True
    return False


def _rule_M31(s: dict) -> bool:
    """M31 OPERAND_CONCATENATION: w == int(str(N1)+str(N2)) OR w == int(str(N2)+str(N1))."""
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    return wi == concat_int(n1, n2) or wi == concat_int(n2, n1)


def _rule_M32(s: dict) -> bool:
    """M32 REVERSED_N1: w == int(reversed(N1)) * N2."""
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n_digits(n1) < 2: return False  # reversal trivial for single-digit
    rev_n1 = int(str(n1)[::-1])
    if rev_n1 == n1: return False  # palindrome, not a real reversal
    return wi == rev_n1 * n2


def _rule_M33(s: dict) -> bool:
    """
    M33 ROW_CONCAT_DIGIT_MUL: multi-digit N2 only.
    For each digit of N2 (RTL), for each digit of N1 (RTL): compute d1*d2 as string,
    concatenate within row, concatenate rows.

    Deferral: defers to M45 if M45 also fires. The two rules can coincide for
    problems where each digit-product happens to equal the full row product
    (e.g. all single-digit-product results, no carries). M45 is the more
    pedagogically specific diagnosis.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    if wi != row_concat_digit_mul(n1, n2):
        return False
    if _PREDICATES["M45"](s):
        return False
    return True


def _rule_M34(s: dict) -> bool:
    """
    M34 LEAD_X_UNITS_APPEND_UNITS (renamed in v14.8 from LEADING_UNITS_APPEND)
    w == int(str(N1_leading * N2_units) + str(N2_units))

    Algorithm: take the leading (MSB) digit of N1, multiply by the units (LSB)
    digit of N2, then append the units digit of N2 to the result.
    Example: 30×24 → 3×4=12, append "4" → "124".
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n1 < 10: return False  # need a leading (non-units) digit
    # spec example: 30×24 → 3×4=12, append "4" → 124. So N1_leading is the LEADING digit (MSB).
    n1_leading = digits(n1)[0]  # MSB
    n2_units = n2 % 10
    candidate = int(str(n1_leading * n2_units) + str(n2_units))
    return wi == candidate


def _rule_M35(s: dict) -> bool:
    """
    M35 ROW1_CARRY_DROPPED: multi-digit N2. w = row 0 (N1 × N2_units) with all
    carries dropped at each digit step.

    v14.8: Added carry-needed guard. Previously M35 fired even when N1 ×
    units(N2) had no carry at any digit step (e.g., 33×12='66' where 3×2=6
    has no carry to drop). For those rows, the "carry dropped" semantic is
    vacuous — wi just equals N1 × units(N2), which is more accurately
    M36 PARTIAL_PRODUCT ("kid used only one digit of N2"). M35 now fires only
    when at least one digit step in row 0 actually has a carry, so "dropped"
    has meaning.

    Corpus impact: ~13 rows / ~114 freq move M35 → M36 (no-carry cases).
    Genuine carry-dropped cases (e.g., 27×34='88' where 7×4=28 has a carry
    that's dropped) remain M35.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    # 1D×1D guard (added to fix step-machinery false-positives on trivial problems)
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return False
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    # v14.8: require an actual carry in the units row.
    n2_units = n2 % 10
    has_carry = any(d * n2_units >= 10 for d in digits_rtl(n1))
    if not has_carry:
        return False
    sim = long_multiply_simulate(n1, n2, row1_carry_dropped=True)
    return sim == wi


def _rule_M36(s: dict) -> bool:
    """
    M36 PARTIAL_PRODUCT
    w == N1 × d where d is a single digit of N2 and d > 1, OR
    w == N2 × d where d is a single digit of N1 and d > 1.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    for d in set(digits(n2)):
        if d > 1 and wi == n1 * d:
            return True
    for d in set(digits(n1)):
        if d > 1 and wi == n2 * d:
            return True
    return False


def _rule_M37(s: dict) -> bool:
    """
    M37 DIGIT_SUM_SUBSTITUTION
    w == N1 × digitSum(N2), OR w == digitSum(N1) × N2, OR w == digitSum(N1) × digitSum(N2).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    ds1 = digit_sum(n1)
    ds2 = digit_sum(n2)
    if wi == n1 * ds2 and ds2 != n2: return True
    if wi == ds1 * n2 and ds1 != n1: return True
    if wi == ds1 * ds2 and (ds1 != n1 or ds2 != n2): return True
    return False


def _rule_M38(s: dict) -> bool:
    """
    M38 ALL_DIGIT_SUM
    w == digit_sum(N1) + digit_sum(N2). At least one operand must be multi-digit
    (otherwise the result coincides with N1+N2, which is M04). Spec also asks
    that w != N1+N2 (M04 already would have fired) and w != |N1-N2| (M05).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n1 < 10 and n2 < 10: return False
    if wi == n1 + n2: return False
    if wi == abs(n1 - n2): return False
    return wi == digit_sum(n1) + digit_sum(n2)


def _rule_M39(s: dict) -> bool:
    """
    M39 PLACE_VALUE_ERROR
    w == correct × 10^k, OR (correct % 10^k == 0 AND w == correct // 10^k), for k in {1,2,3}.
    """
    if s["wi"] is None: return False
    correct = s["correct"]
    wi = s["wi"]
    if wi == correct: return False
    if correct == 0: return False
    for k in (1, 2, 3):
        if wi == correct * (10 ** k):
            return True
        if correct % (10 ** k) == 0 and wi == correct // (10 ** k) and wi > 0:
            return True
    return False


def _rule_M40(s: dict) -> bool:
    """
    M40 WRONG_MULTIPLIER
    Guard: at least one of N1, N2 single-digit.
    w == N1 × (N2±k) OR w == N2 × (N1±k) for k in {1, 2}.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n1 >= 10 and n2 >= 10: return False
    for k in (-2, -1, 1, 2):
        if (n2 + k) >= 0 and wi == n1 * (n2 + k):
            return True
        if (n1 + k) >= 0 and wi == n2 * (n1 + k):
            return True
    return False


def _rule_M41(s: dict) -> bool:
    """M41 DIGIT_REVERSAL_ANSWER: str(w) == str(correct)[::-1]."""
    if s["wi"] is None: return False
    correct, wi = s["correct"], s["wi"]
    if wi == correct: return False
    if str(wi) == str(correct)[::-1] and str(wi) != str(correct):
        # Skip palindromic-correct cases where reversal is the same number
        return True
    return False


def _rule_M42(s: dict) -> bool:
    """
    M42 FINAL_CARRY_REPLACED_BY_N2
    Single-digit N2. len(w) == len(correct), str(w)[1:] == str(correct)[1:],
    str(w)[0] == str(N2), str(w)[0] != str(correct)[0].
    """
    if s["wi"] is None: return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    if n2 >= 10: return False
    sw, sc = str(wi), str(correct)
    if len(sw) != len(sc): return False
    if len(sw) < 2: return False
    if sw[1:] != sc[1:]: return False
    if int(sw[0]) != n2: return False
    if int(sw[0]) == int(sc[0]): return False
    return True


def _rule_M43(s: dict) -> bool:
    """
    M43 DIGIT_ASSEMBLY_ORDER
    sorted(str(w)) == sorted(str(correct)) AND w != correct.
    Guards: same length, w > 0.
    """
    if s["wi"] is None: return False
    # v13.1: 1D×1D problems have no multi-step procedure; this rule does not apply.
    if n_digits(s["n1"]) <= 1 and n_digits(s["n2"]) <= 1: return False
    correct, wi = s["correct"], s["wi"]
    if wi == correct: return False
    if wi <= 0: return False
    sw, sc = str(wi), str(correct)
    if len(sw) != len(sc): return False
    return sorted(sw) == sorted(sc)


def _rule_M44(s: dict) -> bool:
    """
    M44 NEAR_MISS
    (|w - correct| / correct <= 0.05 OR |w - correct| <= 1) AND w > 0 AND w != correct.
    Spec note: fires only after M01–M43 — already guaranteed by cascade order.
    """
    if s["wi"] is None: return False
    correct, wi = s["correct"], s["wi"]
    if wi == correct: return False
    if wi <= 0: return False
    if correct <= 0: return False
    diff = abs(wi - correct)
    if diff <= 1: return True
    if diff / correct <= 0.05: return True
    return False


def _rule_M45(s: dict) -> bool:
    """
    M45 ROW_RESULT_CONCAT
    Multi-digit N2; no N2 digit is 0. Compute each row correctly with carry.
    Concatenate row-result strings (units-first OR tens-first ordering).

    v14.4: Removed the "defer to M17 if single-row-shift also matches" guard
    that v14.3 and earlier had on the reversed-order branch. Cognitive analysis
    showed that for asymmetric N2 collisions (e.g., 33×12='3366'), the concat
    interpretation is strictly simpler than M17's shift+add interpretation:
      - M45 concat: kid computed both rows correctly, skipped addition entirely
      - M17 shift: kid computed both rows, shifted row 1 to wrong column, AND
        added correctly to produce wi
    The concat story requires one skipped step; the shift story requires precise
    addition of large numbers AFTER a layout error. M45 is cleaner.

    M17 already has a "defers to M45" check, so removing M45's defensive guard
    makes the deferral chain work correctly: when both rules match, M17 will
    now properly defer to M45.

    Corpus impact: ~21 rows / 223 freq move from M17 to M45 in v14.4 (cases
    like 33×12='3366', 34×21='6834', 30×24='60120', 50×17='50350').
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if n_digits(n2) < 2: return False
    if 0 in digits(n2): return False
    sim_a = long_multiply_simulate(n1, n2, row_result_concat=True)
    if sim_a == wi:
        return True
    sim_b = long_multiply_simulate(n1, n2, row_result_concat=True, row_result_concat_reversed=True)
    if sim_b == wi:
        return True
    return False


def _rule_M46(s: dict) -> bool:
    """M46 UNCLASSIFIED_ERROR (was M47 in v14.1): fallback. Always fires when wi parseable and != correct."""
    return s["wi"] is not None and s["wi"] != s["correct"]


# Predicate registry
_PREDICATES: dict[str, Callable[[dict], bool]] = {
    f"M{i:02d}": globals()[f"_rule_M{i:02d}"] for i in range(1, 47)
}


# ---------------------------------------------------------------------------
# Cascade traversal
# ---------------------------------------------------------------------------

def _cascade_first_match(signals: dict) -> str:
    for code in MULTIPLICATION_CASCADE_ORDER:
        if _PREDICATES[code](signals):
            return code
    return "M46"


# ---------------------------------------------------------------------------
# Score computation (same formula as Addition / Subtraction)
# ---------------------------------------------------------------------------

def _priority_weight(code: str) -> float:
    pos = MULTIPLICATION_CASCADE_ORDER.index(code) + 1
    return 1.0 / (pos ** 0.5)


def _compute_scores(matched: list[str], cascade_primary: str,
                    priors: dict[str, float]) -> list[tuple[str, float]]:
    if not matched:
        return []
    n_matched = len(matched)
    specificity = 1.0 / n_matched
    raw_scores = {}
    for code in matched:
        prior = priors.get(code, 0.0)
        priority = _priority_weight(code)
        raw_scores[code] = specificity * prior * priority
    max_score = max(raw_scores.values())
    if raw_scores[cascade_primary] < max_score:
        raw_scores[cascade_primary] = max_score * 1.0001
    total = sum(raw_scores.values())
    if total == 0:
        return [(c, 1.0 / n_matched) for c in matched]
    normalized = [(code, raw_scores[code] / total) for code in raw_scores]
    normalized.sort(key=lambda x: (-x[1], MULTIPLICATION_CASCADE_ORDER.index(x[0])))
    return normalized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SCORE_INCLUSION_THRESHOLD = 0.01

MULTIPLICATION_PRIORS_BY_GRADE: dict[Optional[int], dict[str, float]] = {
    None: MULTIPLICATION_PRIORS_ALL,
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
    Classify a Multiplication response into one or more misconception codes.
    """
    n1_p = parse_operand(n1)
    n2_p = parse_operand(n2)
    if n1_p is None or n2_p is None:
        return ClassifyResult(
            cascade_code="M46",
            cascade_name=MULTIPLICATION_ERROR_NAMES["M46"],
            ranked=[("M46", MULTIPLICATION_ERROR_NAMES["M46"], 1.0)],
            debug={"error": "operand parse failed"} if return_debug else {},
        )

    raw = normalize_raw(learner_response)
    wi = parse_response(learner_response)
    correct = n1_p * n2_p

    signals: dict = {
        "n1": n1_p,
        "n2": n2_p,
        "wi": wi,
        "raw": raw,
        "correct": correct,
    }

    if wi is not None and wi == correct:
        return ClassifyResult(
            cascade_code="CORRECT",
            cascade_name="CORRECT",
            ranked=[],
            debug=signals if return_debug else {},
        )

    if wi is None:
        return ClassifyResult(
            cascade_code="M01",
            cascade_name=MULTIPLICATION_ERROR_NAMES["M01"],
            ranked=[("M01", MULTIPLICATION_ERROR_NAMES["M01"], 1.0)],
            debug=signals if return_debug else {},
        )

    cascade_primary = _cascade_first_match(signals)

    matched = [code for code in MULTIPLICATION_CASCADE_ORDER if _PREDICATES[code](signals)]
    if "M46" in matched and len(matched) > 1:
        matched = [c for c in matched if c != "M46"]

    priors = MULTIPLICATION_PRIORS_BY_GRADE.get(learner_grade) or MULTIPLICATION_PRIORS_ALL
    ranked_full = _compute_scores(matched, cascade_primary, priors)
    ranked = [
        (c, MULTIPLICATION_ERROR_NAMES.get(c, ""), s)
        for c, s in ranked_full
        if s >= SCORE_INCLUSION_THRESHOLD
    ]

    return ClassifyResult(
        cascade_code=cascade_primary,
        cascade_name=MULTIPLICATION_ERROR_NAMES.get(cascade_primary, ""),
        ranked=ranked,
        debug=signals if return_debug else {},
    )
