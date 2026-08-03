"""
Division misconception classifier (codes D01–D36).

Implements the Division Error Taxonomy, v47.

v47 change (over v46) - add an invariant assert that the cascade order equals the
numeric code order (D01..Dn), the property restored in v46, so any future out-of-order
code insertion fails at import instead of silently drifting (as it did in v45). No
behaviour change: detectors, names, frequencies and cascade are identical to v46.

v46 change (over v45) - renumber the codes so numeric order matches cascade order
(restoring the cascade == numeric invariant that v45 broke by appending the new
slot-swap code as D36 while inserting it at cascade position 7). The slot-swap
CORRECT_QUOTIENT_IN_REMAINDER_SLOT moves D36 -> D07; every code that was D07..D35
shifts up by one to D08..D36 (ANSWER_EQ_DIVIDEND D07->D08, ANSWER_EQ_DIVISOR
D08->D09, PROBLEM_COPIED_IN_QR_FORMAT D09->D10, ..., QUOTIENT_NEAR_MISS D34->D35,
catch-all UNCLASSIFIED_NEAR_RANDOM D35->D36). Error names, detector logic, cascade
priority, deferral sets and frequencies are all unchanged - a pure relabel.
Verified behaviour-preserving: every corpus row's v46 tag equals the remapped v45
tag across all 45,669 rows. Now 36 codes D01-D36 with cascade order == numeric order.

v45 change (over v44) - two recall recoveries from the D35 catch-all, both
surfaced by a firing-mode / part-consistency audit of the tagged corpus.
(1) Widen D07 ANSWER_EQ_DIVIDEND: in QR form it previously claimed only the clean
"N1 R N1" and "N1 R 0" echoes; it now also claims a dividend echoed into the
quotient box with any OTHER remainder, for a multi-digit dividend (e.g. 924/8 ->
"924 R 12"). Same misconception (wrote the dividend instead of dividing); a junk
remainder is consistent with not having divided. The widened branch carves out
r == q_exp (the slot-swap form, now D36), defers to the problem-copy reading
(D09, the "N1 R N2" form, e.g. 60/5 -> "60 R 5") and to the procedural /
interchange codes (_OP_RECOVER_DEFER), so it only reclaims D35 residual.
(2) New code D36 CORRECT_QUOTIENT_IN_REMAINDER_SLOT: a placement error where the
dividend is echoed in the quotient box and the CORRECT quotient sits in the
remainder box (e.g. 648/4 -> "648 R 162"; 60/5 -> "60 R 12"; 706/9 -> "706 R 78").
The computation is right, so the remedial is format/recording, not arithmetic -
distinct from D07 (wrong computation) and from D26 (Q and R swapped with each
other). Gated to a multi-digit quotient (q_exp >= 10), q_exp != N2 and q_exp != N1
so the remainder-equals-quotient match is not coincidental and does not poach the
D09 problem-copy form. D36 sits just before D07 in the cascade. Measured effect on
the canonical corpus: 485 freq recovered from D35 to D07 and 91 freq from D35 to
the new D36 (191 unique rows, all sourced from D35); no cannibalisation - D09
(3,831) and every other code are unchanged. Now 36 codes D01-D36. _FREQ_TABLE
refreshed (D07 11,368 -> 11,853; D35 132,394 -> 131,818; D36 91; total 284,526).

v44 change (over v43) - make the quotient-zero family (D19-D24) format-agnostic.
The shared gate _d19_zero_base was QR-only, so quotient zero-drop / zero-add errors -
which mostly occur on EXACT divisions (r_exp == 0) entered as a bare integer - were
unreachable in their natural format and scattered to D30 (first-digit) and the D35
residual. The gate now also fires in Case 3 on an exact-division bare integer, the
same way D17 was made format-agnostic in v14. Measured effect on the canonical corpus:
133 freq recovered from D35 into the family, plus 322 freq of bare trailing-zero drops
(e.g. 80/4 -> "2") reclassified from D30 FIRST_DIGIT_QUOTIENT to D19 (a dropped trailing
zero) - this trailing-drop reclassification is the deliberate pedagogy call. No
cannibalisation: addition (D04), extra-trailing (D17), answer-eq-divisor (D08) and
digit-reorder (D02) all precede the family and keep their rows; the family stays MECE
in integer mode (every moved row fires exactly one of D19-D24). Also removed the dead
_int_active helper and refreshed stale freq-table provenance stamps (v40/v37 -> v44).
Codes, cascade order, and all other detectors unchanged (still 35 codes D01-D35).
_FREQ_TABLE refreshed.

v43 change (over v42) - retire D26 R_RIGHT_Q_WRONG_OTHER and rename four codes.
Per pedagogy review, D26 (remainder right, quotient wrong, no specific pattern) was
a residual whose correct-remainder signal is largely coincidental and carries no
actionable misconception; it is removed and its rows fall through the cascade -
close-quotient ones to QUOTIENT_NEAR_MISS, the rest to UNCLASSIFIED_NEAR_RANDOM.
With D26 gone, old D27..D36 RENUMBER DOWN ONE to D26..D35 (interchange D27->D26,
under-division D28->D27, step-remainder D29->D28, table-slip D30->D29, first-digit
D31->D30, last-digit D32->D31, concat D33->D32, off-by-one D34->D33, near-miss
D35->D34, catch-all D36->D35). Renames: D05 WRONG_OP_SUB_N1_N2 -> WRONG_OP_SUB;
D17 Q_DIVIDED_PAST_TERMINATION -> Q_EXTRA_TRAILING_ZEROS (predicate only ever
tested the observable q_w == q_exp x 10^k; most rows do not preserve the remainder
so the past-termination mechanism was overclaimed); D23/D24 Q_EXTRA_ZERO_* ->
Q_EXTRA_INTERNAL_ZERO_* (D17 owns trailing extra zeros, so these catch only
internal ones); renumbered interchange D26 QR_SAME_INTERCHANGED ->
QR_RIGHT_INTERCHANGED. Now 35 codes D01-D35. Deferral sets and catch-all refs
remapped; cascade, detector logic, all other codes unchanged. _FREQ_TABLE
refreshed (near-miss D34 += 688, catch-all D35 += 2,248; total 284,604; CORRECT 78).

v42 change (over v41) - re-key D19/D20 from the QUOTIENT to the DIVIDEND. In v41
the trailing/internal split for the two "missing zero, dividend has a zero" codes
described where the dropped zero sat in the ANSWER; per pedagogy review it now
describes where the zero sits in the DIVIDEND (n1), matching the original case-1/2
framing ("0 end n1" / "0 mid n1"). D19 Q_MISSING_ZERO_DIVIDEND_ENDS_IN_ZERO fires
when a zero is dropped from the answer and the dividend ends in zero; D20
Q_MISSING_ZERO_DIVIDEND_HAS_INTERNAL_ZERO when the dividend has an internal zero
but does not end in zero. Trailing-first precedence: a dividend that both ends in
and contains an internal zero (e.g. 400) is D19. The answer-side stays the
unspecified "MISSING_ZERO" because the dropped zero's own position need not match
the dividend's (e.g. 6003/6=1000 -> "100": dividend internal, answer trailing ->
D20). This moves 64 freq D19->D20 (D19 337->273, D20 58->122; total 395 unchanged).
D21/D22 remain QUOTIENT-keyed (no dividend zero exists to key on) and D23/D24
(extra) are unchanged. No renumber; cascade, deferral sets, and all other codes
are identical to v41. _FREQ_TABLE refreshed (total 284,604; CORRECT 78).

v41 change (over v40) - split the single zero-misconception code into SIX, then
renumber. Old D19 Q_ZERO_MISCONCEPTION fired whenever the remainder was right and
the quotient had the right non-zero digits but mishandled zeros, lumping distinct
errors with distinct remediation. Replaced by six codes keyed on WHAT went wrong
with the quotient zero and whether the dividend contains a zero: D19 trailing/has,
D20 internal/has, D21 trailing/no, D22 internal/no, D23 extra/has, D24 extra/no.
Trailing-vs-internal is on the QUOTIENT (where the error shows), not the dividend;
DIVIDEND_HAS_ZERO/NO_ZERO is the secondary cue. "internal" folds the rare drop-
both and reposition cases. The six partition old D19 exactly (1,272 freq). Old
D20..D31 RENUMBER up by five to D25..D36 (D20 INCOMPLETE->D25, D22 INTERCHANGE->
D27, D28 CONCAT->D33, D31 UNCLASSIFIED->D36, etc.). Deferral sets and D26's
exclusion remapped; the old-D19 reference expands to D19-D24. _FREQ_TABLE
refreshed from fresh v41 tagging (total 284,604; CORRECT 78).

v40 change (over v39) — retire D22, make the operation/operand/concat codes
format-agnostic, rename the interchange code, and RENUMBER to a contiguous
D01–D31 (31 codes). Four taxonomy changes, then a close-the-gap renumber:
  1. The wrong-operation (D03 ×, D04 +, D05 −) and operand (D07 dividend,
     D08 divisor) codes now fire on QR responses that carry the wrong value in
     BOTH slots ("<v> R <v>") as well as the bare-integer and "<v> R 0" forms,
     so a wrong-operation/operand answer gets its own code regardless of format.
     D07/D08 also reclaim "<operand> R 0" responses from the catch-all.
  2. D28 CONCAT_OPERANDS extended the same way to "<concat> R 0" / "<concat> R
     <concat>".
  3. The old same-value code QR_SAME_WRONG_OP (old D22) is RETIRED: its 1,266
     response-frequency redistributes entirely onto the now format-agnostic
     codes (old D22 only ever held op/operand same-value forms; arbitrary
     same-value guesses were already in the catch-all). To preserve the cascade
     priority old D22 provided at position 21, the new branches defer to the more
     specific codes that preceded it (problem-copied, remainder-right, past-
     termination, ÷10 ceiling, incomplete; and, for the "<operand> R 0"
     recovery, also the interchange and off-by-one/near-miss readings).
  4. The interchange code (old D23 Q_RIGHT_R_RIGHT_BUT_INTERCHANGED) is renamed
     QR_SAME_INTERCHANGED. Detector unchanged (q_w == r_exp AND r_w == q_exp).
  Renumber (close the gap): D01–D21 unchanged; old D23->D22 (the renamed
  interchange), D24->D23, D25->D24, D26->D25, D27->D26, D28->D27, D29->D28,
  D30->D29, D31->D30, D32->D31. CAUTION: the freed number 22 is REUSED — current
  D22 = QR_SAME_INTERCHANGED, NOT the retired QR_SAME_WRONG_OP; and the catch-all
  UNCLASSIFIED_NEAR_RANDOM is now D31 (was D32). _FREQ_TABLE refreshed from a
  fresh v40 tagging of the canonical dataset (total 284,604; CORRECT 78).

v39 change (over v38) — BUGFIX in D05 WRONG_OP_SUB_N1_N2, no renumbering. The rule's
docstring documents excluding the all-zero result (N1==N2) so a "0" stays ZERO_ANSWER,
but the `target == 0` guard sat AFTER the non-QR return, so it only protected the
QR branch; bare "0"/"00"/"000" on an N1==N2 problem leaked to D05 (subtraction)
instead of D06. Hoisted the guard above the is_qr split so both branches exclude
N1==N2. Effect: 11 dataset rows (3,874 response-frequency) move D05 -> D06; D05 and
all other codes/logic are otherwise unchanged from v38. Code numbers and names are
identical to v38.

v38 change (over v37) — codes RENUMBERED to deferral (cascade) order, no logic
change. All 32 codes are now contiguous D01–D32 in the exact order the cascade
evaluates them (D01 first … D32 last); the previous gaps (from retired D19/D21/
D22/D24/D29) are gone. Semantic error NAMES are unchanged — every learner response
keeps the same error name; only the D-number changed. NOTE: code numbers in the
changelog entries BELOW (v37 and earlier) use the pre-v38 numbering. old -> new for
this renumber: D03->D02, D04->D03, D05->D04, D06->D05, D02->D06, D30->D17, D35->D18,
D17->D19, D37->D20, D18->D21, D20->D22, D33->D23, D36->D24, D34->D25, D25->D26,
D26->D27, D27->D28, D28->D29, D23->D30; D01,D07-D16,D31,D32 unchanged. CAUTION: retirement freed the five numbers
D19/D21/D22/D24/D29, and v38 REUSED them for unrelated codes — so any mention of
D19/D21/D22/D24/D29 in the entries below refers to the code RETIRED in that era, NOT
the current code now bearing that number. Current meanings of the reused numbers:
D19=Q_ZERO_MISCONCEPTION, D21=R_RIGHT_Q_WRONG_OTHER, D22=QR_SAME_WRONG_OP,
D24=UNDER_DIVISION, D29=CONCAT_OPERANDS.

v37 change (over v36) — naming only, no logic or frequency change:
  D33 QR_INTERCHANGED -> Q_RIGHT_R_RIGHT_BUT_INTERCHANGED. The detector is
  unchanged (q_w == r_exp AND r_w == q_exp with q_exp != r_exp); the new name makes
  explicit that both values are correct, just written in each other's slot. Sub-skill
  (Format error, keyed by code) and frequency unchanged.

v36 change (over v35) — D03 and D29 merged (32 codes):
  D29 Q_DIGITS_REORDERED retired and merged into D03, which is renamed
  REVERSED_QUOTIENT_INPUT -> Q_DIGITS_REORDERED. D03 detected the full reversal of
  the quotient's digits (78 -> 87); D29 detected every OTHER permutation of the same
  digits and explicitly excluded D03. A reversal is just one special case of a
  reordering, so the two were the disjoint halves of a single phenomenon: right
  digits, wrong order. D03's predicate now drops the "reversed" restriction and
  accepts any permutation (same digit multiset, same length, w != q_exp). All D29
  cases move to D03; shared remedial (place value / left-to-right digit order).
  Codes are now D01–D18, D20, D23, D25–D28, D30–D37 (D19, D21, D22, D24, D29 retired).

v35 change (over v34) — D14 and D22 merged (33 codes):
  D22 Q_RIGHT_R_EXCEEDS_DIVISOR retired and merged into D14, which is renamed
  Q_RIGHT_R_LESS_THAN_DIVISOR -> Q_RIGHT_R_WRONG_OTHER (its original v12 name).
  Both detected the identical phenomenon — quotient exactly right, remainder a
  wrong nonzero value with no clear pattern — split only by whether the remainder
  happened to be smaller (D14) or larger (D22) than the divisor. The data showed
  that split is cosmetic: 87% of D22's remainders had no relation to the divisor
  (just wrong-and-large), and 0 had q_w == r_w (so D20 is unaffected). D14 now
  drops its r_w < N2 ceiling and covers both. Single shared remedial (the remainder
  is the leftover after quotient × divisor and must be smaller than the divisor).
  All 1,695 D22 cases move to D14. Codes are now D01–D18, D20, D23, D25–D37
  (D19, D21, D22, D24 retired).

v34 change (over v33) — D21 retired, folded into D32 (34 codes):
  D21 QR_SAME_WRONG_OTHER removed. It only captured "the same value written in
  both the quotient and remainder slots, with the value not a recognised wrong-
  operation result" — and the data shows ~97% of its 7,174 cases bear no relation
  to the problem at all (arbitrary guesses like 60÷5 -> "30 R 30", "530 R 530",
  "2 R 2", spanning 1–9 digits). There is no misconception and nothing to
  remediate; it is near-random duplication, which is exactly D32
  UNCLASSIFIED_NEAR_RANDOM. Its sibling D20 QR_SAME_WRONG_OP is kept — there the
  repeated value IS a wrong-operation result, a teachable mechanism. All D21 cases
  fall through to D32. Codes are now D01–D18, D20, D22–D23, D25–D37 (D19, D21, D24
  retired).

v33 change (over v32) — D19 retired, folded into D36 (35 codes):
  D19 CHUNK_DIVISION_NOT_DIGIT_BY_DIGIT removed as a tagged code. Every D19 case
  closes the division identity q_w × N2 + r_w == N1 with r_w ≥ 2·N2 — i.e. it is
  identity-closing UNDER-DIVISION (the learner under-divided step by step, leaving
  ≥ 2 whole divisors in the remainder, e.g. 706÷9 -> "69 R 85": 9×69+85 = 706).
  There is no separate "chunking" mechanism: combining digits is mandatory normal
  procedure when the leading digit < divisor, not a chosen alternative method, so
  the error is under-division and belongs to D36 UNDER_DIVISION. Empirically all
  390 D19 cases were single-digit-divisor under-division; none were multi-digit-
  divisor "chunking expected" cases. D19's predicate is retained as the internal
  guard _chunk_remnant so D21/D23 still defer these past themselves and D36 claims
  them. Codes are now D01–D18, D20–D23, D25–D37 (D19 and D24 both retired).

v32 change (over v31) — new code D37 INCOMPLETE_DIVISION (36 codes):
  Carves out the learners who run long division correctly for the first few steps
  and then stop, reporting the running quotient and that step's working remainder
  without bringing down the remaining digit(s). Detector: N2·q_w + r_w reconstructs
  a LEADING PREFIX of the dividend (the digits consumed so far) with 0 ≤ r_w < N2 —
  a valid mid-algorithm state — for some prefix shorter than the full dividend.
  Example: 924÷8 -> "11 R 4" (8×11+4 = 92, the first two digits of 924). Distinct
  from D36 UNDER_DIVISION, which closes against the FULL dividend with r_w ≥ N2.
  Cascade-positioned right after D17 (terminal-zero drops keep their zero-
  misconception reading) and before D18 (so the mechanism is named rather than left
  in the generic "remainder right, quotient wrong" residual). It draws from the D18
  residual, the D21 same-value coincidences, and previously-unclassified D32; D17
  and everything ahead of it are untouched. Codes are now D01–D23, D25–D37 (D24
  remains retired).

v31 change (over v30) — D24 retired (35 codes):
  D24 Q_SMALL_R_SMALL removed entirely. Its detector (r_exp != 0, q_exp >= 8,
  q_w < q_exp/4) was an arbitrary "quotient much smaller than a quarter of
  expected" threshold with no coherent misconception or remediation behind it —
  a catch-all for wildly-too-small quotients. Its cases fall through to the codes
  that follow it in the cascade (mostly D32 unclassified). The code number D24 is
  RETIRED, not reused: D25–D36 keep their identities and names so prior workbooks
  stay traceable. Codes are now D01–D23, D25–D36 (35 total).

v30 change (over v29) — D36 renamed and tightened to the division identity:
  D36 WRONG_MULTIPLE_AT_STEP -> UNDER_DIVISION. The detector now requires the
  exact reconstruction Dividend = Divisor × Quotient + Remainder (N1 == N2·q_w +
  r_w) with a wrong quotient — which forces remainder ≥ divisor, i.e. genuine
  under-division (consistent arithmetic, stopped short). The old off-by-one
  branch (b) (q_exp − q == 1) did NOT require the identity (e.g. 706÷9 -> "77 R 3"
  reconstructs to 696, not 706) — those are calculation-error noise, not under-
  division, and now fall through to the off-by-one / near-miss codes (D23/D31).
  Sub-skill (Conceptual error, keyed by code) and cascade position unchanged.

v29 change (over v28) — naming only, no logic or frequency change:
  D21 renamed QR_SAME_VALUE -> QR_SAME_WRONG_OTHER, for parity with its sibling
  D20 QR_SAME_WRONG_OP. Both detect the same surface error (one value written in
  both the quotient and remainder slots, q_w == r_w); D20 is when that value is a
  recognised wrong-operation result, D21 (now ..._OTHER) is any other wrong value.
  Predicate, cascade position, and all frequencies are unchanged from v28.

v28 change (over v27) — D36 restricted to non-maximal (undershoot) multiples:
  D36 WRONG_MULTIPLE_AT_STEP branch (b) now requires the quotient to be one too
  SMALL (q_exp − q == 1), not off-by-one in either direction. A quotient one too
  big (72÷6 -> 13) would need a step multiple exceeding the working dividend
  (6×3=18 > 12), which is not a valid long-division step, so it is not a
  wrong-multiple-at-step — it is a plain off-by-one. Every D36 case now has a step
  product ≤ the working dividend. The 767 high-side cases leave D36: 676 to D23
  (integer + remainder-bearing QR off-by-ones), 59 to D31 (exact-remainder QR
  near-misses), 32 to D32 (QR with quotient and remainder both wrong).
  Net: D36 2,334 -> 1,567; D23 124 -> 800; D31 4,085 -> 4,144; D32 117,776 ->
  117,808. Still 36 codes.

v27 change (over v26) — D31 near-miss floor removed:
  D31 QUOTIENT_NEAR_MISS band drops the absolute floor of 5; it is now purely
  q_exp/3 (capped at 50). Because D31 fires only at q_exp > 10 and q_exp/3 reaches
  5 at q_exp = 15, the floor only inflated the window for q_exp 11–14 — letting a
  response 45% off the answer read as "near". The band is now a constant ±⅓ of
  the answer at every scale; the worst near-miss falls from 45% to 33%.
  Net: D31 4,259 -> 4,085; 174 freq (q_exp 11/12/14, the distance-5 cases) move
  to D32 (117,602 -> 117,776), the only transition. Still 36 codes.

v26 change (over v25) — D25 proportionality cap made symmetric:
  D25 SINGLE_STEP_TABLE_SLIP now bounds the proposed multiplier on both sides,
  q_exp/2 ≤ w ≤ 2·q_exp (within a factor of 2 of the answer). v25 capped only the
  high side, so a disproportionate LOW guess at a large quotient — 72÷9 -> 1
  (proposing row 1 for an answer of 8) — still read as a table slip. The lower
  half-bound sends those out of D25; the q_exp=10 first-digit reads (50÷5 -> 1)
  land in D26 where they belong, the rest in D32.
  Net: D25 22,869 -> 18,514 (4,294 to D32, 61 to D26); still 36 codes.

v25 change (over v24) — D25 proportionality cap:
  D25 SINGLE_STEP_TABLE_SLIP now also requires the proposed multiplier to be
  proportionate to the answer (w ≤ 2·q_exp), not merely a table row in [1,10].
  A wrong table-recall slip lands near the correct row; proposing row 8 for an
  answer of 2 (10÷5 -> 8) is a wild, disproportionate guess, not a slip, and
  returns to D32 as unclassified. The cap scales with the answer: it bites only
  at small quotients (q_exp ≤ 4, where 2·q_exp < 10) and is inert at q_exp ≥ 5
  (where 2·q_exp ≥ 10, so the [1,10] table bound already governs).
  Net: D25 29,466 -> 22,869; the 6,597 disproportionate guesses move to D32
  (D32 106,711 -> 113,308), the only transition. No other code changes; 36 codes.

v24 changes (over v23) — "wrong multiple of the divisor", split by scale:
  1. D25 repurposed to SINGLE_STEP_TABLE_SLIP. For a table-fact division
     (1 ≤ q_exp ≤ 10) any wrong single-digit multiplier (1 ≤ w ≤ 10, w != q_exp)
     is one table slip, unifying what v23 split across D25/D23/D31 by arithmetic
     accident. ~29.5k freq.
  2. New code D36 WRONG_MULTIPLE_AT_STEP — the multi-digit sibling: a non-maximal
     multiple at a long-division step. Fires on (a) one multiple short
     (q_w·N2 + r_w == N1 with N2 ≤ r_w < 2·N2) or (b) an off-by-one quotient on a
     past-the-table division (q_exp > 10). Sits after D33. ~2.3k freq.
  3. D19 narrowed to genuine chunking only (r_w ≥ 2·N2); the one-short cases move
     to D36.
  4. D31 now fires only at q_exp > 10 — no "near-miss" at table scale (that is a
     table slip or, for w > 10, unclassified). Large-q off-by-ones go to D36, so
     D31 holds genuine multi-digit near-misses (off by two or more).
  Net: D25 2,428 -> 29,466; D36 0 -> 2,334; D19 663 -> 390; D31 20,754 -> 4,259;
  D23 10,533 -> 124; D32 108,845 -> 106,711.

v23 changes (over v22):
  1. D25 DIVISOR_TIMES_TABLE_WRONG_K tightened so it names a genuine table-recall
     error rather than any coincidental multiple of the divisor. Now requires the
     correct quotient to be a table fact (q_exp ≤ 10) AND the wrong multiple to be
     within two rows of the correct one (|k − q_exp| ≤ 2). Previously "answer is a
     multiple of the divisor, k ≤ 10" alone tagged 72÷3 -> 9 (quotient 24, past
     the table ceiling) and 21÷3 -> 12 (three rows off) as table-recall errors.
     Sheds ~8,890 freq to D26/D27/D28/D29/D23/D31/D32 where each belongs.

v22 changes (over v21):
  1. D31 QUOTIENT_NEAR_MISS band clamped at the bottom: for q_exp <= 1 the near
     band is 1 (off-by-one only) instead of the floor of 5. A window of ±5 at a
     true quotient of 1 was tagging 3–6x misses (5÷5 -> 6, 2÷2 -> 5) as
     near-misses; those — almost all n÷n where the learner doesn't know the
     answer is 1 — now fall to D32. Off-by-one is already claimed by D23, so the
     clamp removes the over-reach without stranding genuine off-by-one cases.

v21 changes (over v20):
  1. D31 QUOTIENT_NEAR_MISS extended to Q-R responses. The scale-aware near band
     now also applies to the written quotient q_w when the remainder is correct
     (r_w == r_exp), so a clean quotient near-miss written in Q-R form
     (60÷5 -> "11 R 0" for "12 R 0") is tagged as a near-miss instead of being
     stranded in D32 because the net was integer-only. Both-wrong responses with
     a junk remainder stay in D32. D31 sits at the end of the cascade, so this
     reclaims only from D32; the r_exp != 0 versions are already absorbed by D18.
  2. Cosmetic: _rule_D14 docstring title corrected to Q_RIGHT_R_LESS_THAN_DIVISOR
     (the emitted name); no tagging effect.

v20 changes (over v19):
  1. D35 NO_DIGIT_BY_DIGIT_DIVISION gated by reachability. The ×10 table multiple
     must fit in the leading chunk the learner works with: divisor×10 <= the
     leftmost (digits-of-divisor + 1) digits of the dividend. Without this, rows
     like 706÷9 -> "10" were tagged D35 even though 9×10=90 cannot fit in the
     leading "70", so "10" could not be a maxed-table result. Sheds 93 freq (the
     706÷9 family, q_exp 74–638) back to D24/D32; keeps 2,636. Note: the gate
     reads only the leading chunk, so very-far-off answers whose lead happens to
     hold divisor×10 stay in D35 by design (924÷8 -> "10", confirmed in-scope; a
     14-freq tail of 4–5 digit dividends such as 66001÷6 -> "10" also remains).

v19 changes (over v18):
  1. New code D35 NO_DIGIT_BY_DIGIT_DIVISION (sub-skill: conceptual). The
     learner doesn't recognise the problem needs long division and falls back on
     the divisor's table, stopping at its ×10 ceiling: they write quotient 10
     when the correct quotient exceeds 10 (e.g. 60÷5 -> "10" / "10 R 10",
     correct 12). Detected on the written quotient (w / q_w) == 10 with q_exp>10.
     Cascade-positioned just before D17 — ahead of the chunking and remainder
     codes — so this specific ×10-ceiling signature is named rather than folded
     into generic "chunked" (D19) or misread as a wrong table multiple (D25).
     Claims integer + QR; also reabsorbs the table-ceiling answers that v18 had
     pushed from D34 into D25/D31.

v18 changes (over v17):
  1. D34 STEP_REMAINDER_IGNORED narrowed: a wrong quotient of exactly 10 is no
     longer tagged here. Such answers (e.g. 72÷6 -> 10) are the times-table
     ceiling — the learner used the largest recalled multiple (divisor × 10)
     and stopped, leaving a remainder ≥ divisor. That is under-division, not
     digit-wise carry-drop, and was an artefact of the digit-wise detector
     coinciding with the ×10 ceiling. D34 now keeps only carry-drops whose
     quotient ≠ 10 (e.g. 75÷3 -> 21), which have no single-multiplication story.

v17 changes (over v16):
  1. New code D34 STEP_REMAINDER_IGNORED. The learner divides each dividend digit
     by the divisor independently and never carries the remainder to the next
     place, e.g. 90÷2 -> "40" (9//2=4, 0//2=0), 75÷3 -> "21" (7//3=2, 5//3=1).
     Detected when the response equals that digit-by-digit floor division and
     is wrong; restricted to a leading digit that divides to ≥ 1 so ambiguous
     leading-zero collapses (18÷3 -> "2") are NOT swept in. Cascade-positioned
     just ahead of D25 so a carry-drop whose value is a low multiple of the
     divisor (e.g. 75÷3 -> 21 = 3×7) is tagged as the procedural error it is,
     not as a table-recall slip. Claims pull from D25/D31/D32 only.

v16 changes (over v15):
  1. D25 DIVISOR_TIMES_TABLE_WRONG_K cap reduced from k ≤ 20 to k ≤ 10.
     D25 models a *table-recall* error — picking the wrong multiple from a
     memorised times table. Standard tables are recalled to ×10 (e.g. 2×0 …
     2×10); beyond ×10 a learner computes digit-by-digit rather than recalls,
     so a multiple with k > 10 is not a table-recall slip and must not be
     tagged here. (v14 used ≤ 12, v15 briefly tried ≤ 20; both over-reached.)
     The operand-concatenation exclusion added in v15 is retained.

v15 changes (over v14):
  1. D31 QUOTIENT_NEAR_MISS recalibrated to a scale-aware near band (Band C):
     NEAR = |w − q_exp| ≤ min(max(5, q_exp/3), 50); q_exp == 0 → w ≤ 5.
     v14's flat factor-of-2 band was too tight for small quotients (basic-fact
     near-misses such as 8÷4=5 fell through to D32) and too loose for large
     ones (e.g. 846÷2=838, off by 415, read as "near"). The absolute floor of
     5 keeps small-quotient guesses in D31; the /3 slope and cap of 50 keep
     large quotients honest.
  2. D25 DIVISOR_TIMES_TABLE_WRONG_K cap lifted from k ≤ 12 to k ≤ 20
     (extended "tables up to 20"), capturing the genuine extended-table band.
     The bound stays finite on purpose: k > 20 multiples are magnitude/place-
     value slips or coincidental multiples (max observed k ≈ 4.9e8) and must
     not be relabelled as table recall. D25 now also explicitly excludes
     operand concatenations (which CAN be multiples with k ≤ 20, e.g. 6÷2 →
     "26" = 2×13), leaving those to D28; this also corrects a latent v14 case
     where small concatenations such as 5÷5 → "55" (5×11) were tagged D25.

v14 changes (over v13):
  1. D04–D06 (wrong operation) now also fire when a remainder is expected:
     in QR-eligible cases on q_w == N1×N2 / N1+N2 / N1−N2 with r_w == 0
     (the all-zero result is excluded so "0 R 0" stays D02). Integer-mode
     behaviour is unchanged.
  2. Renames: D14 → Q_RIGHT_R_LESS_THAN_DIVISOR, D22 → Q_RIGHT_R_EXCEEDS_DIVISOR.
  3. D33 QR_INTERCHANGED added (q_w == r_exp AND r_w == q_exp, q_exp != r_exp),
     cascade-positioned before D24 so interchange is no longer absorbed there.
  4. D23 Q_OFF_BY_ONE extended to integer mode (|w − q_exp| == 1) and moved
     just before D31, carving off-by-one out of the near-miss net.
  5. D30 Q_DIVIDED_PAST_TERMINATION made format-agnostic (fires on q_w in QR
     too) and moved ahead of D17 so the trailing-zero pattern is labelled here.
  6. D31 QUOTIENT_NEAR_MISS tightened to a genuine near band
     (|w − q_exp| ≤ 2 OR 0.5·q_exp ≤ w ≤ 2·q_exp); far-off quotients fall
     through to D32. The band is the tunable knob.

_FREQ_TABLE / _TOTAL_FREQ are from a fresh v44 tagging of the canonical dataset.
The derived priors are tag-neutral — they do not affect the cascade winner.

Cascade order
-------------
DIVISION_CASCADE_ORDER is the single source of truth for priority and is
evaluated strictly in numeric order, D01 → D31: classify() returns the first
code whose predicate fires, else the D31 catch-all. Since v38 the code numbers
are aligned TO the cascade, so numeric order IS evaluation order — a lower-
numbered code is checked, and therefore wins, ahead of a higher-numbered one.
Cross-code priority is carried entirely by each rule's own predicate conditions
(and, for the format-agnostic operation/operand codes, by the
_OP_BOTHSLOTS_DEFER / _OP_RECOVER_DEFER deferral sets), not by any out-of-order
override. See the per-version changelog above for how the current numbering was
reached and which freed numbers have been reused.

Response-handling framework
---------------------------
The classifier accepts an optional flag, system_expects_remainder, that
indicates whether the system's expected response format is Q R r (True) or
integer-only (False). When the flag is not provided, the classifier defaults
to the math: True if r_exp > 0, False if r_exp == 0. Four cases follow:

  Case 1: system_expects_remainder=True, learner gave QR.
    CORRECT iff q_w == q_exp AND r_w == r_exp.
    On miss: evaluate cascade; QR rules eligible.
  Case 2: system_expects_remainder=True, learner gave integer-only.
    Treat r_w = 0 (absent R = 0). The response is treated as if it were
    "wi R 0" for cascade routing — QR rules eligible.
    CORRECT iff q_w == q_exp AND r_w == r_exp.
  Case 3: system_expects_remainder=False, learner gave integer-only.
    CORRECT iff wi == q_exp.
    On miss: evaluate cascade; QR rules do NOT fire.
  Case 4: system_expects_remainder=False, learner gave QR.
    CORRECT iff q_w == q_exp AND r_w == r_exp.
    On miss: evaluate cascade; QR rules eligible.

Note on D10 and D13: both rules require r_exp > 0 in their detection rule,
so they don't fire when r_exp = 0 regardless of system_expects_remainder.

API
---
    classify(n1, n2, learner_response, learner_grade=None,
             system_expects_remainder=None,
             *, return_debug=False) -> ClassifyResult

Score formula: same as Addition / Subtraction / Multiplication.
"""

__version__ = "47"

from dataclasses import dataclass, field
from typing import Optional, Callable

from utils import (
    parse_operand, parse_qr_response, normalize_raw,
    digits, n_digits, concat_int,
)


# ---------------------------------------------------------------------------
# Empirical priors — from a fresh v44 tagging of the canonical TS+KA+Pvt FIB
# division dataset (Combined_TS_KA_Pvt_Fib_wrong_ans). system_expects_remainder
# is taken per-row from the expected-result format; 78 freq (34 value-correct /
# format-only rows) are excluded as CORRECT. These priors are tag-neutral.
# ---------------------------------------------------------------------------

_TOTAL_FREQ = 284526
_FREQ_TABLE = {
    "D01": 6357,
    "D02": 292,
    "D03": 23778,
    "D04": 10323,
    "D05": 15719,
    "D06": 25165,
    "D07": 91,
    "D08": 11853,
    "D09": 12396,
    "D10": 3831,
    "D11": 946,
    "D12": 631,
    "D13": 1459,
    "D14": 159,
    "D15": 3566,
    "D16": 43,
    "D17": 196,
    "D18": 573,
    "D19": 2636,
    "D20": 620,
    "D21": 142,
    "D22": 149,
    "D23": 342,
    "D24": 286,
    "D25": 188,
    "D26": 648,
    "D27": 727,
    "D28": 663,
    "D29": 549,
    "D30": 18514,
    "D31": 787,
    "D32": 782,
    "D33": 1361,
    "D34": 1955,
    "D35": 4981,
    "D36": 131818,
}
DIVISION_PRIORS_ALL: dict[str, float] = {
    code: freq / _TOTAL_FREQ for code, freq in _FREQ_TABLE.items()
}


# ---------------------------------------------------------------------------
# Spec-derived error names
# ---------------------------------------------------------------------------

DIVISION_ERROR_NAMES: dict[str, str] = {
    "D01": "RANDOM_OR_INVALID",
    "D02": "Q_DIGITS_REORDERED",
    "D03": "WRONG_OP_MULTIPLY",
    "D04": "WRONG_OP_ADD",
    "D05": "WRONG_OP_SUB",
    "D06": "ZERO_ANSWER",
    "D07": "CORRECT_QUOTIENT_IN_REMAINDER_SLOT",
    "D08": "ANSWER_EQ_DIVIDEND",
    "D09": "ANSWER_EQ_DIVISOR",
    "D10": "PROBLEM_COPIED_IN_QR_FORMAT",
    "D11": "Q_RIGHT_R_ZERO",
    "D12": "Q_RIGHT_R_EQUALS_DIVISOR",
    "D13": "Q_RIGHT_R_COPIED_AS_Q",
    "D14": "Q_RIGHT_R_DOUBLED",
    "D15": "Q_RIGHT_R_WRONG_OTHER",
    "D16": "R_RIGHT_Q_ZERO",
    "D17": "R_RIGHT_Q_OFF_BY_ONE",
    "D18": "Q_EXTRA_TRAILING_ZEROS",
    "D19": "NO_DIGIT_BY_DIGIT_DIVISION",
    "D20": "Q_MISSING_ZERO_DIVIDEND_ENDS_IN_ZERO",
    "D21": "Q_MISSING_ZERO_DIVIDEND_HAS_INTERNAL_ZERO",
    "D22": "Q_MISSING_TRAILING_ZERO_DIVIDEND_NO_ZERO",
    "D23": "Q_MISSING_INTERNAL_ZERO_DIVIDEND_NO_ZERO",
    "D24": "Q_EXTRA_INTERNAL_ZERO_DIVIDEND_HAS_ZERO",
    "D25": "Q_EXTRA_INTERNAL_ZERO_DIVIDEND_NO_ZERO",
    "D26": "INCOMPLETE_DIVISION",
    "D27": "QR_RIGHT_INTERCHANGED",
    "D28": "UNDER_DIVISION",
    "D29": "STEP_REMAINDER_IGNORED",
    "D30": "SINGLE_STEP_TABLE_SLIP",
    "D31": "FIRST_DIGIT_QUOTIENT",
    "D32": "LAST_DIGIT_QUOTIENT",
    "D33": "CONCAT_OPERANDS",
    "D34": "Q_OFF_BY_ONE",
    "D35": "QUOTIENT_NEAR_MISS",
    "D36": "UNCLASSIFIED_NEAR_RANDOM",
}


# ---------------------------------------------------------------------------
# Cascade order
# ---------------------------------------------------------------------------
# Per spec: numerical D01 → D36 with one override — wrong-op checks
# (D03, D04, D05) fire BEFORE D06. So D06 is moved after D05.
DIVISION_CASCADE_ORDER: list[str] = [
    "D01",
    # D06 moved later — see spec priority note
    "D02",
    "D03", "D04", "D05",
    "D06",
    "D07",                       # v45: slot-swap (dividend in Q, correct quotient in R) — ahead of the dividend-echo D08
    "D08", "D09", "D10",
    "D11", "D12", "D13", "D14", "D15",
    "D16", "D17",
    "D18",                       # v14: trailing-zero pattern, prioritized ahead of the zero family (D20-D25)
    "D19",                       # v19: table-ceiling under-division (quotient==10), ahead of the chunking/remainder codes
    "D20",
    "D21",
    "D22",
    "D23",
    "D24",
    "D25",
    "D26",                       # v32: incomplete/truncated long division — after the zero family (D20-D25, which keeps priority)
    "D27",                       # v14: Q/R interchange, ahead of D36
    "D28",                       # v24/v30: UNDER_DIVISION (identity-closing, remainder >= divisor), ahead of D34/D35
    "D29",                       # v17: digit-wise no-carry division, ahead of D30 so carry-drops that look like table multiples aren't tagged D30
    "D30",
    "D31", "D32", "D33",
    "D34",                       # v14: off-by-one carved out just ahead of the near-miss net
    "D35", "D36",
]
assert sorted(DIVISION_CASCADE_ORDER) == sorted(DIVISION_ERROR_NAMES.keys())
assert DIVISION_CASCADE_ORDER == [f"D{i:02d}" for i in range(1, len(DIVISION_ERROR_NAMES) + 1)], \
    "cascade order must equal numeric code order (D01..Dn)"


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
# Predicate helpers
# ---------------------------------------------------------------------------
# After the four-case framing in classify() runs, predicates see a unified
# signal dict. Two booleans drive QR-rule eligibility:
#   qr_eligible:   True when QR rules are allowed to fire (Cases 1, 2, 4).
#                  False in Case 3.
#   int_eligible:  True when integer-only rules are allowed to fire (Cases 1, 4
#                  also disable some integer rules — see below).
#
# In Case 1 and 4 (system or learner used QR), integer-only rules can still
# fire if the learner happened to give integer-only AND it's Case 3. The
# integer-rule guard reduces to: was the response actually given in
# integer-only form? That's the case if the parsed response was integer-only
# (parsed["wi"] is not None) AND not Case 2 (where we synthesize r_w=0).

def _qr_active(s: dict) -> bool:
    """Are QR rules eligible to fire? True for Cases 1, 2, 4."""
    return s["qr_eligible"]


# ---------------------------------------------------------------------------
# Per-rule predicates (D01–D27) — v15 numbering
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Deferral sets for the format-agnostic operation / operand codes (v40).
# When a wrong-operation or operand value is written in QR form, the op/operand
# code claims it ONLY where a more specific reading does not apply — reproducing
# the cascade priority the retired same-value code (old D28, then at cascade
# position 21) used to provide.
#   _OP_BOTHSLOTS_DEFER: codes that preceded old D28 (cascade pos < 21) and can
#     fire on an "<v> R <v>" (both-slots) response. The new "<v> R <v>" branch of
#     D03/D04/D05/D08/D09 defers to these so e.g. a remainder-right or extra-trailing-zeros
#     reading keeps its specific code. It deliberately excludes the
#     codes that came AFTER old D28, so genuine same-value redistributions still
#     land on the op/operand code.
#   _OP_RECOVER_DEFER: QR-capable codes preceding the D36 catch-all. The new
#     "<operand> R 0" recovery branch of D08/D09 defers to these so it only
#     reclaims responses that would otherwise be unclassified (D36), never
#     overriding a procedural / interchange / partial-correctness reading.
_OP_BOTHSLOTS_DEFER = ("D10", "D17", "D18", "D19", "D20", "D21", "D22", "D23", "D24", "D25", "D26")
_OP_RECOVER_DEFER = ("D17", "D18", "D19", "D20", "D21", "D22", "D23", "D24", "D25", "D26", "D27", "D34", "D35")


def _rule_D01(s: dict) -> bool:
    """
    D01 RANDOM_OR_INVALID
    Non-numeric, contains letters, empty, decimal, OR pure-integer string of
    ≥4 identical digits. Mash detection uses raw string (not parsed integer)
    so that "00000" is still detected as mash even though it parses to 0.
    Q-R format strings with repeated digits go to QR rules per spec.

    Per spec, mash fires "immediately, before D06 and the rest of the cascade"
    — no deferrals.
    """
    if s["raw"] is None:
        return True
    # Failed parse (decimal, negative, multi-R, non-numeric)
    if not s["is_qr"] and s["wi"] is None:
        return True
    # Mash detection: integer-only response, 4+ identical consecutive digits
    # in the raw text (must use raw to catch "00000" which parses to 0).
    if not s["is_qr"] and s["wi"] is not None:
        raw_digits = s["raw"].replace(",", "")
        for i in range(len(raw_digits) - 3):
            if (raw_digits[i].isdigit()
                and raw_digits[i] == raw_digits[i+1]
                == raw_digits[i+2] == raw_digits[i+3]):
                return True
    return False


def _rule_D06(s: dict) -> bool:
    """
    D06 ZERO_ANSWER
    Parsed as integer 0, OR "0 R 0" / "00 R 00" in Q-R format.
    Fires only AFTER wrong-op checks (cascade-order override).
    Not applicable when the correct quotient is genuinely 0.
    """
    q_exp = s["q_exp"]
    r_exp = s["r_exp"]
    # If the correct answer is 0 (math says 0): D06 doesn't apply.
    if q_exp == 0 and r_exp == 0:
        return False
    if s["is_qr"]:
        return s["q_w"] == 0 and s["r_w"] == 0
    if s["wi"] is not None:
        return s["wi"] == 0
    return False


def _rule_D02(s: dict) -> bool:
    """
    D02 Q_DIGITS_REORDERED
    Integer response; q_exp has ≥2 digits; w uses the same digits as q_exp (same
    multiset, same length) but in a different order (w != q_exp). Covers the full
    reversal (78 -> 87) and any other permutation (123 -> 213, 321, …). The reversal
    was code REVERSED_QUOTIENT_INPUT and the non-reversal permutations were a separate
    code until v36; unified here since a reversal is just one special
    case of a reordering — the learner has the right digits, wrong order (a place-
    value / transcription slip, not a division error).
    """
    if s["is_qr"]:
        return False
    if s["wi"] is None:
        return False
    q_exp = s["q_exp"]
    if n_digits(q_exp) < 2:
        return False
    sw, sq = str(s["wi"]), str(q_exp)
    if len(sw) != len(sq):
        return False
    if s["wi"] == q_exp:
        return False
    return sorted(sw) == sorted(sq)


def _rule_D03(s: dict) -> bool:
    """
    D03 WRONG_OP_MULTIPLY: response equals N1 × N2.
    Integer mode: w == N1×N2. QR-eligible mode: q_w == N1×N2 and r_w == 0
    (a clean wrong-op result written in QR form, incl. integer-in-QR Case 2).
    Excludes the all-zero result so "0 R 0" stays D06.
    """
    target = s["n1"] * s["n2"]
    if not s["is_qr"]:
        return s["wi"] is not None and s["wi"] == target
    if target == 0:
        return False
    qw, rw = s["q_w"], s["r_w"]
    if qw != target:
        return False
    if rw in (0, None):
        return True
    if rw == target and target != s["q_exp"]:
        return not any(_PREDICATES[c](s) for c in _OP_BOTHSLOTS_DEFER)
    return False


def _rule_D04(s: dict) -> bool:
    """
    D04 WRONG_OP_ADD: response equals N1 + N2.
    Integer mode: w == N1+N2. QR-eligible: q_w == N1+N2 and r_w == 0.
    """
    target = s["n1"] + s["n2"]
    if not s["is_qr"]:
        return s["wi"] is not None and s["wi"] == target
    if target == 0:
        return False
    qw, rw = s["q_w"], s["r_w"]
    if qw != target:
        return False
    if rw in (0, None):
        return True
    if rw == target and target != s["q_exp"]:
        return not any(_PREDICATES[c](s) for c in _OP_BOTHSLOTS_DEFER)
    return False


def _rule_D05(s: dict) -> bool:
    """
    D05 WRONG_OP_SUB: response equals N1 − N2 (N1 ≥ N2).
    Integer mode: w == N1−N2. QR-eligible: q_w == N1−N2 and r_w == 0.
    Excludes the all-zero result (N1==N2) so "0 R 0" stays D06.
    """
    if s["n1"] < s["n2"]:
        return False
    target = s["n1"] - s["n2"]
    if target == 0:
        return False
    if not s["is_qr"]:
        return s["wi"] is not None and s["wi"] == target
    qw, rw = s["q_w"], s["r_w"]
    if qw != target:
        return False
    if rw in (0, None):
        return True
    if rw == target and target != s["q_exp"]:
        return not any(_PREDICATES[c](s) for c in _OP_BOTHSLOTS_DEFER)
    return False


def _rule_D08(s: dict) -> bool:
    """D08 ANSWER_EQ_DIVIDEND: the response is the dividend N1 — as a bare
    integer (w == N1), or in QR as "N1 R N1" (dividend in both slots) or
    "N1 R 0" (dividend as the quotient with no remainder). Never fires when the
    dividend equals the correct quotient (q_w == q_exp). The both-slots form
    defers to the specific QR codes that preceded the retired same-value code
    (_OP_BOTHSLOTS_DEFER); the "N1 R 0" recovery defers to any procedural /
    interchange reading (_OP_RECOVER_DEFER) so it only reclaims D36 residual."""
    n1 = s["n1"]
    if not s["is_qr"]:
        return s["wi"] is not None and s["wi"] != 0 and s["wi"] == n1
    q, r = s["q_w"], s["r_w"]
    if q is None or q == 0 or q != n1 or q == s["q_exp"]:
        return False
    if r == n1:
        return not any(_PREDICATES[c](s) for c in _OP_BOTHSLOTS_DEFER)
    if r == 0:
        return not any(_PREDICATES[c](s) for c in _OP_RECOVER_DEFER)
    # v45: dividend echoed into the quotient slot with any OTHER remainder
    # (multi-digit dividend), e.g. 924/8 -> "924 R 12". Same misconception as the
    # bare / both-slots forms; a junk remainder is consistent with not dividing.
    # Carve out r == q_exp (the slot-swap pattern handled by D07), defer to the
    # problem-copy reading (D10, the "N1 R N2" form) and to the procedural /
    # interchange readings, so this only reclaims D36 residual.
    if n1 >= 10 and r != s["q_exp"]:
        if _PREDICATES["D10"](s):
            return False
        return not any(_PREDICATES[c](s) for c in _OP_RECOVER_DEFER)
    return False


def _rule_D09(s: dict) -> bool:
    """D09 ANSWER_EQ_DIVISOR: the response is the divisor N2 — as a bare integer
    (w == N2), or in QR as "N2 R N2" (divisor in both slots) or "N2 R 0"
    (divisor as the quotient with no remainder). Never fires when the divisor
    equals the correct quotient (q_w == q_exp). The both-slots form defers to the
    specific QR codes that preceded the retired same-value code
    (_OP_BOTHSLOTS_DEFER); the "N2 R 0" recovery defers to any procedural /
    interchange reading (_OP_RECOVER_DEFER) so it only reclaims D36 residual."""
    n2 = s["n2"]
    if not s["is_qr"]:
        return s["wi"] is not None and s["wi"] != 0 and s["wi"] == n2
    q, r = s["q_w"], s["r_w"]
    if q is None or q == 0 or q != n2 or q == s["q_exp"]:
        return False
    if r == n2:
        return not any(_PREDICATES[c](s) for c in _OP_BOTHSLOTS_DEFER)
    if r == 0:
        return not any(_PREDICATES[c](s) for c in _OP_RECOVER_DEFER)
    return False


def _rule_D10(s: dict) -> bool:
    """
    D10 PROBLEM_COPIED_IN_QR_FORMAT
    Q R r format: (q_w == N1 AND r_w == N2) OR (q_w == N2 AND r_w == N1).
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    q, r = s["q_w"], s["r_w"]
    n1, n2 = s["n1"], s["n2"]
    return (q == n1 and r == n2) or (q == n2 and r == n1)


def _rule_D11(s: dict) -> bool:
    """D11 Q_RIGHT_R_ZERO: q_w == q_exp AND r_exp > 0 AND r_w == 0."""
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["r_exp"] == 0:
        return False
    return s["q_w"] == s["q_exp"] and s["r_w"] == 0


def _rule_D12(s: dict) -> bool:
    """D12 Q_RIGHT_R_EQUALS_DIVISOR: q_w == q_exp AND r_w == N2 EXACTLY."""
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    return s["q_w"] == s["q_exp"] and s["r_w"] == s["n2"]


def _rule_D13(s: dict) -> bool:
    """
    D13 Q_RIGHT_R_COPIED_AS_Q
    q_w == q_exp AND r_w == q_exp AND q_exp != r_exp.
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["q_w"] != s["q_exp"]:
        return False
    if s["r_w"] != s["q_exp"]:
        return False
    if s["q_exp"] == s["r_exp"]:
        return False
    return True


def _rule_D14(s: dict) -> bool:
    """D14 Q_RIGHT_R_DOUBLED: q_w == q_exp AND r_exp > 0 AND r_w == 2 × r_exp."""
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["r_exp"] == 0:
        return False
    return s["q_w"] == s["q_exp"] and s["r_w"] == 2 * s["r_exp"]


def _rule_D15(s: dict) -> bool:
    """
    D15 Q_RIGHT_R_WRONG_OTHER
    q_w == q_exp AND r_w != r_exp AND r_w != 0 AND not matching D11–D14.
    The quotient is exactly right but the remainder is some other wrong, nonzero
    value with no clear pattern — whether it is smaller than the divisor OR larger
    than it. (The r_w ≥ N2 case was a separate code, R_EXCEEDS_DIVISOR, until v35;
    merged here because the magnitude split was cosmetic: 87% of those remainders
    bore no relation to the divisor — just a wrong-and-large remainder, not a
    distinct mechanism.) Cascade order handles the "not matching D11–D14" guard.
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["q_w"] != s["q_exp"]:
        return False
    if s["r_w"] == s["r_exp"]:
        return False
    if s["r_w"] == 0:
        return False
    return True


def _rule_D16(s: dict) -> bool:
    """D16 R_RIGHT_Q_ZERO: r_exp != 0 AND r_w == r_exp AND q_w == 0."""
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["r_exp"] == 0:
        return False
    return s["r_w"] == s["r_exp"] and s["q_w"] == 0


def _rule_D17(s: dict) -> bool:
    """
    D17 R_RIGHT_Q_OFF_BY_ONE
    r_exp != 0 AND r_w == r_exp AND |q_w − q_exp| == 1.
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["r_exp"] == 0:
        return False
    return s["r_w"] == s["r_exp"] and abs(s["q_w"] - s["q_exp"]) == 1


def _d19_zero_base(s: dict) -> bool:
    """Shared gate for the quotient-zero family D20-D25: a response whose quotient
    has the SAME non-zero digits as the correct quotient but a different set or
    placement of zeros. v44: made format-agnostic (mirroring D18) - the family now
    also fires on a bare-integer response to an EXACT division (Case 3), not only in
    QR form. These quotient zero-drop/zero-add errors mostly occur on exact divisions
    (r_exp == 0) entered as a bare integer; the old QR-only gate left them unreachable
    in their natural format. This is the old single Q_ZERO_MISCONCEPTION condition;
    the six codes partition it."""
    if s["is_qr"]:
        if s["r_w"] != s["r_exp"]:
            return False
    else:
        # Case 3 (integer-only): the bare integer is the whole quotient - only
        # meaningful when the division is exact (no remainder was entered).
        if s["r_exp"] != 0:
            return False
    if s["q_w"] is None or s["q_w"] == s["q_exp"]:
        return False
    nz_qw = str(s["q_w"]).replace("0", "")
    nz_qe = str(s["q_exp"]).replace("0", "")
    if nz_qw == "" and nz_qe == "":
        return False
    return nz_qw == nz_qe


def _zero_error_kind(q_exp: int, q_w: int) -> str:
    """'extra' if q_w has MORE zeros than the correct quotient; else 'internal'
    if an internal zero of the correct quotient is missing or displaced (folds the
    rare drop-both and same-count reposition cases); else 'trailing'."""
    se, sw = str(q_exp), str(q_w)
    ze, zw = se.count("0"), sw.count("0")
    if zw > ze:
        return "extra"
    ie = ze - (len(se) - len(se.rstrip("0")))
    iw = zw - (len(sw) - len(sw.rstrip("0")))
    if ie > iw:
        return "internal"
    return "trailing"


def _dividend_has_zero(s: dict) -> bool:
    return "0" in str(s["n1"])


def _dividend_zero_kind(n1: int) -> str:
    """Where the DIVIDEND's zero sits, trailing-first: 'trailing' if the dividend
    ends in a zero (this wins even if it also has an internal zero, e.g. 400),
    'internal' if it has a non-terminal zero but does not end in zero, else
    'none'. Used by D20/D21, which are keyed on the dividend (n1) rather than the
    quotient."""
    s = str(n1)
    if s.endswith("0"):
        return "trailing"
    if "0" in s:
        return "internal"
    return "none"


def _rule_D20(s: dict) -> bool:
    """
    D20 Q_MISSING_ZERO_DIVIDEND_ENDS_IN_ZERO
    The learner dropped a zero from the answer (a missing zero, not an extra one)
    AND the DIVIDEND ends in a zero. Keyed on the dividend's zero position
    (trailing-first: a dividend ending in zero takes this code even if it also has
    an internal zero, e.g. 400). e.g. 80/4=20 -> "2", 400/5=80 -> "8".
    (6003/6=1000 -> "100" is NOT here: 6003 does not end in zero, so it is D21.)
    """
    if not _d19_zero_base(s):
        return False
    return (_zero_error_kind(s["q_exp"], s["q_w"]) != "extra"
            and _dividend_zero_kind(s["n1"]) == "trailing")


def _rule_D21(s: dict) -> bool:
    """
    D21 Q_MISSING_ZERO_DIVIDEND_HAS_INTERNAL_ZERO
    The learner dropped a zero from the answer (a missing zero, not an extra one)
    AND the DIVIDEND has an internal zero but does NOT end in zero. Keyed on the
    dividend's zero position. e.g. 204/2=102 -> "12", 6003/6=1000 R 3 -> "100 R 3".
    """
    if not _d19_zero_base(s):
        return False
    return (_zero_error_kind(s["q_exp"], s["q_w"]) != "extra"
            and _dividend_zero_kind(s["n1"]) == "internal")


def _rule_D22(s: dict) -> bool:
    """
    D22 Q_MISSING_TRAILING_ZERO_DIVIDEND_NO_ZERO
    Answer should END in a zero and the learner dropped it, dividend has NO zero
    (not cued). e.g. 41/4=10 R 1 -> "1 R 1", 321/2=160 R 1 -> "16 R 1".
    """
    if not _d19_zero_base(s):
        return False
    return _zero_error_kind(s["q_exp"], s["q_w"]) == "trailing" and not _dividend_has_zero(s)


def _rule_D23(s: dict) -> bool:
    """
    D23 Q_MISSING_INTERNAL_ZERO_DIVIDEND_NO_ZERO
    Answer has an INTERNAL zero, dividend has NO zero - hardest case: produce a
    mid-answer zero with no dividend cue. e.g. 1213/3=404 R 1 -> "44 R 1", 832/8=104 -> "14".
    """
    if not _d19_zero_base(s):
        return False
    return _zero_error_kind(s["q_exp"], s["q_w"]) == "internal" and not _dividend_has_zero(s)


def _rule_D24(s: dict) -> bool:
    """
    D24 Q_EXTRA_INTERNAL_ZERO_DIVIDEND_HAS_ZERO
    Quotient carries an EXTRA zero, dividend contains a zero (gave that dividend
    zero its own quotient step, 0/n2=0). e.g. 60/5=12 -> "102".
    """
    if not _d19_zero_base(s):
        return False
    return _zero_error_kind(s["q_exp"], s["q_w"]) == "extra" and _dividend_has_zero(s)


def _rule_D25(s: dict) -> bool:
    """
    D25 Q_EXTRA_INTERNAL_ZERO_DIVIDEND_NO_ZERO
    Quotient carries an EXTRA zero, dividend has NO zero - a phantom zero with no
    structural cue anywhere. e.g. 93/7=13 R 2 -> "103 R 2".
    """
    if not _d19_zero_base(s):
        return False
    return _zero_error_kind(s["q_exp"], s["q_w"]) == "extra" and not _dividend_has_zero(s)


def _chunk_remnant(s: dict) -> bool:
    """
    Internal deferral guard (NOT a tagged code). True when the response closes the
    division identity q_w × N2 + r_w == N1 with r_w ≥ 2·N2 (and q_w > 0, q_w != q_exp).
    These were a tagged code (pre-v38 'D20' CHUNK_DIVISION) until v33; that code is retired because every
    such case is identity-closing UNDER-DIVISION (the learner under-divided step by
    step, leaving a remainder of two or more whole divisors — e.g. 706÷9 -> "69 R 85",
    9×69+85 = 706). There is no distinct "chunking" mechanism here: combining digits
    is mandatory normal procedure (the leading digit < divisor), not a chosen method,
    so the error is under-division and belongs to D28. This guard is retained so the
    off-by-one code (D34) still defers these cases past itself, letting D28
    UNDER_DIVISION claim them rather than mislabelling them as off-by-one (D34).
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    q, r = s["q_w"], s["r_w"]
    if q is None or r is None:
        return False
    if q <= 0:
        return False
    if q == s["q_exp"]:
        return False
    if r < 2 * s["n2"]:
        return False
    return q * s["n2"] + r == s["n1"]


def _rule_D34(s: dict) -> bool:
    """
    D34 Q_OFF_BY_ONE — quotient off by exactly one, in either format.
    Integer mode: |w − q_exp| == 1.
    QR mode: r_exp != 0 AND |q_w − q_exp| == 1 AND r_w != r_exp AND not the chunk-remnant case (the _chunk_remnant guard).
    v14: extended to integer mode and cascade-positioned just before D35, so
    off-by-one is carved out of the near-miss net without stealing from the
    specific integer rules (D30–D18).
    """
    if not s["is_qr"]:
        return s["wi"] is not None and abs(s["wi"] - s["q_exp"]) == 1
    if not _qr_active(s):
        return False
    if s["r_exp"] == 0:
        return False
    if s["q_w"] is None:
        return False
    if abs(s["q_w"] - s["q_exp"]) != 1:
        return False
    if s["r_w"] == s["r_exp"]:
        return False
    if _chunk_remnant(s):
        return False
    return True


def _rule_D30(s: dict) -> bool:
    """
    D30 SINGLE_STEP_TABLE_SLIP — wrong multiplier for a single-step table fact.
    When the correct quotient is itself a times-table fact (1 ≤ q_exp ≤ 10), the
    learner solves by missing-factor recall — "N2 × ? = N1" — and writes their
    proposed multiplier. A wrong proposal is a table row 1 ≤ w ≤ 10, w != q_exp,
    that is proportionate to the answer (w ≤ 2·q_exp) — e.g. 12÷3 -> 6 or 2 or 5
    (correct 4). This unifies what earlier versions split across three codes by
    arithmetic accident — a divisor multiple (old D27), an off-by-one (D34), or a
    within-band value (D35) — none of which is a distinct cognitive event in a
    missing-factor pedagogy: all are one table slip. Integer responses only.
    v25: the proportionality cap w ≤ 2·q_exp keeps a slip from being a wild,
    disproportionate guess: 10÷5 -> 8 (proposing row 8 for an answer of 2) is not
    a table slip and falls to D36; w > 10 likewise is not a table-row proposal.
    v26: the cap is symmetric — q_exp/2 ≤ w ≤ 2·q_exp (the proposal is within a
    factor of 2 of the answer on both sides). The lower half-bound catches a
    disproportionate LOW guess at a large quotient — 72÷9 -> 1 (row 1 for an
    answer of 8) — that v25 still admitted. Such cases leave D30: most to D36,
    and the q_exp=10 first-digit reads (50÷5 -> 1) to D31 where they belong.
    Structural reads (n1×n2, n1±n2, n1, concatenations) fire earlier and are kept.
    """
    if s["is_qr"] or s["wi"] is None:
        return False
    qe = s["q_exp"]
    if qe is None or not (1 <= qe <= 10):
        return False
    w = s["wi"]
    if w == qe:
        return False
    if not (1 <= w <= 10):
        return False
    return qe / 2 <= w <= 2 * qe


def _rule_D19(s: dict) -> bool:
    """
    D19 NO_DIGIT_BY_DIGIT_DIVISION — fell back on the table instead of dividing.
    The learner does not recognise the problem needs digit-by-digit (long)
    division, so they recall the divisor's table up to its ×10 ceiling and stop:
    they write quotient 10 when the correct quotient exceeds 10, leaving a
    remainder ≥ divisor (e.g. 60÷5 -> "10" or "10 R 10"; correct is 12).
    Detected on the written quotient (w in quotient-only, q_w in Q-R) == 10 with
    q_exp > 10. Cascade-positioned ahead of the chunking/remainder codes so this
    specific ×10-ceiling signature is named, not folded into generic "chunked".
    Reachability gate: the ×10 table multiple must actually fit in the leading
    chunk the learner works with — divisor×10 must be <= the leftmost
    (digits-of-divisor + 1) digits of the dividend (2 digits for a single-digit
    divisor, 3 for a two-digit one). Where it cannot fit (706÷9: 9×10=90 > "70"),
    "10" could not have come from maxing the table, so the row is not D19.
    """
    qe = s["q_exp"]
    if qe is None or qe <= 10:
        return False
    q = s["q_w"] if s["is_qr"] else s["wi"]
    if q != 10:
        return False
    n1, n2 = s["n1"], s["n2"]
    lead = str(n1)[:len(str(n2)) + 1]
    return n2 * 10 <= int(lead)


def _rule_D29(s: dict) -> bool:
    """
    D29 STEP_REMAINDER_IGNORED — digit-wise division that drops the remainder.
    Learner divides each dividend digit by the divisor independently and never
    carries the remainder to the next place, e.g. 90÷2 -> "40" (9//2=4, 0//2=0),
    75÷3 -> "21" (7//3=2, 5//3=1). Detected when the response equals that
    digit-by-digit floor division and is wrong; restricted to a leading digit
    that divides to ≥ 1 (str(N1)[0]//N2≥1) so ambiguous leading-zero collapses
    (18÷3 -> "2", mostly ANSWER_EQ_DIVISOR) are not swept in. Cascade-positioned
    just ahead of D30 so a carry-drop whose value is a low multiple of the
    divisor is tagged here, not as a table-recall error. A wrong quotient of
    exactly 10 is excluded: that is the times-table ceiling (divisor × 10),
    which signals under-division (maxed the table and stopped), not a carry-drop.
    """
    if s["is_qr"] or s["wi"] is None:
        return False
    w, n1, n2, qe = s["wi"], s["n1"], s["n2"], s["q_exp"]
    if w == qe:
        return False
    digits = str(n1)
    if len(digits) < 2 or n2 < 2:
        return False
    if int(digits[0]) // n2 < 1:
        return False
    digitwise = int("".join(str(int(c) // n2) for c in digits))
    if w != digitwise:
        return False
    # A wrong quotient of exactly 10 is the times-table ceiling (divisor × 10):
    # the learner used the largest recalled multiple and stopped, leaving a
    # remainder ≥ divisor (e.g. 72÷6 -> 10 is 6×10=60, not 7//6 then 2//6).
    # That is table-ceiling under-division, not a digit-wise carry-drop.
    if w == 10:
        return False
    return True


def _rule_D28(s: dict) -> bool:
    """
    D28 UNDER_DIVISION — the answer satisfies the division identity exactly,
        Dividend = Divisor × Quotient + Remainder   (N1 == N2·q_w + r_w),
    but the quotient is wrong. When that identity holds with a wrong quotient the
    remainder is necessarily ≥ the divisor (the only way to close the identity with
    0 ≤ r_w < N2 is the correct answer), so this is precisely under-division: the
    learner divided consistently — every multiply and subtract reconciles — but
    stopped short, leaving a remainder that still contains one or more whole
    divisors. Example: 706 ÷ 9 -> "77 R 13" (9×77 + 13 = 706 exactly; should have
    taken 9×8). ONLY identity-closing cases belong here. An answer that does NOT
    reconstruct to N1 (e.g. 706 ÷ 9 -> "77 R 3", which makes 696) reflects a
    calculation error somewhere, not under-division, and is left to the off-by-one
    / near-miss codes (D34/D35). The multi-step chunking subset (remainder ≥ 2
    divisors) is the retired CHUNK_DIVISION case (folded in here at v33); the _chunk_remnant guard makes the off-by-one code defer it, so D28 claims it together with the one-divisor-short cases.
    """
    if not s["is_qr"] or s["q_w"] is None or s["r_w"] is None:
        return False
    qw, rw, qe = s["q_w"], s["r_w"], s["q_exp"]
    if qw <= 0 or qw == qe:
        return False
    return qw * s["n2"] + rw == s["n1"]


def _rule_D26(s: dict) -> bool:
    """
    D26 INCOMPLETE_DIVISION — the learner ran the long-division algorithm correctly
    for the first few steps, then stopped and reported the running quotient and the
    working remainder of the last step they did, without bringing down the remaining
    digit(s). Signature: N2 × q_w + r_w equals a LEADING PREFIX of the dividend (the
    digits consumed so far) rather than the full dividend, with 0 ≤ r_w < N2 (a valid
    mid-algorithm step state). Equivalently, q_w is the correct quotient of the
    leading j digits of N1 and r_w is that step's remainder, for some j < (number of
    digits of N1). Example: 924 ÷ 8 -> "11 R 4" — did 9÷8=1 R 1, brought down 2 ->
    12÷8=1 R 4 (quotient "11", remainder 4), then stopped instead of bringing down
    the 4 (8×11+4 = 92, the leading two digits of 924). Distinct from D28
    UNDER_DIVISION, which closes against the FULL dividend with r_w ≥ N2. Positioned
    after the zero family (D20-D25, so terminal-zero drops keep their "zero misconception" reading) so
    these are recognised by mechanism rather than left in the unclassified residual (D36). Remedial: complete the algorithm —
    keep bringing down digits until none remain; the answer is finished only when
    every digit of the dividend has been processed.
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    qw, rw = s["q_w"], s["r_w"]
    if qw is None or rw is None:
        return False
    if qw <= 0 or qw == s["q_exp"]:
        return False
    if rw >= s["n2"]:                       # r_w ≥ divisor is under-division (D28), not a valid mid-step remainder
        return False
    digits = str(s["n1"])
    for j in range(1, len(digits)):         # proper prefix => stopped before the last digit
        partial = int(digits[:j])
        if partial < s["n2"]:               # no non-zero quotient digit produced from this prefix yet
            continue
        if partial // s["n2"] == qw and partial % s["n2"] == rw:
            return True
    return False


def _rule_D31(s: dict) -> bool:
    """
    D31 FIRST_DIGIT_QUOTIENT
    Integer response; q_exp has ≥2 digits; w == int(str(q_exp)[0]);
    first digit != 0.
    """
    if s["is_qr"] or s["wi"] is None:
        return False
    q_exp = s["q_exp"]
    if n_digits(q_exp) < 2:
        return False
    first_digit = int(str(q_exp)[0])
    if first_digit == 0:
        return False
    return s["wi"] == first_digit


def _rule_D32(s: dict) -> bool:
    """
    D32 LAST_DIGIT_QUOTIENT
    Integer response; q_exp has ≥2 digits; w == int(str(q_exp)[-1]);
    last digit != 0.
    """
    if s["is_qr"] or s["wi"] is None:
        return False
    q_exp = s["q_exp"]
    if n_digits(q_exp) < 2:
        return False
    last_digit = int(str(q_exp)[-1])
    if last_digit == 0:
        return False
    return s["wi"] == last_digit


def _rule_D33(s: dict) -> bool:
    """
    D33 CONCAT_OPERANDS
    The response is the two operands written side by side, either as a bare
    integer (w == N1N2 or N2N1) or in QR form as "<concat> R 0" / "<concat> R
    <concat>" (the concatenation in the quotient slot, with a zero or duplicated
    remainder). The concatenated value is large and distinctive, so it matches no
    earlier cascade code; positioned late among the structural reads.
    """
    n1, n2 = s["n1"], s["n2"]
    cc = (int(str(n1) + str(n2)), int(str(n2) + str(n1)))
    if not s["is_qr"]:
        wi = s["wi"]
        if wi is None or wi == s["q_exp"]:
            return False
        return wi in cc
    q, r = s["q_w"], s["r_w"]
    if q is None or q == s["q_exp"] or q not in cc:
        return False
    return r in (0, q)


def _rule_D18(s: dict) -> bool:
    """
    D18 Q_EXTRA_TRAILING_ZEROS — the quotient is the correct value with
    1–3 extra trailing zeros, in either format. Integer: w == q_exp × 10^k.
    QR-eligible: q_w == q_exp × 10^k. v14: extended to QR and cascade-positioned
    ahead of the zero family (D20-D25) so this specific trailing-zero pattern is labelled here rather
    than as a generic zero misconception.
    """
    if s["q_exp"] == 0:
        return False
    val = s["q_w"] if s["is_qr"] else s["wi"]
    if val is None or val == s["q_exp"]:
        return False
    return any(val == s["q_exp"] * (10 ** k) for k in (1, 2, 3))


def _rule_D35(s: dict) -> bool:
    """
    D35 QUOTIENT_NEAR_MISS — response close to the correct quotient.
    v15 (Band C): scale-aware near band, NEAR = |answer − q_exp| ≤ min(max(5,
    q_exp/3), 50). v21: also applies to a QR quotient when r_w == r_exp. v22:
    bottom clamp for q_exp ≤ 1.
    v24: D35 fires only when q_exp > 10. At table scale (q_exp ≤ 10) there is no
    "near-miss / estimate" behaviour in this pedagogy — a wrong quotient there is
    a table slip (D30) when it is a plausible multiplier, otherwise unclassified
    (D36). Large-quotient off-by-ones are taken first by D28, so D35 now holds the
    genuine multi-digit near-misses that are off by two or more.
    v27: the absolute floor of 5 is removed; the band is purely q_exp/3 (capped at
    50). The floor only inflated the window for q_exp 11–14 (q_exp/3 already ≥ 5
    at q_exp = 15), letting a 45%-off response read as "near"; the band is now a
    constant ±⅓ of the answer at every scale. Worst near-miss drops 45% -> 33%.
    """
    qe = s["q_exp"]
    if qe is None or qe <= 10:
        return False
    band = min(qe / 3, 50)
    if s["is_qr"]:
        if not _qr_active(s):
            return False
        qw, rw = s["q_w"], s["r_w"]
        if qw is None or rw is None:
            return False
        if rw != s["r_exp"]:
            return False
        if qw == qe:
            return False
        return abs(qw - qe) <= band
    if s["wi"] is None:
        return False
    w = s["wi"]
    if w == qe:
        return False
    return abs(w - qe) <= band


def _rule_D27(s: dict) -> bool:
    """
    D27 QR_RIGHT_INTERCHANGED — both values correct but each in the wrong slot.
    q_w == r_exp AND r_w == q_exp, with q_exp != r_exp so the swap is real: the quotient
    is written in the remainder box and the remainder in the quotient box.
    Positioned after the remainder-right and procedural codes and ahead of the
    under-division / near-miss reads, so a clean slot-swap is named before the
    messier identity-closing interpretations.
    """
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    if s["q_w"] is None or s["r_w"] is None:
        return False
    if s["q_exp"] == s["r_exp"]:
        return False
    return s["q_w"] == s["r_exp"] and s["r_w"] == s["q_exp"]


def _rule_D36(s: dict) -> bool:
    """
    D36 UNCLASSIFIED_NEAR_RANDOM
    Fallback. Catches everything that fell through.
    """
    if s["raw"] is None:
        return False
    return True


def _rule_D07(s: dict) -> bool:
    """D07 CORRECT_QUOTIENT_IN_REMAINDER_SLOT: a placement error where the learner
    echoes the dividend N1 in the quotient box and writes the CORRECT quotient in
    the remainder box, e.g. 648/4 -> "648 R 162" (162 is correct) or 60/5 ->
    "60 R 12". The computation is right; only the placement is wrong, so the
    remedial is format/recording, not arithmetic. Distinct from D08 (dividend as
    the answer, wrong computation) and from D27 (Q and R swapped with each other).
    Gated to a multi-digit correct quotient (q_exp >= 10) so the
    remainder-equals-quotient match is not coincidental, excludes q_exp == N2
    (the D10 problem-copy form N1 R N2), and excludes q_exp == N1 (trivial)."""
    if not _qr_active(s):
        return False
    if not s["is_qr"]:
        return False
    q, r = s["q_w"], s["r_w"]
    if q is None or r is None:
        return False
    q_exp = s["q_exp"]
    return (
        q == s["n1"]
        and r == q_exp
        and q_exp >= 10
        and q_exp != s["n1"]
        and q_exp != s["n2"]
    )


# Predicate registry
_PREDICATES: dict[str, Callable[[dict], bool]] = {
    code: globals()[f"_rule_{code}"] for code in DIVISION_ERROR_NAMES.keys()
}


# ---------------------------------------------------------------------------
# Cascade traversal
# ---------------------------------------------------------------------------

def _cascade_first_match(signals: dict) -> str:
    for code in DIVISION_CASCADE_ORDER:
        if _PREDICATES[code](signals):
            return code
    return "D36"


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def _priority_weight(code: str) -> float:
    pos = DIVISION_CASCADE_ORDER.index(code) + 1
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
    normalized.sort(key=lambda x: (-x[1], DIVISION_CASCADE_ORDER.index(x[0])))
    return normalized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SCORE_INCLUSION_THRESHOLD = 0.01

DIVISION_PRIORS_BY_GRADE: dict[Optional[int], dict[str, float]] = {
    None: DIVISION_PRIORS_ALL,
}


def classify(
    n1: int | str,
    n2: int | str,
    learner_response: object,
    learner_grade: Optional[int] = None,
    system_expects_remainder: Optional[bool] = None,
    *,
    return_debug: bool = False,
) -> ClassifyResult:
    """
    Classify a Division response into one or more misconception codes.

    Args:
      n1:                       dividend
      n2:                       divisor
      learner_response:         integer or "Q R r" string
      learner_grade:            optional grade override for prior selection
      system_expects_remainder: True if system expects QR-format response,
                                False if integer-only. If None (default),
                                inferred from the math: True iff r_exp > 0.
      return_debug:             if True, ClassifyResult.debug includes signal dict
    """
    n1_p = parse_operand(n1)
    n2_p = parse_operand(n2)
    if n1_p is None or n2_p is None or n2_p == 0:
        return ClassifyResult(
            cascade_code="D36",
            cascade_name=DIVISION_ERROR_NAMES["D36"],
            ranked=[("D36", DIVISION_ERROR_NAMES["D36"], 1.0)],
            debug={"error": "operand parse failed or N2=0"} if return_debug else {},
        )

    parsed = parse_qr_response(learner_response)
    q_exp = n1_p // n2_p
    r_exp = n1_p % n2_p

    # Default system_expects_remainder to "what the math says"
    if system_expects_remainder is None:
        system_expects_remainder = (r_exp > 0)

    # ---- Four-case framing ----
    learner_gave_qr = parsed["is_qr"]

    if system_expects_remainder and learner_gave_qr:
        # Case 1
        case_id = 1
        eff_q = parsed["q_w"]
        eff_r = parsed["r_w"]
        qr_eligible = True
        is_qr_for_predicates = True
    elif system_expects_remainder and not learner_gave_qr:
        # Case 2: synthesize r_w = 0 from absent remainder
        case_id = 2
        eff_q = parsed["wi"]
        eff_r = 0 if parsed["wi"] is not None else None
        qr_eligible = True
        # Treat for predicates as if response were "wi R 0" — QR rules see is_qr=True
        is_qr_for_predicates = parsed["wi"] is not None
    elif not system_expects_remainder and not learner_gave_qr:
        # Case 3: integer-only mode
        case_id = 3
        eff_q = parsed["wi"]
        eff_r = None
        qr_eligible = False
        is_qr_for_predicates = False
    else:
        # Case 4: not system_expects_remainder AND learner gave QR
        case_id = 4
        eff_q = parsed["q_w"]
        eff_r = parsed["r_w"]
        qr_eligible = True
        is_qr_for_predicates = True

    # ---- Build signals dict ----
    signals: dict = {
        "n1": n1_p,
        "n2": n2_p,
        "q_exp": q_exp,
        "r_exp": r_exp,
        "raw": parsed["raw"],
        # The predicates use "is_qr" to decide whether to fire; in Case 2 we
        # synthesize is_qr=True so QR rules can fire on integer-only input
        # treated as "Q R 0".
        "is_qr": is_qr_for_predicates,
        "wi": parsed["wi"],
        "q_w": eff_q,
        "r_w": eff_r,
        "qr_eligible": qr_eligible,
        "int_eligible": not qr_eligible,
        "case_id": case_id,
        "system_expects_remainder": system_expects_remainder,
    }

    # ---- Correctness check (per the four cases) ----
    if case_id == 3:
        # Compare wi to q_exp only (no R consideration)
        if parsed["wi"] is not None and parsed["wi"] == q_exp:
            return ClassifyResult(
                cascade_code="CORRECT", cascade_name="", ranked=[],
                debug=signals if return_debug else {},
            )
    else:
        # Cases 1, 2, 4: compare (eff_q, eff_r) to (q_exp, r_exp)
        if eff_q is not None and eff_q == q_exp and eff_r is not None and eff_r == r_exp:
            return ClassifyResult(
                cascade_code="CORRECT", cascade_name="", ranked=[],
                debug=signals if return_debug else {},
            )

    # ---- Unparseable response — D01 ----
    if parsed["raw"] is None:
        return ClassifyResult(
            cascade_code="D01",
            cascade_name=DIVISION_ERROR_NAMES["D01"],
            ranked=[("D01", DIVISION_ERROR_NAMES["D01"], 1.0)],
            debug=signals if return_debug else {},
        )

    # ---- Cascade ----
    cascade_primary = _cascade_first_match(signals)

    matched = [code for code in DIVISION_CASCADE_ORDER if _PREDICATES[code](signals)]
    if "D36" in matched and len(matched) > 1:
        matched = [c for c in matched if c != "D36"]

    priors = DIVISION_PRIORS_BY_GRADE.get(learner_grade) or DIVISION_PRIORS_ALL
    ranked_full = _compute_scores(matched, cascade_primary, priors)
    ranked = [
        (c, DIVISION_ERROR_NAMES.get(c, ""), s)
        for c, s in ranked_full
        if s >= SCORE_INCLUSION_THRESHOLD
    ]

    return ClassifyResult(
        cascade_code=cascade_primary,
        cascade_name=DIVISION_ERROR_NAMES.get(cascade_primary, ""),
        ranked=ranked,
        debug=signals if return_debug else {},
    )
