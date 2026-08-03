"""
Subtraction misconception classifier (codes S01–S31), v29.

v29 — Promotion to a clean integer version. No behavioral or code change:
    consolidates the v28 wrong-operation insert + renumber (S07
    WRONG_OPERATION_MULTIPLICATION, S08 WRONG_OPERATION_DIVISION; former
    S07–S29 shifted +2) and the v28.1 co-occurring X-0 / X-X identity
    refinement (S26 Final, S27 co-flag) under one version label.

v28.1 — Co-occurring column identities. S26 (X-0=X failure) and S27 (X-X=0
    failure) are mirror rules; each previously disqualified if ANY diff column
    was the other type, so a problem where the kid fails BOTH an X-0 column and
    an X-X column (rest correct) fell through to S30 MULTI_COLUMN_SLIP — e.g.
    621-601='11' (units wrote operand 1 instead of 0 = X-X failure; tens wrote
    1 instead of 2 = X-0 failure; correct 20). The per-column tests are
    UNCHANGED; S26/S27 now merely TOLERATE the other identity's failure column
    while still each requiring >=1 of its own type. Result for such mixed cases:
    both S26 and S27 fire (so the flag set carries S26, S27 and S30), and the
    Final code resolves to S26 by cascade order. Pure X-0 and pure X-X answers
    are unaffected. ~22 rows / 93 freq corpus-wide.

v28 — Added two wrong-operation codes and renumbered. New S07
    WRONG_OPERATION_MULTIPLICATION (w == N1*N2) and S08
    WRONG_OPERATION_DIVISION (w == N1//N2, exact) inserted right after
    S06, so they win above the slip codes that currently absorb
    divide-instead answers (e.g. 18-9='2' was tagged a single-column
    slip). All former S07–S29 shifted +2 (S07->S09 ... S29->S31);
    cascade is the trivial sorted S01–S31. NOTE: every S-code below,
    INCLUDING in the historical v19/v27 notes, uses the NEW v28
    numbering, not the number it carried when that note was written.

v27 — Two-layer tagging. The corpus flag columns (the multi-hot S01..S31
    set) now record EVERY applicable interpretation — every rule whose
    mechanism reconstructs the learner's typed answer — while the single
    Final_Error_Code remains the cascade/deferral winner (classify(), which
    is UNCHANGED). applicable_codes() computes the flag set: the post-deferral
    matched set PLUS any rule that deferred to a higher-priority match but
    whose own pattern still fires AND reconstructs the answer — S06 (wrong-op
    addition), S10 (n1-units-digit-as-tens), S13 (operand digit reversal),
    S20 (borrow-writes-zero). Loose width-blind matches (e.g. S09 on '009')
    and mechanisms that do not reproduce the answer (e.g. S16 on a zero-top
    column, which the engine partitions to S23) are excluded. ~140 corpus
    rows gained a flag; AL, _FREQ_TABLE, priors and the Taxonomy are all
    AL-based and therefore unchanged. Example: 10-3='13' flags {S06, S23}
    (addition + zero-top-copies-N2) with Final_Error_Code S23.

v26 — S21 BORROW_SKIPS_INTERIOR_ZERO now fires for full-width answers whose
    parsed value carries leading zeros (e.g. 303-204='009', 100-7='003',
    601-518='003'). The digit-count guard measured the PARSED integer
    (009 -> 9, one digit) against the correct answer (99, two digits) and
    wrongly rejected these genuine borrow-skips; it now measures the digits
    the learner actually wrote (the raw string), so a full-width borrow-skip
    like '009' qualifies while a true units-only answer like '9' does not.
    S09 (UNITS_ONLY) and S05 (N1_OR_N2_COPIED) now defer to S21 when the
    borrow-skip story holds, so these tag as the more-specific S21 rather
    than "units only"/"operand copy". 23 corpus rows re-tagged to S21 (20
    from S09, 2 from S05, 1 from S31); _FREQ_TABLE/priors and the corpus
    Taxonomy resynced.

v25 — S21 BORROW_SKIPS_INTERIOR_ZERO tightened. A genuine borrow-skip differs
    from the correct answer ONLY at the interior-zero pass-through column(s)
    (written 0 instead of the truth 9); EVERY other column, including the
    borrow-trigger units, must equal the correct answer. Pre-v25 the rule only
    required non-borrow columns to be "valid" (it accepted the column-wise
    |d1-d2| value), so no-borrow column-wise answers with a 0 at the interior
    zero were mis-tagged S21 — e.g. 601-518='107' (units 7=|1-8|, hundreds
    1=|6-5| → no borrow happened). Those now fall through to S31 (no single
    mechanism explains them). Cascade tags re-derived; _FREQ_TABLE/priors and
    the corpus Taxonomy resynced accordingly.

v24 — S15 renamed TENS_ONLY_SUBTRACTION → UNITS_DIGIT_DROPPED (name only:
    code "S15", detection logic, and tag membership all unchanged). The
    rule matches wi == correct // 10 — the correct answer with its units
    digit removed; "tens-only" was a misnomer for 3+ digit operands
    (9175-5205='397' includes hundreds), while the detection already frames
    it as dropping the units column. No behavioural change; the corpus
    Final_Error_Name was updated for S15 rows accordingly.

v23 — three precision fixes to the identity/zero rules, all closing "diagnose
    a misconception from an incomplete or mismatched view of the response"
    holes. (1) S23 Tier 1 now requires the COMPLETE no-borrow S23 procedure to
    reproduce wi (full-mechanism gate via _e20_mechanism_explains_wi), not just
    per-column digit copies at zero-top columns — 50-28='98'/'18' -> S30, not
    S23. (2) S27's split Tier 1 (effective digits, equal length) and Tier 3
    (raw digits, extra-digit, borrow-excluded) are UNIFIED into one effective-
    digit, completeness-gated column tier; it recovers extra-digit borrow-
    induced X-X the split version dropped (1000-991='999', 601-518='583',
    2352-1844='1548'). (3) Both S26 and S27 gain symmetric engagement-coverage
    guards: a column-level identity fires only when width-1 <= answer length
    <= width (under-engagement = a give-up read off the bottom column;
    over-engagement = garbage longer than the problem). Combined-corpus impact
    (169,737 rows): S23 ~14,341 freq leave (-> S30/S31/S29/S16); S26 ~3,786
    freq (under-guard) + ~7,452 freq (over-guard) -> S31; S27 +~126 freq
    recovered, ~1,045 freq of over/under-engaged over-claims shed. Most
    reroutes land in S31 — the pass trades confident-but-wrong tags for an
    explicit "unclassified," so S31 grows by ~15k freq by design. Codes
    unchanged (S01-S31). Per-entry examples reflect the version described, not
    necessarily current behaviour.

v22 — S26 fully engagement-gated (canonical wi==0 branch removed). Previously
    S26 had two paths: a per-column engagement test AND a "canonical" branch
    that fired whenever wi==0 and every non-zero digit of the correct answer
    sat at an X-0 column. The canonical branch inferred an X-0 identity failure
    from columns the kid never wrote (e.g. 100-0='0', 40-0='0', 621-601='0' —
    one digit written, higher columns absent), which contradicts S26's own
    stated principle that failure cannot be inferred from absence, and it
    disagreed with the per-column branch on what an X-0 column is (105-5='0'
    already fell to S09). v22 removes the canonical branch; S26 is governed
    solely by per-column engagement and now means ONE thing: a wrong digit at
    a column the kid demonstrably engaged with, where N2 contributes nothing.
    5-0='0' stays S26 (units engaged, real diff); 100-0='0' / 105-5='0' /
    40-0='0' become S09 (units-only, no inference from absence). On the Combined
    corpus this moves 8 rows / ~597 freq S26->S09 (+a couple to S01). Only the
    canonical branch was removed; no other logic changed; codes unchanged.

v21 — S16 wins over S23 when the borrowing gap is evidenced (conditional
    deferral). Previously S16 Tiers 1-4 deferred to S23 UNCONDITIONALLY when
    S23 fired. But at a zero-top column, bigger-minus-smaller (|0-d|=d)
    coincides with zero-top-copy (d), so a full bigger-minus-smaller response
    on a problem with an interior/leading zero (e.g. 601-518='117') would fire
    S23 via its single zero-top column and S16 would defer — handing the row to
    the LESS complete, less fundamental diagnosis (S23 explains one column; S16
    explains all of them). Fix: suppress the S23 deferral when there is a
    NON-zero-top column where a borrow was needed and the kid did bigger-minus-
    smaller (wrote |top-bottom|). That column evidences the fundamental "doesn't
    borrow at all" gap (S16), which outranks the zero-top-specific S23. Zero-top-
    ONLY borrow cases (90-6='96', 50-28='38', 10-3='13' — where bigger-minus-
    smaller and zero-top-copy are indistinguishable) keep the S23 reading. Only
    the deferral changed; no rule's own matching logic changed; codes unchanged
    (S01-S31). On the Combined corpus this moves ~164 rows / ~2.2k freq S23->S16.

v20 — S26 chain-aware purity (borrow-chain leakage fix).
    v19.28's S26 guard used borrow_columns(), which flags only the column
    that NEEDED a borrow — not the 0->9 pass-through columns of a borrow
    chain, nor the lender at the top. So `X0...0 - small` problems
    (10000-9='99991', 6006-97='5009', 5000-1='499') leaked into S26 even
    though the engaged X-0 column sits buried inside a borrow chain — those
    are borrow-across-zeros errors, not the X-0 = X identity failure, and a
    teacher acting on the S26 tag would drill X-0 instead of borrowing.
    Fix: a column is a pure X-0 identity column iff the borrow simulation
    never touched it (n1_effective_digits_after_borrow[k] == original N1
    digit). Borrow-touched X-0 columns no longer qualify, so S26 fires only
    where the identity genuinely holds. Genuine X-0 cases are unchanged
    (17-10='6', 53-20='32', 59-0='5', canonical 5-0='0' all stay S26).
    Per-column branch only; the canonical (wi==0) branch is unchanged. No
    other rule's logic changed; codes range unchanged (S01–S31).

Note on methodology: starting from v19.12, this classifier optimizes for
PEDAGOGICAL ACCURACY (remediation readiness) over corpus agreement. The
corpus tags were derived from an initial loose ruleset and contain
"kid wrote X somewhere → tag Y" patterns that conflate distinct
misconceptions. Where corpus agreement and accurate diagnosis diverge,
we choose accurate diagnosis. Cumulative Option-C cost reflects this
deliberate choice.

================================================================================
DEFERRAL & PRECEDENCE RATIONALE  (read this first for independent review)
================================================================================
The cascade resolves co-firing rules by STRICT NUMERIC ORDER: when several rules
match a response, the lowest-numbered code wins. A "deferral" is an EXPLICIT
OVERRIDE of that order — a clause `if _rule_Y(s): return False` inside rule X
forces X to yield to Y. Deferrals are load-bearing: they encode which
misconception is the better DIAGNOSIS when one wrong answer is consistent with
more than one procedure. Every deferral in this file falls into one of three
groups.

(A) STRUCTURAL — "the more specific misconception wins." Not judgment calls.
    - S01, S09, S14, S15, S21  ->  S26 : when a short / all-zeros / units-only /
      dropped-leading-digit response ALSO fits the X-0 identity-failure story,
      S26 wins. Grounding (v19.25): at an X-0 column there is nothing to
      compute, so a wrong digit there is an identity failure — not a slip, an
      omission, or a copy. (As of v22 S26 is engagement-gated, so these no
      longer pull in pure short-response ABSENCE: 100-0='0' now stays S09.)
    - S21 -> S23/S24, S15 -> S16, S16 -> S17, S16 -> S18/S20/S21, S10 -> S19,
      S13 -> S15 : the rule naming the more specific borrow/zero behaviour wins
      over the more generic one (e.g. a specific interior-zero borrow story
      beats the generic "bigger-minus-smaller").

(B) JUDGMENT CALLS — pedagogical decisions; please scrutinise these. Neither is
    provable from the answer alone, so each is a deliberate choice of which
    reading to surface. Documented again at the call site.

    S06 -> S23   WRONG_OPERATION_ADDITION  defers to  BORROW_ZERO_TOP_COPIES_N2
      For an X0 - Y problem, "the kid added" and "the kid wrote N2's digit at
      the zero-top column" yield the IDENTICAL answer (0 + d = d = copy d); no
      discriminator can separate them in this geometry (the deferral fires only
      when S23's full mechanism reproduces wi — see _e20_mechanism_explains_wi).
      DECISION: default to S23 (the zero-top concept) because (1) it is the more
      actionable conceptual remediation, and (2) a genuine "adds instead of
      subtracts" learner is caught UNAMBIGUOUSLY on non-zero-top problems, where
      adding does not coincide with any borrow mechanism — so reserving the
      zero-top cases for S23 does not lose the adders. This is a PREVALENCE
      call: reverse it if, in your cohort, zero-top answers are more often
      operation-confusion than a true zero-top-copy rule.

    S16 -> S23   BORROW_FORGOTTEN_BIGGER_MINUS_SMALLER  defers to  zero-top-copy
      S16 ("doesn't know if/why/how to borrow — does bigger-minus-smaller
      everywhere") is a MORE FUNDAMENTAL gap than the zero-top-specific S23. At
      a zero-top column bigger-minus-smaller (|0-d|) and zero-top-copy (d)
      coincide, so a full bigger-minus-smaller answer would otherwise be claimed
      by S23 through its single zero-top column. DECISION (v21): S16 defers to
      S23 ONLY when the answer offers no other evidence — i.e. the only borrow
      is at a zero-top column. When a NON-zero-top column needed a borrow and
      the kid did bigger-minus-smaller there (wrote |top-bottom|), that proves
      the fundamental gap and S16 WINS. Worked contrast: 601-518='117' -> S16
      (units 8-1=7 is the non-zero-top evidence); 90-6='96' and 50-28='38' ->
      stay S23 (zero-top-only borrow; genuinely ambiguous, so the concept-first
      reading is kept).

(C) MECHANISM-COMPLETENESS GATING — defer only on a WHOLE-answer match.
    S20 -> S23, and S21 -> S23, defer to the zero-top family ONLY when
    subtract_columnwise_abs(n1, n2) == wi — i.e. the ENTIRE response is the
    uniform bigger-minus-smaller mechanism, not merely one signature column.
    Same "validate against the whole response, not one column" principle that
    governs S26 (v22) and the S16<->S23 split above.

(D) CASCADE-LEVEL OVERRIDE — not a deferral; lives in _derive_cascade_primary.
    The "leading-zero raw" override: when the kid's raw response carries leading
    zeros (len(raw) > n_digits(wi)) AND the parsed value still fits the problem
    width AND S26 independently fires, the primary is forced to S26, overriding
    the numeric cascade. Rationale: leading zeros are evidence the kid ENGAGED the
    higher columns, which contradicts the "kid wrote a shorter answer" cognitive
    story that several parsed-value rules (S05, S15, S16, S23, ...) assume; rather
    than add a per-rule deferral to each, the override routes such cases to S26
    once. It is safe because (post-v22) S26 only fires on an engaged X-0 column
    with a wrong digit, and the width bound rejects overflow/concat (5-0='50' ->
    S03, not S26). Example: 12-1='1' -> S05 (looks like an operand copy), but
    12-1='01' -> S26 (the leading 0 shows the kid annihilated the engaged tens).
    See _derive_cascade_primary for the full predicate and worked examples.

Two related SCOPE decisions (not deferrals, but previously flagged by reviewers):
  - S26 is engagement-gated (v22): it never infers identity failure from a
    column the kid did not write. 5-0='0' -> S26 (units engaged, real diff);
    100-0='0' -> S09. See the S26 docstring.
  - S23 Tier-1 is deliberately LEFT loose: it fires on the zero-top signature
    column even when another column is an unrelated slip (50-28='98' -> S23,
    with S30 surfacing as the ranked secondary). KEPT intentionally — the
    zero-top concept is the priority diagnosis here and the secondary preserves
    the "there is also a slip" reading. Tightening Tier-1 to require the full
    mechanism was considered and DECLINED; revisit only if precision on partial
    matches is preferred over concept-first.
================================================================================

Cumulative changes over v19:
(Note: worked examples in the dated entries below reflect the behaviour of the
version being described, NOT necessarily current behaviour — e.g. several
100-0='0' -> S26 and 5-0='4' -> S29 examples were superseded by later versions
and now resolve differently (S09, S26 respectively). For current behaviour trust
the rule docstrings and the DEFERRAL & PRECEDENCE RATIONALE above.)

  v19.1 — S12 Tier 4: cross-operand digit transposition.
  v19.2 — S15 deferrals (later superseded).
  v19.3 — S15 Tier 2 removed; teen-1d cases route to S16.
  v19.4 — S06 deferral to S23 made conditional.
  v19.5 — S10 sub-A coincidence guard.
  v19.6 — S10 sub-B coincidence guard.
  v19.7 — S10 restricted to n_digits(n1) ≤ 2.
  v19.8 — S18 Tier 5: partial chain reduction at zero pass-throughs.
  v19.9 — S16 Tier 3: long-documented but never-coded teen-1d catch.
  v19.10 — S20 Tier 2: borrow-writes-zero at chain pass-through columns.
  v19.11 — S20 global deferral to S23 when cw_abs(n1, n2) == wi.
  v19.12 — S20 wi != 0 guard (kid gave up entirely → not S20).
  v19.13 — S20 Option B: non-borrow cols must match {d1-d2, correct}.
  v19.14 — S20 length guard: n_digits(wi) >= n_digits(correct).
  v19.15 — S15 / S16 split for "drop units" pattern:
    - S15 restricted to NO borrow at units. The "systematically drops
      units" misconception only applies when the kid wasn't forced to
      borrow there.
    - S16 Tier 5 added: borrow-skip pattern. When borrow is needed at
      units AND kid wrote only the higher-order subtraction (wi shorter
      than correct, wi == |n1//10 - n2//10|), the kid avoided the borrow
      by skipping the column. Cognitively cleaner: S15 = "habit drops
      units", S16 (borrow-skip) = "avoided the borrow column."
      Cases: 64-16=5, 91-76=2, 30-12=2, 75-29=5, etc.
  v19.16 — Code hygiene pass; NO behavioral change to cascade picks.
    - S20: deleted ~40 lines of dead code after `return True` (lines
      965-1004 in v19.15). Exact copy of pre-Option-B body left behind
      when v19.13 added the early return; unreachable per AST.
    - S18: docstring phantom Tier 2 removed. Code has Tier 1/3/4/5
      only; docstring previously listed a Tier 2 that was never
      implemented.
    - S24: in-line analytical commentary about the spec's 91-76=85
      example not fitting the stated detection condition moved from
      function body to docstring as a [KNOWN SPEC DIVERGENCE] note.
      Conservative implementation choice (a) unchanged.
    - S25: explanations.json example replaced. Old example
      (618-17=601, wrote 611) was structurally impossible because
      618-17 requires zero borrows; classifier correctly tagged that
      case as S27. New example (40-31=9, wrote 39) actually fires S25.
    - S03/S04/S05/S06/S11: `wi == correct` guards added at the top.
      These rules previously returned True on the correct answer when
      called directly; classify()'s fast path masked it but guards
      are cheap and now consistent with S10/S14/S18/S22/S24/S25/S26/S27.
    - Audit also noted but DID NOT FIX: the S06↔S23 deferral over-fires
      on X0−Y geometry (e.g., 10-3=13 → S23, 90-6=96 → S23). After
      review, this is a defensible diagnostic choice — the conditional
      prior in the wi=n1+n2 ∧ S23-mechanism-matches subspace points
      to S23 per corpus annotators, and the 0-x=x bug is the canonical
      zero-top error (BUGGY / VanLehn). Current v19.15 behavior
      retained as v19.16 behavior.
  v19.17 — S28 restricted to 2-digit correct only.
    - S28's cognitive story ("kid wrote a single digit equal to the
      difference of two digits of correct") is most defensible when
      correct has exactly one digit pair, so the match is unambiguous.
      For correct ≥ 3 digits the rule had multiple candidate pair-diffs
      and fired loosely. Empirical audit: 1,233 rows / 12,657 freq of
      3+ digit correct cases were single-rule S28 fires (no other rule
      co-firing), most of which represented coincidental matches rather
      than diagnostic signal.
    - Corpus impact: 1,233 rows / 12,657 freq move from S28 → S31
      (UNCLASSIFIED). Pure restriction; no other rule transitions.
    - Decision rationale: accepted honest withholding over loose
      diagnosis for the 3+ digit regime, where the cognitive story
      doesn't hold up under scrutiny. Same-digit 2-digit cases
      (correct=11, 22, ...) are retained — only 9 rows / 813 freq, and
      degenerate |d-d|=0 may still represent a genuine cognitive event
      (kid noticed repeated digit somewhere).
  v19.18 — Bug fixes from external review (no design changes).
    - Fix 1: guard against n1 < n2 at API entry. Previously the cascade's
      full-rule sweep called _rule_S28, which called
      pairwise_digit_diffs(correct); for correct < 0, digits(correct)
      crashed on '-' in str(correct). Now returns S31 with debug error
      message. Corpus impact: 0 (no n1<n2 rows in corpus); robustness.
    - Fix 2: S23 over-wide guard. Previously str(wi).zfill(width)[-width:]
      silently truncated leading digits of over-wide responses, causing
      cases like 80-6='9999996' to match S23 because the trailing 2
      digits happened to fit the zero-top-copies-subtrahend pattern. S26
      had this guard; S23 mirrors it now. Corpus impact: 1,543 rows /
      3,314 freq lose their (incorrect) S23 tag.
    - Fix 5: parse_response now strips commas (in utils_v14.py), matching
      parse_operand. Previously '1,234' parsed as None (S01), while
      '2,000' as an operand parsed as 2000. Corpus impact: ~256 rows
      with comma characters in raw response.
  v19.19 — S26 tightened via cognitive-consistency principle.
    - v19.18's S26 had two cognitive-story failures:
      (i) The `if n2 == 0: return True` short-circuit fired S26 on ANY
          wrong answer when n2=0, including 5-0='4' (kid wrote 4, not
          0 — clearly understands X-0≠0) and 59-0='9' (kid wrote units
          only — didn't apply X-0=0 anywhere).
      (ii) The per-column branch fired when diffs occurred at N2-zero
           columns but didn't require the kid actually wrote 0 there.
    - Cognitive consistency principle: if a kid truly has the X-0=0
      misconception, they apply it AT EVERY X-0 column they encounter.
      Concretely: (a) at any X-0 col where they wrote a non-zero digit,
      they don't have the misconception; (b) at any col they didn't
      engage with (wrote shorter answer), we cannot infer X-0=0 from
      absence; (c) the kid's intentional 0 at a N2-zero column IS
      evidence of the misconception.
    - v19.19 detection (two branches):
      * canonical: n2==0 AND wi==0. Kid wrote 0 for X-0 problem;
        size of n1 doesn't matter (one-digit '0' is consistent with
        applying X-0=0 at every column of any-width problem).
      * per-column: n_digits(wi) == max(n_digits(n1), n_digits(n2))
        AND at every diff col: n2_digit=0 AND wi_digit=0.
    - Key case decisions:
      * 5-0='0' → S26 (canonical, preserved)
      * 5-0='4' → S29 (kid wrote 4, not 0 → not X-0=0)
      * 59-0='9' → S09 (kid wrote units only, didn't engage tens)
      * 59-0='50' → S26 (kid wrote 0 at units = column-level X-0=0)
      * 100-0='0' → S26 (canonical, multi-digit problem)
      * 445-404='1' → S09 (shorter than operands; didn't engage)
      * 53-20='30' → S26 (per-column at units)
      * 100-50='0' → not S26 (n2 isn't 0; kid likely gave up)
    - Corpus impact: 3,726 rows / 24,781 freq change. All transitions
      from S26 (no spurious new S26 fires). ~67% (16,736 freq) get more
      specific diagnoses (S29/S30/S15/S09/S03/S13/S10/S28/S14); ~33%
      (8,045 freq) move to S31 (honest unclassified).
  v19.20 — S26 reframed and renamed: X_MINUS_ZERO_IDENTITY_FAILURE.
    - Pedagogical reframing: the rule now captures the broader cognitive
      gap "kid didn't recognize X-0 as an identity," not the narrower
      misconception "kid thinks X-0=0." Two cognitive subcases share
      the same competency gap and the same remediation (drill X-0=X):
      * Annihilation: kid wrote 0 at an X-0 column (the v19.19 case).
      * Computation attempt: kid wrote a non-correct, non-zero digit
        at an X-0 column (counted back wrong, slipped, etc.). Treated
        as identity failure under v19.20.
    - Implementation change: removed the `if wi_uf[k] != '0': return
      False` check from v19.19's per-column branch. Cognitive consistency
      engagement check preserved (n_digits(wi) == width). Canonical case
      (n2==0 AND wi==0) preserved.
    - Key case decisions (* = changed from v19.19):
      * 5-0='4'    → S26* (was S29): wrote 4, tried to count back
      * 59-0='58'  → S26* (was S29): wrote 8 at units (X-0 col)
      * 53-20='32' → S26* (was S29): wrote 2 at units (X-0 col)
      * 100-0='400'→ S26* (was S31): wrote 4 at hundreds (X-0 col)
      * 59-0='9'   → S09 (unchanged: kid engaged units correctly, didn't
                          engage tens; cognitive consistency preserved)
      * 5-0='0'    → S26 (unchanged: canonical)
      * 59-0='50'  → S26 (unchanged: per-col at units)
    - Corpus impact: 1,014 rows / 8,565 freq newly become S26 from
      S29 (425/6,112), S30 (581/2,407), S10 (8/46). S26 total grows
      from 71 rows / 14,972 freq (v19.19) → 1,085 rows / 23,537 freq.
    - Trade-off: loses some cognitive specificity (kids who slip on
      an X-0 col are now lumped with kids who annihilate) but gains
      unified remediation (the action is "teach the X-0 identity"
      regardless of how it failed).
  v19.21 — S16 Tier 3 tightened with units-derivability constraint.
    - Tier 3's previous detection was loose: it fired on any wi where
      n_digits(wi) == n_digits(correct)+1 AND tens(wi) == tens(n1)-tens(n2)
      AND units(wi) != correct's units. No constraint on units(wi).
    - Symptom: cases like 11-2='14' (units=4 has no derivation from
      operand digits {1, 2, |1-2|=1}) were diagnosed as
      BORROW_FORGOTTEN_BIGGER_MINUS_SMALLER, even though the kid didn't
      do bigger-minus-smaller at units AND units=4 has no clean cognitive
      story.
    - Fix: require units(wi) ∈ {units(n1), units(n2), |units(n1)−units(n2)|}.
      The three values correspond to "kid kept n1's units," "kid kept
      n2's units," and "kid did bigger-minus-smaller at units."
    - Corpus impact: 1,249 rows / 15,199 freq move from S16 → S31.
      Pure transition (single class). S16 count drops from 2,939 to
      1,690 rows. The 15,199 freq affected cases have no coherent
      cognitive story for the units digit and are now honestly
      unclassified.
    - Cases preserved (Tier 3 units IS derivable):
      * 17-9='12': units=2 = |7-9|=2 ✓
      * 18-9='11': units=1 = |8-9|=1 ✓
      * 14-7='12': units=2 ≠ {4, 7, 3} → no longer Tier 3 → S31
    - Cases moved to S31:
      * 11-2='14': units=4 ∉ {1, 2, 1}
      * 15-6='12': units=2 ∉ {5, 6, 1}
      * 15-6='14': units=4 ∉ {5, 6, 1}
      * 17-9='11': units=1 ∉ {7, 9, 2}
      * 17-9='16': units=6 ∉ {7, 9, 2}
      * 18-9='17': units=7 ∉ {8, 9, 1}
  v19.22 — Hygiene + cognitive-consistency fixes from external review.
    Three substantive changes plus four pure-cleanup items.

    SUBSTANTIVE:
    - S26 canonical case generalized: was `n2 == 0 AND wi == 0`. Now:
      `wi == 0 AND every non-zero digit of correct sits at an X-0
      column`. Restores S26 routing for 1,597 freq of cases (e.g.
      51-50='0', 145-140='0') that v19.19's engagement check had
      silently moved to S15. Cognitive story: kid's '0' is consistent
      with applying X-0 identity failure at X-0 cols PLUS correct math
      at non-X-0 cols that coincidentally give 0. (Reviewer claim #3.)
    - S27 extended with whole-problem Tier 2: `n1 == n2 AND wi == n1`.
      Catches cases like 10-10='10', 22-22='22', 100-100='100' that
      previously fell to S31. Same X-X=X misconception at the whole-
      number level rather than column level. (Reviewer claim #6.)
    - S15's S16 deferral comment updated to reflect v19.15's
      borrow-at-units guard reaching before S16 Tier 4/5 can fire;
      the deferral now effectively handles only S16 Tier 1-3 cases.
      (Reviewer claim #5.)

    CLEANUP (no behavior change):
    - utils.n1_effective_digits_after_borrow docstring example fixed:
      `(618, 17) -> [8, 1, 6]` (no borrows for 618-17), not the stale
      `[18, 0, 6]`. (Reviewer claim #1.)
    - _rule_S09 dead S26 deferral removed; docstring rewritten to
      reflect that 445-404='1' now correctly fires S09 (cognitive
      consistency: kid didn't engage tens/hundreds → units-only).
      (Reviewer claim #2.)
    - _rule_S14 Tier 1 dead S26 deferral removed (incompatible widths
      between S14 Tier 1 and post-v19.20 S26 made it unreachable).
      (Reviewer claim #4.)
    - _rule_S14 Tier 1 redundant `n_digits(wi) < n_digits(correct)`
      removed (already guaranteed by enclosing `==-1` condition).
      (Reviewer claim #7.)

    Corpus impact (net): 1,597 freq S15 → S26 (claim #3 fix); plus
    a small number of cases newly catching S27 Tier 2 (claim #6).
  v19.23 — Performance + dead-code hygiene from final review pass.
    Six small fixes. Zero behavioral changes; all corpus tags identical
    to v19.22. The classifier was already correct; v19.23 cleans up.

    SUBSTANTIVE (performance):
    - classify() now walks the cascade ONCE instead of twice. Previously
      _cascade_first_match() did a cascade walk to compute cascade_primary,
      then classify() did a second walk to build the matched list. With
      inter-rule deferrals, individual rules were hit 2-5× per call
      (e.g., S23 was evaluated 5x for 100-50='150'). v19.23 builds the
      matched list once and derives cascade_primary from it via the new
      _derive_cascade_primary() helper. Predicate call counts cut by
      roughly half for most cases.
    - _cascade_first_match() deleted (replaced by _derive_cascade_primary).
      The dead `if code in ("S14", "S22"): pass` branch inside it also
      goes away as a side effect.

    DOCSTRING FIXES (no behavior change):
    - utils.n1_minus_n2_left_aligned: docstring claimed "Returns None if
      negative result" but the function unconditionally returns the int.
      Docstring corrected to match actual behavior (caller is responsible
      for context-appropriate handling of negative results).
    - _rule_S17: docstring formula `(tens(N1) - tens(N2)) * 10 + units(N2)`
      misrepresented the implementation, which uses `(N1//10) - (N2//10)`
      (integer division of the upper part) — coincides with tens() for
      2-digit operands but diverges for 3+ digit (e.g., 100-99='19' fires
      S17 via 10-9=1 → 1*10+9=19, not via literal tens digits 0 and 9).
      Docstring updated.

    DEAD CODE REMOVED:
    - n1_minus_n2_left_aligned import in subtraction.py — never called
      (S12 inlines the equivalent math).
    - `k < len(w_msb)` check inside `_rule_S23`'s `for k in range(width)`
      loop — tautological after v19.18's over-wide guard.
  v19.24 — Multi-zero raw responses route to S26.
    Cognitive-consistency fix for responses like '00', '000', etc. —
    kid wrote multiple zeros, indicating engagement at multiple columns.

    BACKGROUND:
    Pre-v19.24, all-zeros responses like 66-60='00' fired S01
    (RANDOM_OR_INVALID) because '00' has ≥2 zero chars. Other cases like
    111-101='000' fired S09 (UNITS_ONLY_SUBTRACTION) because the parsed
    value (0) matches correct%10, OR S14 (LEADING_DIGIT_DROPPED) because
    n_digits(wi)=1=n_digits(correct)-1. But the kid wrote N zeros — they
    engaged with N columns, which contradicts all three diagnoses:
      - "Random" (S01) — but the response has clear structure
      - "Units-only" (S09) — but kid wrote multiple chars
      - "Dropped leading digit" (S14) — but kid wrote N digits, not N-1

    The asymmetry was visible in '0' vs '00': 51-50='0' fired S26
    (v19.22 generalized canonical), but 51-50='00' fired S01. Same
    parsed value, same cognitive error, different diagnosis.

    THE FIX (three coordinated changes):

    1) _rule_S01: deferral added — when raw has ≥2 zero chars and no
       other digit AND _rule_S26 fires, return False. (Semantic: this
       isn't random input — there's a coherent X-0 cognitive story.)

    2) _rule_S09: deferral added — same pattern. (Semantic: kid wrote
       multiple chars, so this isn't "units-only".)

    3) _derive_cascade_primary: cascade special-case added — when raw
       is multi-zero AND S26 is in matched, return S26 regardless of
       cascade position. This is the structural fix that covers any
       OTHER rule that might fire for these cases (S14, future rules).

    The per-rule deferrals (1) and (2) give cleaner per-rule data —
    those rules don't fire when their cognitive stories don't fit. The
    cascade special-case (3) ensures the final classification is
    correct regardless of which other rules fire structurally.

    SAFETY:
    The cascade special-case requires S26 to be in matched (S26 must
    INDEPENDENTLY fit). All guards:
      - raw.isdigit() (must be pure digits)
      - zero_count >= 2 (must have multiple zeros)
      - nonzero_count == 0 (no other digit)
      - "S26" in matched (S26 must already fire)

    Cases verified to STAY S01 (no change):
      - 'XYZ' (non-numeric, wi=None)
      - 'nan' (non-numeric)
      - 88-11='00' (no X-0 col, S26 doesn't fit)
      - 76-67='00' (borrow required, S26 doesn't fit)
      - 200-100='000' (hundreds not X-0)

    Cases verified to STAY S09 (no change):
      - 445-404='1' (single digit, not multi-zero raw)
      - 59-0='9' (single non-zero digit)

    CORPUS IMPACT: 173 rows / 3,794 freq move to S26 (all from S01 or
    indirectly via S09/S14). Top cases now routed to S26:
      66-60='00' (818), 17-10='00' (283), 77-70='00' (252),
      145-140='000' (224), 51-50='00' (206), 38-30='00' (177),
      288-280='000' (167), 111-101='000' (163), 621-601='000' (118),
      344-304='000' (106).
  v19.25 — S26 refined: engagement-aware X-0 identity failure.
    Reframes S26 around the cognitive principle that AT AN X-0 COLUMN
    THERE IS NOTHING TO COMPUTE. The answer is X by identity; there's
    no fact to misremember and no procedure to slip on. Any wrong digit
    at an engaged X-0 column is necessarily identity failure (S26) — it
    cannot be arithmetic slip (S29), because slip presupposes a
    computation to slip on.

    BACKGROUND — what changed since v19.24:
    Pre-v19.25, the asymmetry between '0' (S09) and '00' (S26 since
    v19.24) was partially fixed, but a similar asymmetry remained
    between cases like '1' and '001'. The v19.24 cascade special-case
    handled all-zeros raw, but didn't handle non-zero parsed wi with
    leading-zero raw. Earlier v19.25 iterations tried Option-B (cascade
    special-case for leading-zero raw); this version replaces that with
    a more principled design.

    Critical case (user's question — 17-10='6'):
      - Pre-v19.25:   S29 (single-column slip)
      - Refined v19.25: S26
    Cognitively, units in 17-10 is 7-0=7 by identity. Kid wrote 6. No
    slip available — there's no fact "7-0=6" to misremember; the col
    is just identity recognition. Wrong digit = identity failure.

    THE REFINED RULE:
    S26 fires when, examining every column the kid demonstrably
    engaged with (k < engagement_len):
      - Any diff col must be an X-0 col (else S26 disqualified; some
        other rule should fire — kid is doing wrong arithmetic, not
        identity failure)
      - At least one engaged X-0 col must have a wrong digit
        (identity failure actually happened)

    ENGAGEMENT:
      - Prefer raw response length (when digit-only) over parsed-wi
        digit count, because leading zeros indicate the kid actually
        wrote at those cols (e.g., '06' vs '6': both parse to wi=6
        but '06' shows engagement at 2 cols).
      - Capped at problem width.
      - Beyond-n2-width cols are implicit X-0 (e.g., for 888-5, tens
        and hundreds are X-0 because n2=5 contributes nothing there).

    ASYMMETRIC HANDLING OF KEY CASES:
      59-0='9' → S09 (units X-0, kid wrote 9=9-0 — identity CORRECT)
      59-0='5' → S26 (units X-0, kid wrote 5 — identity failure)
      445-404='1'   → S09 (engaged units only, units NOT X-0, units correct)
      445-404='001' → S26 (engaged tens X-0 with wrong digit 0)
      888-5='3'   → S09 (engaged units only, units NOT X-0)
      888-5='003' → S26 (engaged tens & hundreds X-0 with wrong digit 0)
      17-10='6'   → S26 (engaged units X-0 with wrong digit 6)
      17-10='06'  → S26 (same, with explicit tens engagement)
      96-6='80'   → S26 (engaged tens X-0 implicit, wrote 8 instead of 9)
      96-6='96'   → S05 (operand copy preserved; units diff is at non-X-0)

    COORDINATED CHANGES:
    1) _rule_S26: replaced per-column branch with engagement-aware
       design above. Canonical (wi==0) branch retained for cases
       like 100-0='0' where the response is shorter than width.
    2) _rule_S09: generalized v19.24 narrow "multi-zero raw" deferral
       to v2-style general S26 deferral (`if _rule_S26(s): return
       False`). Under refined v19.25 S26 firing selectively (only when
       engaged X-0 col has wrong digit), the general deferral is safe
       and routes leading-zero cases (445-404='001', 19-4='05') to
       S26. Single-digit cases (445-404='1', 59-0='9') unaffected
       because refined S26 doesn't fire for them.
    3) _rule_S14: restored v2-style S26 deferral on Tier 1 (`if
       _rule_S26(s): return False`). The v19.22 dead-code removal had
       removed it; under refined v19.25 S26 firing for leading-zero
       cases (445-404='001'), the deferral is alive again and routes
       these correctly to S26.
    4) _rule_S15: deferral narrowed to wi==0 AND _rule_S26(s). The
       original v19.2 deferral intent per docstring was annihilation
       cases (145-140='0', 51-50='0'); under refined S26 firing more
       broadly, the unnarrowed deferral was disqualifying S15 for
       cases like 60-10='5' (legitimate units-digit-dropped case).
    5) _rule_S05: excludes wi==0. When kid writes 0 for X-0 (so
       wi == n2 == 0), the diagnosis is annihilation (S26), not
       operand copy. Without this exclusion, cases like 5-0='0' and
       100-0='0' route to S05 by cascade position.
    6) _derive_cascade_primary: retained ONE special-case (the
       leading-zero raw override) and REMOVED the v19.24 n2==0
       early-fire. The leading-zero override routes to S26 when raw
       has leading zeros indicating engagement at cols the parsed wi
       doesn't naturally fill, AND the parsed wi fits within the
       problem width (excluding concat overflow like 5-0='50'), AND
       refined S26 fires. This systematically catches cases where
       many rules (S14 Tier 1, S16 Tier 4, S16 Tier 5, S22 Tier 1,
       S17, S23, etc.) fire structurally based on parsed wi with
       cognitive stories assuming a shorter raw response — for
       leading-zero raw, those stories don't fit, and S26 (kid did
       identity failure at engaged X-0 col) is the right diagnosis.
       Cleaner than adding per-rule deferrals to every affected rule.
       The v19.24 n2==0 early-fire was over-aggressive (routed 5-0='50'
       to S26 over S03 concat) and is NOT restored.

    Note: _rule_S01's mashed-zeros deferral (v19.24) is UNCHANGED.
    It continues to defer to S26 for all-zeros raw when S26 fits;
    the set of cases differs slightly because refined S26 fires for
    slightly different cases.

    CORPUS IMPACT: ~8,270 rows / ~45,800 freq move.
    Top transitions:
      S31 → S26 (6,314 rows / 25,236 freq): unclassified → specific
        X-0 identity failure diagnosis
      S29 → S26 (1,229 rows / 14,760 freq): slip at X-0 col reframed
        as identity failure (no slip possible at X-0)
      S30 → S26 (475 rows / 1,411 freq): multi-col slip cases where
        all diff cols are X-0
      S09 → S26 (46 rows / 1,399 freq): leading-zero engagement
        cases (445-404='001', 19-4='05', etc.)
      S01 → S26 (92 rows / 1,227 freq): mashed-zeros + canonical fit
      S20 → S26 (46 rows / 961 freq): borrow cases at X-0 implicit
      S28 → S26 (14 rows / 341 freq)
      S14 → S26 (36 rows / 246 freq)
    Reverse direction (cases LOSING S26):
      S26 → S10 (8 rows / 46 freq): cases like 59-0='99' now route
        to S10 (N1_UNITS_DIGIT_AS_TENS) as a more specific diagnosis;
        v19.24's n2==0 special-case had been over-routing to S26.

    CRITICAL CASES PRESERVED:
      96-6='96' → S05 (operand copy)
      13-3='13' → S05 (operand copy)
      41-1='42' → S06 (wrong op)
      11-2='14' → S31 (unclassified — diff at non-X-0 disqualifies S26)
      60-10='5' → S15 (units-digit-dropped — preserved via narrow S15 deferral)
      5-0='50' → S03 (concat — preserved via cascade SC removal)
      88-11='00' → S01 (no X-0 col)
      76-67='00' → S01 (borrow required)
      200-100='000' → S01 (hundreds not X-0)
  v19.26 — S27 Tier 3: column-level X-X identity failure with extra digits.
    Adds Tier 3 to _rule_S27 as the SIBLING of refined v19.25 S26. Both
    diagnose column-level identity-rule failures:
      X − 0 = X (identity)  →  kid writes wrong → S26 (X-0 failure)
      X − X = 0 (identity)  →  kid writes wrong → S27 Tier 3 (X-X failure)

    Critical cases (the user's question):
      17-17='10' → was S31, now S27 Tier 3
      17-13='14' → was S31, now S27 Tier 3
    For 17-13='14': units 7-3=4 ✓; tens 1-1 should be 0 but kid wrote 1
    (= n1's tens digit). The cognitive story is "kid saw 1-1, didn't
    apply X-X=0, wrote the matching digit". Mirror of refined S26.

    THE RULE:
    Tier 3 fires when n1 != n2 AND, examining every column within
    engagement (engagement_len = min(len(raw), width)):
      - Any diff col must be a "clean X-X failure col":
          * n1_d == n2_d (column-level X-X), AND
          * n1_d != 0 (non-zero — distinguishes from X-0 cases), AND
          * kid wrote n1_d at this col, AND
          * no borrow involves this col (would alter pre-borrow X-X)
      - At least one such X-X failure col exists.

    BORROW EXCLUSION:
    The check "no borrow involves this col" requires:
      - borrows[k] == False (col k doesn't itself need to borrow)
      - borrows[k-1] == False (col k is not a lender for col k-1)
    Examples this correctly disqualifies (kid's wrong digit is borrow-
    related coincidence, not X-X failure):
      584-88='486' (tens looks X-X but tens borrows)
      255-156='059' (tens borrows in a chain)

    COORDINATED CHANGES (v19.26):
    Only ONE change: _rule_S27 gains Tier 3. No other rule modified.
    S27's cascade position (24) is between S26 (23) and S28 (25), so
    Tier 3 wins over slip rules (S28, S29, S30) but loses to operand-
    copy (S05), concat (S03), wrong-op (S06), and borrow rules (S16-S23).
    This is correct: more-specific cognitive diagnoses win, but otherwise
    X-X failure is preferred over generic slip.

    CORPUS IMPACT: ~99 rows / ~1,426 freq move S31 → S27, plus a few
    minor reroutes from S17, S29 where the X-X interpretation is cleaner.
    Top affected cases:
      445-404='441' (507 freq): hundreds X-X failed
      621-601='620' (170 freq): hundreds X-X failed
      344-304='340' (115 freq): hundreds X-X failed
      288-280='208' (82 freq): hundreds X-X failed

    PRESERVED:
      96-6='96' → S05 (operand copy wins over Tier 3 at cascade 24)
      13-3='13' → S05 (same)
      17-17='17' → S27 Tier 2 (whole-problem)
      30-30='30' → S27 Tier 2
      584-88='486' → S29 (borrow check disqualifies Tier 3)
      11-2='14' → S31 (no X-X col)
  v19.27 — S02 deferral: tighten Tier 2 against coincidental matches.
    S02 (INPUT_ORDERING_ERROR) Tier 2 fires when raw's digit-multiset
    matches padded correct's. This is a real cognitive story for true
    transpositions (38-6='23', 43-23='02'). But Tier 2 also catches
    structural coincidences where the kid's actual misconception is
    unambiguous and better-diagnosed by another rule. Since S02 sits
    at cascade position 2, it preempts S05 (operand copy, pos 5) and
    S06 (addition, pos 6) when both fire.

    THE CHANGE: At the top of _rule_S02, defer when
        wi ∈ {n1, n2, n1+n2}
    These three conditions identify the cases where a cleaner rule
    fires AND should win:

      - wi == n2 → kid wrote n2 entirely (S05 operand copy).
        Examples: 66-60='60' (754 freq), 77-70='70' (327), 77-7='07' (264).
      - wi == n1 → kid wrote n1 entirely (S05 operand copy).
        Example: 10-9='10' (90 freq).
      - wi == n1+n2 → kid added instead of subtracting (S06).
        Examples: 11-9='20' (402 freq), 55-36='91' (32), 455-9='464' (26).

    Each is a specific, diagnosable misconception. S02's
    "digit-permutation of correct" is a coincidence when wi already
    matches one of these — there's no real "ordering" story to tell.

    CORPUS IMPACT: ~1,992 freq move S02 → {S05, S06}.

    PRESERVED (real transpositions, unaffected):
      38-6='23' (correct=32; freq 409)
      43-23='02' (correct=20; freq 386)
      67-33='43' (correct=34; freq 374)
      19-4='51' (correct=15; freq 367)
    These have wi != n1, != n2, != n1+n2, so the deferral doesn't fire
    and S02 still correctly tags them.
  v19.28 — S26 borrow-independence: fire only at borrow-independent X-0 cols.
    Tightens S26 to fully align with v19.25's principle. v19.25's
    foundation was: "at an X-0 col there is NOTHING to compute, so any
    wrong digit = identity failure (no slip possible)". But when borrow
    involves the X-0 col, there IS computation (subtract 1 for lending
    or take borrow from above). The X-0 SHAPE is preserved but the X-0
    IDENTITY (no computation) is broken.

    THE CHANGE: Add a borrow check inside S26's per-column loop, after
    the X-0 check. For each diff X-0 col k, require:
        borrows[k] == False
        AND (k == 0 OR borrows[k-1] == False)
    If any diff X-0 col is borrow-involved (borrows itself or lends to
    col k-1), S26 disqualified.

    This is the SYMMETRIC SIBLING of v19.26's S27 Tier 3 borrow check:
        S26 (X-0 identity):  fires only at borrow-independent X-0 cols
        S27 T3 (X-X identity): fires only at borrow-independent X-X cols
    Same principle, same check, perfectly symmetric. Both rules now
    cleanly separate from borrow-rule territory (S16-S23).

    COGNITIVE PRINCIPLE: column-level identity-rule failures
    (X-0=X for S26, X-X=0 for S27 Tier 3) fire ONLY at columns where
    the identity actually holds (no borrow involvement). When borrow
    breaks the identity, the kid's wrong digit gets diagnosed by other
    rules (S16-S23 for borrow misconceptions, S29 for slip, S31 for
    unclear).

    CORPUS IMPACT: ~13,924 freq move S26 → {S17, S18, S19, S20, S22,
    S23, S29, S30, S31} per cascade routing. Breakdown by what kid
    wrote at the borrow-involved X-0 col (from prior audit):
      Annihilation cases (kid wrote 0; ~2,442 freq): route to borrow
        rules where they fire (S22 for "borrow units only dropped"),
        else S29 or S31.
      No-reduce cases (kid wrote n1's pre-borrow digit; ~628 freq):
        route to S17/S18 where they fire, else S31.
      Slip cases (kid wrote ±1 from post-borrow truth; ~1,357 freq):
        route to S29.
      Other (~9,000+ freq): mostly S31 (honest withholding).

    The volume going to S31 reflects that many "borrow-with-wrong-
    digit-at-X-0" cases don't have a clean specific cognitive story;
    being honest about that is better than mis-tagging them S26.

    PRESERVED: ~59,880 freq of canonical pure-X-0-non-borrow identity
    failures unchanged. Examples:
      17-10='6'    → S26 (units X-0, no borrow)
      17-10='06'   → S26 (same, explicit tens engagement)
      180-68='012' → S26 (no borrow)
      100-0='0'    → S26 (canonical)
      888-5='003'  → S26 (over-width tens/hundreds X-0)
      96-6='80'    → S26 (tens X-0, no borrow at tens)
      53-20='32'   → S26 (units X-0, no borrow)
    All v19.26/v19.27 cases also unchanged.
  v19.29 — Split S20 into S20 + S21: separate trigger-col from interior-zero.
    Legacy S20 (BORROW_WRITES_ZERO) had two tiers — Tier 1 (kid wrote 0
    at a borrow trigger col) and Tier 2 (kid wrote 0 at a chain
    pass-through col). v19.28's analysis revealed these are cognitively
    DISTINCT misconceptions:

      S20 (trigger col, original): kid recognized borrow needed but
        "cancelled" the col rather than completing the exchange. The
        column was attempted but mishandled.
      S21 (interior zero, new): kid mentally JUMPED the borrow over an
        interior zero directly to the lender. The interior column was
        BYPASSED, not addressed. The 0 in the response is the original
        n1 digit unchanged, not a digit the kid chose.

    Surface signature is identical (zero at borrow-related col); cognitive
    story is different; remediation differs:
      S20 remediation: "borrow = exchange, not cancel"
      S21 remediation: "interior zero gets a haircut from 10 — it
        becomes 9, not stays 0"

    THE CHANGE:
      - Renamed legacy S20 to fire ONLY for Tier 1 (trigger col).
      - Created new S21 BORROW_SKIPS_INTERIOR_ZERO, extracting Tier 2.
      - Inserted S21 in cascade between S20 and S22 (sibling concept;
        wins over S22-S31 but loses to more-specific S16-S20).
      - All other internals (length guard, wi != 0 guard, Option B,
        global cw_abs deferral, internal S23/S24/S26 deferrals) were
        INITIALLY preserved in both rules unchanged. NOTE: v25 later
        replaced S21's Option B and global cw_abs deferral with a strict
        column-match (S20 retains both); v26 added S21's raw-digit guard
        and made S09/S05 defer to S21. See the v25/v26 changelog and the
        _rule_S21 docstring for current S21 behavior.

    Examples now correctly tagged S21:
      601-8='503'   (correct=593): interior tens left at 0
      408-109='209' (correct=299): same
      8102-6='8006' (correct=8096): same
      200-9='101'   (correct=191): same
      303-204='009' (correct=99): same

    Examples that stay S20 (trigger col cases):
      21-9='10'  (correct=12): units trigger col wrote 0
      32-3='10' (similar trigger pattern)

    CORPUS IMPACT: ~3,480 freq (about 8% of v19.28's S20) move S20 → S21.
    No other rules affected. This is a relabeling — same diagnoses, just
    split into two rule codes for pedagogical precision.

    SYSTEM CHANGES: This is the first non-Tier change since v19.25 that
    changes the rule INVENTORY. The codes range is now S01–S31.
      - _FREQ_TABLE updated (S20 prior reduced, S21 added) [renumbered v19.31: was "S31 added" pre-renumber]
      - SUBTRACTION_ERROR_NAMES gains "S21": "BORROW_SKIPS_INTERIOR_ZERO" [v19.31: at slot S21; was added as "S31" in v19.29 before the v19.31 renumber]
      - SUBTRACTION_CASCADE_ORDER becomes an explicit list (was a
        range comprehension) with S21 inserted after S20.
      - _PREDICATES gains "S21": _rule_S21
      - explanations.json gains an S21 entry (detection/example/remedial)

API
---
    classify(n1, n2, learner_response, learner_grade=None,
             *, return_debug=False) -> ClassifyResult

Returns ClassifyResult with:
    - cascade_code: the spec-defined cascade output (top of the ranked list)
    - cascade_name: human-readable error name for cascade_code (e.g.
                    "BORROW_NO_REDUCE"); empty string for "CORRECT"
    - ranked: list of (code, name, score) triples for ALL rules that fired,
              ranked by score (descending). Top entry is always cascade_code.
    - debug: optional dict with computed signals.

Score formula (same as Addition)
--------------------------------
    raw_score = specificity × prior × priority_weight
    Specificity = 1 / (number of rules that also fired)
    Prior       = rule's historical frequency
    Priority    = 1 / sqrt(cascade_position)
    Scores normalized to sum to 1.0.

S31 (UNCLASSIFIED_ERROR) appears in the ranked output only when no other rule fires.
"""

__version__ = "29"

from dataclasses import dataclass, field
from typing import Optional, Callable

from utils import (
    parse_response, parse_operand, normalize_raw,
    digits, n_digits, concat_int, is_digit_permutation_strs,
    right_align_digits,
    reverse_int, units, tens,
    subtract_columnwise_abs,
    borrow_columns, units_borrow_required, any_borrow_required,
    lender_column_for_borrow, n1_effective_digits_after_borrow,
    pairwise_digit_diffs,
    digit_position_mismatches,
)

# ---------------------------------------------------------------------------
# Spec-derived priors (from subtraction_error_rules_v19.docx, Table 0)
# Computed as Freq / total_freq (total = 1,633,157 per spec)
# ---------------------------------------------------------------------------

_TOTAL_FREQ = 1_501_040
_FREQ_TABLE = {
    "S01": 24_695,
    "S02": 19_834,
    "S03": 6_528,
    "S04": 703,
    "S05": 93_563,
    "S06": 105_601,
    "S07": 1_309,
    "S08": 3_380,
    "S09": 23_599,
    "S10": 3_744,
    "S11": 11_177,
    "S12": 9_070,
    "S13": 9_283,
    "S14": 1_525,
    "S15": 4_370,
    "S16": 61_263,
    "S17": 12_756,
    "S18": 49_746,
    "S19": 5_680,
    "S20": 39_848,
    "S21": 1_425,
    "S22": 568,
    "S23": 37_170,
    "S24": 4_758,
    "S25": 2_099,
    "S26": 50_486,
    "S27": 13_978,
    "S28": 6_901,
    "S29": 243_488,
    "S30": 222_219,
    "S31": 430_274,
}
# Priors above reflect actual observed frequencies in the v26 tagged corpus
 # (Subtraction_tagged_Combined_S28.xlsx: 169,737 rows; 1,501,040 error-tag freq,
# 290 CORRECT freq excluded). RESYNCED v19.29 -> v24 (2026-05-30): 16 of 29
# per-code frequencies re-derived after v26 re-tagged 23 full-width
# borrow-skips to S21 (+293 freq: 20 from S09, 2 from S05, 1 from S31). _TOTAL_FREQ is unchanged: total
# response volume is fixed, only per-code assignment changed. These priors
# feed ONLY the `ranked` likelihood output; the cascade code used for corpus
# tagging is unaffected by priors.
SUBTRACTION_PRIORS_ALL: dict[str, float] = {
    code: freq / _TOTAL_FREQ for code, freq in _FREQ_TABLE.items()
}

# ---------------------------------------------------------------------------
# Spec-derived error names (from subtraction_error_rules_v19.docx, Table 0)
# ---------------------------------------------------------------------------

SUBTRACTION_ERROR_NAMES: dict[str, str] = {
    "S01": "RANDOM_OR_INVALID",
    "S02": "INPUT_ORDERING_ERROR",
    "S03": "CONCAT_FORWARD",
    "S04": "CONCAT_REVERSE",
    "S05": "N1_OR_N2_COPIED_AS_ANSWER",
    "S06": "WRONG_OPERATION_ADDITION",
    "S07": "WRONG_OPERATION_MULTIPLICATION",
    "S08": "WRONG_OPERATION_DIVISION",
    "S09": "UNITS_ONLY_SUBTRACTION",
    "S10": "N1_UNITS_DIGIT_AS_TENS",
    "S11": "DOUBLE_SUBTRACTION",
    "S12": "PLACE_VALUE_POSITIONING",
    "S13": "OPERAND_DIGIT_REVERSAL",
    "S14": "LEADING_DIGIT_DROPPED",
    "S15": "UNITS_DIGIT_DROPPED",
    "S16": "BORROW_FORGOTTEN_BIGGER_MINUS_SMALLER",
    "S17": "BORROW_NON_ZERO_SMALLER_TOP_COPIES_N2_DIGIT",
    "S18": "BORROW_NO_REDUCE",
    "S19": "BORROW_ADDS_10_TO_BOTH_COLUMNS",
    "S20": "BORROW_WRITES_ZERO",
    "S21": "BORROW_SKIPS_INTERIOR_ZERO",
    "S22": "BORROW_INDUCED_ZERO_OMITTED",
    "S23": "BORROW_ZERO_TOP_COPIES_N2_DIGIT",
    "S24": "BORROW_ZERO_TOP_NO_REDUCE",
    "S25": "BORROW_N2_DIGIT_IGNORED",
    "S26": "X_MINUS_ZERO_IDENTITY_FAILURE",
    "S27": "X_MINUS_X_EQUALS_X",
    "S28": "CORRECT_ANSWER_DIGITS_SUBTRACTED",
    "S29": "SINGLE_COLUMN_SLIP",
    "S30": "MULTI_COLUMN_SLIP",
    "S31": "UNCLASSIFIED_ERROR",
}

SUBTRACTION_SHORT_LABELS: dict[str, str] = {
    # Friendly paraphrases shown in the HTML ranked-matches list.
    # Single source of truth: edit here, rebuild_html.py regenerates the
    # HTML labels dict from this on every build.
    "S01": 'Random / invalid input',
    "S02": 'Digit reorder',
    "S03": 'Concatenation (forward)',
    "S04": 'Concatenation (reverse)',
    "S05": 'Operand copied as answer',
    "S06": 'Wrong-op: addition',
    "S07": 'Wrong-op: multiplication',
    "S08": 'Wrong-op: division',
    "S09": 'Units-only subtraction',
    "S10": 'N1 units used as tens',
    "S11": 'Double subtraction',
    "S12": 'Place-value positioning',
    "S13": 'Operand digit reversal',
    "S14": 'Leading digit dropped',
    "S15": 'Units digit dropped',
    "S16": 'Borrow forgotten (bigger-minus-smaller)',
    "S17": 'Non-zero smaller top: copies N2 digit',
    "S18": 'Borrow without reduce',
    "S19": 'Borrow adds +10 to both columns',
    "S20": 'Borrow writes zero (trigger col)',
    "S21": 'Borrow skips interior zero (chain pass-through)',
    "S22": 'Borrow-induced zero in answer omitted',
    "S23": 'Zero-top copies N2 digit',
    "S24": 'Borrow at zero-top: wrong units AND unreduced',
    "S25": 'N2 next-column ignored after borrow',
    "S26": 'x minus 0 = 0 (rule confusion)',
    "S27": 'x minus x = x (rule confusion)',
    "S28": 'Correct answer digits subtracted',
    "S29": 'Single column slip',
    "S30": 'Multi-column slip',
    "S31": 'Unclassified',
}

# ---------------------------------------------------------------------------
# Cascade priority order (spec section 4).
# v19.29: S21 BORROW_SKIPS_INTERIOR_ZERO inserted right after S20 — sibling
# concept that wins over the rules below S20 (S22-S31) but loses to the
# more-specific borrow rules S16-S19 and to S20 itself (the trigger-col
# story is more specific when both could fire).
# ---------------------------------------------------------------------------

SUBTRACTION_CASCADE_ORDER: list[str] = [
    "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19", "S20", "S21", "S22", "S23", "S24", "S25", "S26", "S27", "S28", "S29", "S30", "S31",
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
                      A code like "S18", "CORRECT", or "S31" (fallback).
        cascade_name: Human-readable error name for cascade_code (e.g.
                      "BORROW_NO_REDUCE"). Empty string for "CORRECT".
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
# ---------------------------------------------------------------------------

def _rule_S01(s: dict) -> bool:
    """
    S01 RANDOM_OR_INVALID
    Detection: raw is non-numeric / negative / mashed zeros (≥2 zeros, no other digit)
    Classification:
      IF raw_string contains ≥2 zero characters AND no other digit character → S01
      Also IF int(raw) < 0 → S01
      Also fires for unparseable input (the parsed wi will be None).

    v19.24 — mashed-zeros path defers to S26 when S26 also fires.
    Background: pre-v19.24, all-zeros responses like 66-60='00' fired
    S01 (RANDOM_OR_INVALID) because '00' has ≥2 zero chars. But many of
    these responses are systematic, not random — the kid wrote N zeros
    consistent with applying X-0=0 at every X-0 column AND correct math
    at non-X-0 columns (where correct happens to be 0). This is exactly
    the v19.22 generalized S26 canonical case applied to multi-char input.
    Without the deferral, 51-50='0' (S26) and 51-50='00' (S01) got
    inconsistent diagnoses despite reflecting the same cognitive error.

    The deferral is narrow: only triggers when S26 ALREADY independently
    fits the case. Cases like 88-11='00' (no X-0 column, S26 doesn't fit)
    or 76-67='00' (borrow required, S26 doesn't fit) continue firing S01.
    """
    if s["wi"] is None:
        return True
    raw = s["raw"]
    if raw is not None and raw.isdigit():
        zero_count = raw.count("0")
        nonzero_count = sum(1 for c in raw if c.isdigit() and c != "0")
        if zero_count >= 2 and nonzero_count == 0:
            # v19.24: defer to S26 if the all-zeros response fits the
            # X-0 identity-failure cognitive story.
            if _rule_S26(s):
                return False
            return True
    return False

def _rule_S02(s: dict) -> bool:
    """
    S02 INPUT_ORDERING_ERROR
    Detection: digit-set match with correct (raw is ground truth, leading zeros preserved).
    Tier 1: sorted(digits(w)) == sorted(digits(correct)), same digit-count.
    Tier 2 (padded): L=max(len(N1),len(N2)); padded_correct=correct.zfill(L);
                     sorted(raw_digits)==sorted(padded_correct).
    Tier 3 (any-raw override): post-process S14/S22 to S02 — handled at cascade level
                               since this only re-tags AFTER another tier; treated
                               here as: if raw matches Tier 2's padded condition.

    v19.27 — DEFERRAL added at top: when wi ∈ {n1, n2, n1+n2}, defer to
    other rules. S02's cascade position (2) preempts S05 (5) and S06 (6),
    so without this deferral, Tier 2's digit-multiset coincidence would
    misclassify cases with much cleaner cognitive stories:

      - wi == n2 → kid wrote n2 entirely (S05 operand copy is more
        diagnosable than "digits happen to permute correct's digits").
        Examples: 66-60='60' (754 freq), 77-70='70' (327 freq),
        77-7='07' (264 freq).

      - wi == n1 → kid wrote n1 entirely (S05 operand copy). Example:
        10-9='10' (90 freq).

      - wi == n1+n2 → kid added instead of subtracting (S06). Examples:
        11-9='20' (402 freq), 55-36='91' (32 freq), 455-9='464' (26 freq).

    These are coincidental digit-multiset matches where the kid's actual
    misconception is unambiguous. Deferral routes them to the
    pedagogically clearer rule.

    Corpus impact: ~1,992 freq move S02 → {S05, S06}.

    Real transposition cases unaffected — kid wrote digits of correct in
    wrong order, with wi != n1, != n2, != n1+n2. Examples preserved:
      38-6='23' (correct=32; freq 409)
      43-23='02' (correct=20; freq 386)
      67-33='43' (correct=34; freq 374)
      19-4='51' (correct=15; freq 367)
    """
    if s["wi"] is None or s["wi"] == s["correct"]:
        return False
    # v19.27: defer when wi matches a clearly-cleaner cognitive story.
    # S05 (operand copy) and S06 (addition) are more diagnosable than
    # S02's digit-multiset coincidence; they sit at cascade positions 5
    # and 6 vs S02 at 2, so without this deferral S02 incorrectly
    # preempts them.
    if s["wi"] in (s["n1"], s["n2"], s["n1"] + s["n2"]):
        return False
    correct_str = str(s["correct"])
    # Tier 1: digit-permutation
    if is_digit_permutation_strs(str(s["wi"]), correct_str):
        return True
    # Tier 2: padded (raw vs operand-width-padded correct)
    if s["raw"] is not None and s["raw"].isdigit():
        L = max(n_digits(s["n1"]), n_digits(s["n2"]))
        padded = correct_str.zfill(L)
        if is_digit_permutation_strs(s["raw"], padded):
            return True
    return False

def _rule_S03(s: dict) -> bool:
    """S03 CONCAT_FORWARD: w == int(str(N1) + str(N2))."""
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    return s["wi"] == concat_int(s["n1"], s["n2"])

def _rule_S04(s: dict) -> bool:
    """S04 CONCAT_REVERSE: w == int(str(N2) + str(N1))."""
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    return s["wi"] == concat_int(s["n2"], s["n1"])

def _rule_S05(s: dict) -> bool:
    """
    S05 N1_OR_N2_COPIED_AS_ANSWER: N1 ≠ N2 AND w ∈ {N1, N2}.
    (renamed in v19.29; was PARTIAL_OPERAND_COPY — "PARTIAL" was
    misleading: the kid copies a whole operand, not part of one.)

    v19.25: excludes wi==0. When kid writes 0 for X-0 (so wi == n2 == 0),
    the cognitive story is annihilation/identity failure (X-0=0), not
    operand copy. The "copy" framing is degenerate for the zero operand
    — writing 0 isn't reproducing n2 as an answer in the same sense as
    writing n1 or a non-zero n2. Without this exclusion, S05 would fire
    for cases like 5-0='0' and 100-0='0' (writing 0 reads as copying the
    zero operand n2). The wi==0 exclusion lets these resolve to their
    identity-failure / engagement reading instead: 5-0='0' → S26, and (as of
    v22) 100-0='0' → S09. The complementary case (wi == n1
    AND n1 == 0) is structurally impossible given n1 ≥ n2 ≥ 0 and the
    pre-existing n1 == n2 exclusion.

    v26: also defers to S21 BORROW_SKIPS_INTERIOR_ZERO — when wi == n2
    coincides with a full-width borrow-skip (e.g. 1006-8='0008', wi=8=n2),
    the borrow-skip diagnosis is more specific than operand-copy.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    if s["n1"] == s["n2"]: return False
    if s["wi"] == 0: return False
    if _rule_S21(s): return False  # v26: borrow-skip is more specific than operand-copy
    return s["wi"] == s["n1"] or s["wi"] == s["n2"]

def _rule_S06(s: dict) -> bool:
    """
    S06 WRONG_OPERATION_ADDITION: w == N1 + N2.

    Deferral: defers to S23 (BORROW_ZERO_TOP_COPIES_N2_DIGIT) only when S23's
    full mechanism (apply 0−x=x at every zero-top column, normal
    subtraction with borrow at others) reproduces wi exactly.
    v19.4: previously defer was unconditional (whenever _rule_S23 fired),
    which over-fired on cases like 50-28=78, 4100-1368=5468, 703-74=777
    where the kid clearly added but a zero-top column coincidentally
    matched (because n1 + n2 forces 0 + d2 = d2 at any zero-top col).
    Audit: 269 sheet-S06 cases (106,092 freq) of wi==n1+n2 have
    S23-mechanism != wi; 43 sheet-S23 cases (23,005 freq) have
    S23-mechanism == wi. The discriminator is clean.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    if s["wi"] != s["n1"] + s["n2"]: return False
    # JUDGMENT CALL (prevalence): when both "added" and "zero-top copy" explain
    # wi, default to S23. Full rationale: see "DEFERRAL & PRECEDENCE RATIONALE"
    # (group B) at the top of this file.
    if _rule_S23(s):
        if _e20_mechanism_explains_wi(s):
            return False
    return True

def _e20_mechanism_explains_wi(s: dict) -> bool:
    """Helper for S06's deferral and S23 Tier 1's full-mechanism gate (v23).
    Return True iff S23's per-column
    interpretation (write n2_digit at zero-top cols, do normal
    subtraction with borrow at other cols) reproduces wi exactly.

    This separates two cases of wi == n1 + n2:
    - 90-6=96: at units (zero-top), 0-6=6; at tens, 9-0=9. sim=96=wi.
      → S23 mechanism explains it. (Coincidence with addition.)
    - 50-28=78: at units (zero-top), 0-8=8; at tens, with borrow
      4-2=2. sim=38, wi=78. → S23 doesn't explain it; kid added.
    """
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)
    eff = list(d1)
    # Propagate borrows from non-zero-top cols (units-first).
    # S23 cols don't trigger borrows (kid does 0-x=x there).
    for k in range(width - 1, -1, -1):
        if d1[k] == 0 and d2[k] > 0:
            continue  # S23 col — no borrow
        if eff[k] < d2[k]:
            j = k - 1
            while j >= 0 and eff[j] == 0:
                eff[j] = 9
                j -= 1
            if j >= 0:
                eff[j] -= 1
            eff[k] += 10
    # Produce simulated answer
    sim_digits = []
    for k in range(width):
        if d1[k] == 0 and d2[k] > 0:
            sim_digits.append(d2[k])
        else:
            sim_digits.append(eff[k] - d2[k])
    sim = int("".join(str(d) for d in sim_digits)) if sim_digits else 0
    return sim == wi

def _rule_S07(s: dict) -> bool:
    """
    S07 WRONG_OPERATION_MULTIPLICATION: w == N1 * N2 (added v28).
    Guards: N1 > 1 AND N2 > 1 AND wi != N1 AND wi != N2 AND wi != correct.
    Sits just below S06 (added-instead), so the 2-2='4' coincidence
    (2x2 == 2+2) resolves to S06. Mirrors addition A04.
    """
    if s["wi"] is None:
        return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if n1 <= 1 or n2 <= 1:
        return False
    if wi == n1 or wi == n2:
        return False
    if wi == correct:
        return False
    return wi == n1 * n2

def _rule_S08(s: dict) -> bool:
    """
    S08 WRONG_OPERATION_DIVISION: w == N1 // N2, exact division only (added v28).
    Guards: big=max(N1,N2), small=min(N1,N2); big % small == 0 AND
    wi == big // small AND wi > 1 AND N1 > 1 AND N2 > 1 AND N1 != N2 AND
    wi != N1 AND wi != N2 AND wi != correct. Tightly guarded because small
    quotients collide with the slip band; mirrors addition A05.

    v28 routing note (confirmed): for "halving" answers such as 16-8='2'
    and 36-18='2', where BOTH this rule (16/8=2) and BORROW_FORGOTTEN
    (|6-8|=2 with the tens dropped) reconstruct the answer, S08 wins —
    operation confusion is the more fundamental error and S08 sits above
    the borrow codes by design. Do NOT demote S08 below the borrow tier to
    "fix" these. The borrow reading is not lost: applicable_codes() still
    flags it (e.g. 16-8='2' -> S08, S16, S29); only the single Final code
    is divide. ~638 freq corpus-wide, ~565 of it the single item 16-8='2'.
    """
    if s["wi"] is None:
        return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if n1 <= 1 or n2 <= 1:
        return False
    if n1 == n2:
        return False
    if wi <= 1:
        return False
    if wi == n1 or wi == n2:
        return False
    if wi == correct:
        return False
    big, small = max(n1, n2), min(n1, n2)
    if big % small != 0:
        return False
    return wi == big // small

def _rule_S09(s: dict) -> bool:
    """
    S09 UNITS_ONLY_SUBTRACTION
    (v19.34: expanded to cover both borrow and no-borrow units cases,
     subsuming the former S22 BORROW_UNITS_ONLY_DROPPED rule)

    Cognitive story: the kid believes the answer is just the units digit.
    They computed the units column (with or without borrow, depending on
    the problem) and wrote that single digit as the final answer. The
    tens/hundreds/etc. columns were never written.

    Detection: a single predicate works regardless of whether borrow was
    needed because correct%10 gives the units digit of the correct answer
    in BOTH cases:
      n_digits(wi) == 1                # kid wrote one digit
      n_digits(correct) >= 2           # correct answer has more digits
      wi == correct % 10               # what kid wrote IS the units digit

    What this rule does NOT prove:
      Whether the kid borrowed correctly (in problems that required it).
      Whether they reduced the lender column. We never see a tens digit.
      So this rule cannot distinguish "correct full borrow then truncated"
      from "additive borrow without lender reduction" from "no borrow
      needed, kid just truncated."

    The problem-level distinction (units borrow required vs not) is
    preserved as a Units_Borrow_Required column in the corpus xlsx
    starting v19.34, so analyses can still slice by borrow context
    without spending a separate rule code on it.

    Examples:
      19 − 4 = 15, kid wrote '5'  (no borrow needed, U(15)=5)
      67 − 9 = 58, kid wrote '8'  (borrow needed at units, U(58)=8)
      43 − 17 = 26, kid wrote '6' (borrow at units, U(26)=6)

    Deferral: defers to S26 X_MINUS_ZERO_IDENTITY_FAILURE (renumbered
    from old S27 in v19.34). When the kid wrote the units digit and that
    happens to be 0 for an X-0 column problem, S26's per-column 0-rule
    is the more specific diagnosis.

    Also defers to S21 BORROW_SKIPS_INTERIOR_ZERO (v26): when the answer
    is a full-width borrow-skip (the units digit shown alongside a
    skipped interior zero), the borrow-skip diagnosis is more specific
    than "units only".
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    if n_digits(s["wi"]) != 1:
        return False
    if n_digits(s["correct"]) < 2:
        return False
    if s["wi"] != s["correct"] % 10:
        return False
    # Defer to S26 X_MINUS_ZERO_IDENTITY_FAILURE (was S27 pre-v19.34)
    if _rule_S26(s):
        return False
    # v26: defer to S21 BORROW_SKIPS_INTERIOR_ZERO — a full-width borrow-skip is
    # more specific than "units only".
    if _rule_S21(s):
        return False
    return True

def _rule_S10(s: dict) -> bool:
    """
    S10 N1_UNITS_DIGIT_AS_TENS
    Restricted to 2-digit n1 (v19.7 — see below).

    Sub-type A: len(n1)≤2, len(w)==len(correct)≥2, w%10==correct%10,
                (w//10)%10==N1%10, tens(w)≠tens(correct),
                AND |tens(N2) - tens(N1)| ≠ N1%10  (v19.5 guard).
    Sub-type B: len(n1)≤2, len(w)==len(correct)+1, len(correct)==1,
                w%10==correct%10, (w//10)%10==N1%10,
                AND |tens(N2) - tens(N1)| ≠ N1%10  (v19.6 guard).

    v19.7 — restricted to n_digits(n1) ≤ 2.
    The S10 misconception is fundamentally a 2-digit phenomenon: a
    learner confused about column alignment writes n1's units digit
    in the tens position of the result. For 3+ digit n1 problems,
    sheet-tagged "S10" cases consistently turn out to be other
    mechanisms on close inspection:
      317-131=176 → single-column slip at tens (correct 186, off by 1)
      935-167=758 → slip at tens (correct 768, off by 1)
      567-78=479  → slip at tens (correct 489, off by 1)
      703-74=639  → borrow-no-reduce at tens (correct + 10 = 639)
      412-220=222 → smaller-minus-bigger at tens
    The sheet over-tagged these as S10 because the wi happened to have
    units(n1) at the tens position by coincidence, but the cognitive
    process is something else entirely.
    Audit: -25 rows / -841 freq corpus agreement (Option C: corpus
    over-tagged 3-digit cases as S10). The lost cases mostly fire
    S29 SINGLE_COLUMN_SLIP after the restriction, which is at least
    pedagogically honest.
    Cumulative cost so far: 11,971 (v19.1+v19.3) + 841 (v19.7) =
    12,812 freq of deliberate corpus override.

    Deferral: defers to S19 when S19 (BORROW_ADDS_10_TO_BOTH_COLUMNS) also matches.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    # v19.7: S10 only applies to 2-digit n1
    if n_digits(n1) > 2: return False
    matched = False
    coincidence = abs(tens(n2) - tens(n1)) == n1 % 10
    # Sub-type A
    if n_digits(wi) == n_digits(correct) >= 2:
        if (wi % 10 == correct % 10
                and tens(wi) == n1 % 10
                and tens(wi) != tens(correct)
                and not coincidence):
            matched = True
    # Sub-type B
    if n_digits(wi) == n_digits(correct) + 1 and n_digits(correct) == 1:
        if wi % 10 == correct % 10:
            if (wi // 10) % 10 == n1 % 10 and not coincidence:
                matched = True
    if not matched:
        return False
    # S19 deferral
    if _rule_S19(s):
        return False
    return True

def _rule_S11(s: dict) -> bool:
    """S11 DOUBLE_SUBTRACTION: w == correct − N2."""
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    return s["wi"] == s["correct"] - s["n2"]

def _rule_S12(s: dict) -> bool:
    """
    S12 PLACE_VALUE_POSITIONING
    Tier 1: w == N1 − (N2 × 10^(L−len(N2))) where L=max(len(N1),len(N2))
    Tier 3: w == N1 − (rev(N2) × 10^(L−len(rev(N2))))
    Tier 4 (v19.1): cross-operand column-grouping for 2-digit operands.
        new_minuend = tens(N1)·10 + tens(N2)         (both tens digits)
        new_subtrahend = units(N1)·10 + units(N2)    (both units digits)
        w == new_minuend - new_subtrahend
        e.g., 91-76=81 via 97-16, 84-65=41 via 86-45, 63-21=31 via 62-31.

    Note on Tier 2: the spec lists Tier 2 as "(units_as_tens — absorbed)", meaning
    the units-as-tens pattern is owned by S10 (N1_UNITS_DIGIT_AS_TENS), not S12.
    This implementation does NOT implement Tier 2 — those cases fall through to S10.

    Note on Tier 4 / corpus disagreement: the v19 tagged corpus consistently
    labels the cross-operand-transposition pattern as S13
    (OPERAND_DIGIT_REVERSAL) — 37/38 matching rows / 2,139 freq. Per project
    decision (Option C), this implementation treats S12 as the more accurate
    label since the misconception is structurally about confused place-value
    grouping across operands, not within-operand digit reversal. The
    classifier therefore disagrees with the corpus on these ~2,500 freq.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    # Tier 1
    L = max(n_digits(n1), n_digits(n2))
    shift = L - n_digits(n2)
    if shift > 0:
        candidate = n1 - n2 * (10 ** shift)
        if candidate >= 0 and wi == candidate:
            return True
    # Tier 3: rev(N2) left-aligned
    rn2 = reverse_int(n2)
    shift_r = L - n_digits(rn2)
    if shift_r > 0:
        candidate = n1 - rn2 * (10 ** shift_r)
        if candidate >= 0 and wi == candidate:
            return True
    # Tier 4 (v19.1): cross-operand digit transposition (2-digit operands)
    if 10 <= n1 <= 99 and 10 <= n2 <= 99:
        new_n1 = (n1 // 10) * 10 + (n2 // 10)
        new_n2 = (n1 % 10) * 10 + (n2 % 10)
        if new_n1 >= new_n2 and wi == new_n1 - new_n2:
            return True
    return False

def _rule_S13(s: dict) -> bool:
    """
    S13 OPERAND_DIGIT_REVERSAL
    Tier 1: rev(N1) − N2 == w
    Tier 2: N1 − rev(N2) == w
    Tier 3: rev(N1) − rev(N2) == w

    Deferral: defers to S15 (UNITS_DIGIT_DROPPED) when S15 also fires.
    The Tier 3 (rev-both) condition can coincidentally produce the same result
    as |tens(N1) - tens(N2)| for problems where both operands have similar
    digit structure (e.g., 93-23=7: rev(93)-rev(23)=39-32=7 = |9-2|=7).
    The spec's S15 worked example "93-23=70 → w=7" is the canonical case.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    rn1 = reverse_int(n1)
    rn2 = reverse_int(n2)
    matched = False
    if rn1 != n1 and rn1 - n2 == wi and rn1 >= n2:
        matched = True
    if rn2 != n2 and n1 - rn2 == wi and n1 >= rn2:
        matched = True
    if (rn1 != n1 or rn2 != n2) and rn1 - rn2 == wi and rn1 >= rn2:
        matched = True
    if not matched:
        return False
    # S15 deferral
    if _rule_S15(s):
        return False
    return True

def _rule_S14(s: dict) -> bool:
    """
    S14 LEADING_DIGIT_DROPPED
    Tier 1: len(w)==len(correct)-1 AND correct % (10^(len(correct)-1)) == w
    Tier 2: all non-zero digits of correct appear in w in order; the skipped
            digit is a zero NOT caused by borrowing AND no raw variant shows
            all correct digits.

    Deferrals:
    - Tier 1 defers to S22 Tier 1 (units-only-with-borrow drop) — when units
      borrow is required and w == 10+U(N1)-U(N2), the spec's S22 example
      (67-9=58 → w=8) takes that interpretation despite also matching S14 Tier 1.
    - Tier 1 defers to S26 (v19.25 — v2-style restoration). When the kid
      engaged at multiple cols (e.g., raw='001') and the engaged X-0 cols
      have wrong digits, refined S26 fires. Cognitively, the kid did NOT
      drop the leading digit — they wrote at that col explicitly (the
      leading 0 in raw shows it). The X-0 identity failure diagnosis is
      more accurate. Examples (S14 fires structurally, refined S26 also
      fires, S14 defers): 445-404='001', 19-4='05', 111-101='000'.
      Single-digit responses like 445-404='1' (where refined S26 does
      NOT fire because no engaged X-0 col is wrong) stay as S14... but
      actually fall to S09 by cascade position (position 7 < 12).
    - Tier 2 defers to S22 Tier 2 (borrow-induced interior zero skip) — handled
      by the borrow-induced-zero check below.
    """
    if s["wi"] is None: return False
    n1, n2 = s["n1"], s["n2"]
    correct = s["correct"]
    wi = s["wi"]
    if wi == correct: return False
    # Tier 1: dropped MSB
    if n_digits(wi) == n_digits(correct) - 1:
        if correct % (10 ** (n_digits(correct) - 1)) == wi:
            # S22 Tier 1 deferral: when units borrow is required and w fits the
            # units-only-with-borrow pattern, defer to S22.
            # (v19.22: dropped redundant `n_digits(wi) < n_digits(correct)` —
            # already guaranteed by the enclosing `n_digits(wi) == n_digits(correct) - 1`.)
            if (units_borrow_required(n1, n2)
                    and wi == 10 + units(n1) - units(n2)):
                return False
            # v2-style restoration: S26 deferral. When per-column 0-rule
            # pattern also fits (e.g., 445-404='1' — kid dropped leading 4
            # which coincides with applying 4-0=0 misconception at tens),
            # defer to S26. Restored because v19.X removed engagement check.
            if _rule_S26(s):
                return False
            return True
    # Tier 2: INTERIOR zero in correct that is NOT borrow-induced
    # ("interior" means not the last position of correct — trailing zeros are
    # "units only" patterns, not interior-zero drops)
    cs = str(correct)
    ws = str(wi)
    if len(ws) < len(cs):
        # Walk wi as sub-sequence of correct, find skipped positions
        i = j = 0
        skipped_positions = []
        while i < len(cs) and j < len(ws):
            if cs[i] == ws[j]:
                i += 1
                j += 1
            else:
                skipped_positions.append(i)
                i += 1
        while i < len(cs):
            skipped_positions.append(i)
            i += 1
        # Interior-only check: no skipped position can be at the last index of cs
        # (trailing zero) or the first index (leading zero — that's Tier 1's domain)
        if (j == len(ws) and skipped_positions
                and all(cs[p] == "0" for p in skipped_positions)
                and all(0 < p < len(cs) - 1 for p in skipped_positions)):
            # Each skipped zero must NOT be borrow-induced.
            # A zero at column k in correct is "borrow-induced" iff column k
            # acted as a LENDER (was reduced because column to its right borrowed).
            borrows = borrow_columns(s["n1"], s["n2"])
            width_correct = len(cs)
            for p in skipped_positions:
                col_uf = width_correct - 1 - p   # column index, units=0
                # Was this column a lender?
                is_lender = False
                for borrow_col, borrowed in enumerate(borrows):
                    if borrowed:
                        lender = lender_column_for_borrow(s["n1"], s["n2"], borrow_col)
                        if lender == col_uf:
                            is_lender = True
                            break
                if is_lender:
                    return False  # borrow-induced; defer to S22 Tier 2
            return True
    return False

def _rule_S15(s: dict) -> bool:
    """
    S15 UNITS_DIGIT_DROPPED
    (Renamed from TENS_ONLY_SUBTRACTION in v24 — name only; code "S15",
    detection, and tag membership unchanged.) Detects wi == correct // 10:
    the correct answer with its units digit dropped. Under the no-units-
    borrow guard below this equals abs(N1//10 - N2//10), which is what
    Tier 1 tests; the older "tens-only" name was inaccurate for 3+ digit
    operands (the result includes hundreds/thousands, not just tens).
    Tier 1: N2 ≥ 10 AND w == abs((N1 // 10) − (N2 // 10)).
        The "tens" interpretation is "everything except units" — the kid
        effectively drops the units column and subtracts the remaining
        higher-order parts. For 2-digit operands this equals the
        tens-digit difference; for 3+ digit operands it produces a
        multi-digit answer.
        Examples:
          93-23=70 → w=7 (|9-2|=7), 2-digit case
          9175-5205=3970 → w=397 (|917-520|=397), 4-digit case

    Deferrals (v19.2; refined v19.15, v19.22):
    - Tier 1 → S16: when S16 also fires, defer. The v19.2-era audit cited
      Tier 4 (single-digit wi, |units(N1)-units(N2)|) coincidences like
      68-59=1; v19.15's borrow-at-units guard now reaches before Tier 4/5
      can fire (both require borrow at units), so this deferral effectively
      handles only S16 Tier 1-3 co-firings post-v19.15. Still useful — e.g.
      S16 Tier 1 column-wise patterns can coincidentally equal the
      higher-order-only result for certain operand pairs.
    - Tier 1 → S26: when wi == 0 AND S26 also fires (v19.25 narrowing).
      When tens(N1)==tens(N2) AND wi==0, Tier 1's mechanism is a trivial
      coincidence; the kid most likely applied X-0 identity failure at
      units (e.g. 145-140=0, 51-50=0). Cognitively the kid wrote 0
      because (a) X-0=0 at units gives 0, and (b) tens/higher cols
      correctly compute to 0 because operands match there.
      Audit (pre-narrowing history): v19.15 cleared 5 rows / 2,190 freq
      via the original "if _rule_S26(s): return False" version. After
      v19.19's engagement check on S26, deferral became briefly dead.
      v19.22 extended canonical to wi==0-with-structural-fit, restoring
      the deferral's effect for ~1,597 freq.
      v19.25 NARROWING: changed to `wi == 0 AND _rule_S26(s)` to match
      the original docstring intent ("tens(N1)==tens(N2) AND wi==0,
      Tier 1's mechanism is a trivial coincidence"). Without this
      narrowing, refined v19.25 S26 (which fires for cases like
      60-10='5') would steal legitimate units-digit-dropped diagnoses. Cases
      like 60-10='5' (wi=5≠0): deferral inactive → S15 fires. Cases
      like 145-140='00' (wi=0, both written cols engaged): deferral
      active → S26 fires. (v23: a bare '0' here is under-engaged for a
      3-digit problem, so S26's coverage guard blocks it and S15 fires
      instead — 145-140='0' → S15.)

    v19.3 — Tier 2 REMOVED.
    Previously S15 Tier 2 (OPERAND_UNITS_BLEND) caught teen-minus-
    single-digit cases (10≤N1≤19, 1≤N2≤9, wi==(N1//10)*10+|N1%10-N2|).
    Cognitively these are NOT the units-digit-dropped pattern — the kid did
    bigger-minus-smaller at the units column (avoiding the borrow)
    and "carried through" the 1 from the tens place because there
    was nothing to subtract there. That's the S16 BORROW_FORGOTTEN
    misconception. The structure of Tier 2 (wi == columnwise_abs) is
    a special case of S16 Tier 1.
    Audit: all 25 sheet=S15 teen-1d cases (10,044 freq) also fire
    S16 Tier 1 directly. Removing Tier 2 routes them to S16 without
    any falling through. This disagrees with the corpus's S15 tagging
    on those 10,044 freq — accepted as a corpus-correction (Option C
    style: the corpus mis-labelled this family).
    v19.15 — Borrow-at-units guard added. S15 fires only when no borrow
    is needed at units. When borrow IS needed at units and the kid
    drops units, that's borrow-avoidance (the kid is skipping the
    column to avoid the borrow), not "systematically drops units"
    behavior. Those cases route to S16 Tier 5 (borrow-skip) instead.
    Cognitively cleaner remediation:
      - S15: teach the kid that units is part of every answer.
      - S16 (borrow-skip): teach the borrow procedure.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    # Tier 1
    if n2 >= 10:
        # v19.15: when borrow at units is needed, dropping units is
        # borrow-avoidance, not "systematically drops units". S16 Tier 5
        # captures that pattern.
        borrows = borrow_columns(n1, n2)
        if borrows and borrows[0]:
            return False
        tens_diff = abs((n1 // 10) - (n2 // 10))
        if wi == tens_diff:
            # v19.2 deferrals
            if _rule_S16(s): return False
            # v19.25 narrowing: only defer to S26 when wi==0 (the
            # original intent per docstring — "tens(N1)==tens(N2) AND
            # wi==0, Tier 1's mechanism is a trivial coincidence").
            # Under refined v19.25, S26 fires more broadly (including
            # cases like 60-10='5' where kid wrote tens-diff). Without
            # this narrowing, S15 would defer for all such cases,
            # losing the S15 diagnosis. Original intent was just to
            # handle annihilation (145-140='0', 51-50='0').
            if wi == 0 and _rule_S26(s): return False
            return True
    return False

def _rule_S16(s: dict) -> bool:
    """
    S16 BORROW_FORGOTTEN_BIGGER_MINUS_SMALLER
    Borrow required.
    Tier 1: w == column-wise |N1_col − N2_col| for all columns.
    Tier 2: reversed Tier 1.
    Tier 3 (v19.9 introduced; v19.21 tightened):
            len(w) == len(correct) + 1, tens(N1) ≥ tens(N2),
            tens(w) == tens(N1) − tens(N2), units(w) wrong, AND
            v19.21: units(w) ∈ {units(N1), units(N2), |units(N1)−units(N2)|}.
            Internal deferrals to S18, S20 — when a more specific
            borrow-related mechanism fires.
            The cognitive story: kid didn't see that the answer should be
            1 digit, kept tens(N1)−tens(N2) at tens, and did SOMETHING
            cognitively-derivable at units (kept a units digit from an
            operand, or did bigger-minus-smaller at units matching the
            rule name).
            v19.21 tightening rationale: the previous version had no
            constraint on units(w), causing Tier 3 to fire on cases like
            11-2='14' where units=4 has no clean derivation from operand
            digits {1, 2}. Cases without coherent units-story now route
            to S31 (honest unclassified). Corpus impact: 1,249 rows /
            15,199 freq move to S31.
            Examples that still fire:
              17-9='12': units=2=|7-9|=2 ✓
              18-9='11': units=1=|8-9|=1 ✓
              15-6='15': would be S05 (wi=n1) before reaching here
              15-6='16': would be S17 Tier 1 before reaching here
    Tier 4 (borrow avoidance): borrow required AND w==abs(U(N1)−U(N2)) AND len(w)==1.
    Tier 5 (v19.15): borrow-skip pattern. Borrow needed at units AND kid
            dropped units entirely AND wi == |n1//10 - n2//10| AND
            n_digits(wi) < n_digits(correct). The kid avoided the borrow by
            skipping the units column and computing only higher-order
            subtraction. Examples: 64-16=5, 91-76=2, 30-12=2, 75-29=5.
            This was previously misclassified as S15 (UNITS_DIGIT_DROPPED),
            but cognitively the kid is doing borrow-avoidance, not
            systematic units-dropping.

    Deferrals:
    - Defers to S17 (BORROW_FORGOTTEN_SMALLER_MINUS_BIGGER) when S17 also fires.
      (All tiers.)
    - Tiers 1-4 defer to S23 (BORROW_ZERO_TOP_COPIES_N2_DIGIT) when S23 also fires.
      Tier 5 (borrow-skip) does NOT defer to S23 — for cases like 30-12=2
      where both Tier 5 and S23 match coincidentally, the user's principle
      and the corpus prefer the borrow-skip diagnosis (the kid wrote
      higher-order-only (units-dropped) result, not zero-top mechanism).
    """
    if s["wi"] is None: return False
    if not any_borrow_required(s["n1"], s["n2"]):
        return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    matched_t1to4 = False
    matched_t5 = False
    # Tier 1
    cw = subtract_columnwise_abs(n1, n2)
    if wi == cw:
        matched_t1to4 = True
    # Tier 2: reversed Tier 1
    if cw > 0 and wi == reverse_int(cw):
        matched_t1to4 = True
    # Tier 3 (v19.9, tightened v19.21): wi is one digit longer than correct,
    # kid kept tens(N1)−tens(N2), AND units(wi) must be operand-derivable
    if (not matched_t1to4
            and n_digits(wi) == n_digits(s["correct"]) + 1
            and tens(n1) >= tens(n2)
            and tens(wi) == tens(n1) - tens(n2)):
        # v19.21: cognitive-derivability tightening on units(wi).
        # Tier 3's cognitive story is "kid kept tens(N1)−tens(N2) at tens,
        # and did SOMETHING at units." For the diagnosis to be defensible,
        # the units digit must be plausibly operand-derived. We require
        # units(wi) to be one of:
        #   - units(n1)            (kid kept units of n1)
        #   - units(n2)            (kid kept units of n2)
        #   - |units(n1)-units(n2)| (kid did bigger-minus-smaller at units,
        #                            matching the rule name's promise)
        # Cases where units(wi) is unrelated to operands (e.g., 11-2='14',
        # units=4 with operand units 1, 2, |1-2|=1) are honest unclassified
        # — there's no clean cognitive story for where '4' came from.
        u1, u2 = units(n1), units(n2)
        allowed_units = {u1, u2, abs(u1 - u2)}
        if units(wi) in allowed_units:
            # Internal deferrals: more specific borrow-related rules win.
            # v19.29: S21 (BORROW_SKIPS_INTERIOR_ZERO) added — was previously
            # captured by S20 Tier 2, which this deferral originally referenced.
            # Adding S21 here preserves the v19.28 cascade behavior for cases
            # that fit BOTH S16 and the chain-pass-through story.
            if not _rule_S18(s) and not _rule_S20(s) and not _rule_S21(s):
                matched_t1to4 = True
    # Tier 4: borrow avoidance, single-digit answer
    if n_digits(wi) == 1:
        if wi == abs(units(n1) - units(n2)):
            matched_t1to4 = True
    # Tier 5 (v19.15): borrow-skip pattern (checked independently of T1-4
    # because they can co-fire on coincidence cases like 30-12=2 where
    # |0-2| == |3-1| == 2; Tier 5's diagnosis takes priority for S23
    # deferral suppression).
    if n2 >= 10:
        borrows_at_units = borrow_columns(n1, n2)
        if (borrows_at_units and borrows_at_units[0]
                and n_digits(wi) < n_digits(s["correct"])
                and wi == abs((n1 // 10) - (n2 // 10))):
            matched_t5 = True
    if not (matched_t1to4 or matched_t5):
        return False
    # S17 deferral applies to all tiers.
    if _rule_S17(s):
        return False
    # S23 deferral applies only when Tier 5 did NOT fire. Tier 5
    # (borrow-skip) is cognitively distinct from S23 (zero-top) — when
    # both fire (or Tier 4 fires alongside Tier 5), the borrow-skip
    # diagnosis wins.
    #
    # v21: the S23 deferral is ALSO suppressed when there is positive
    # evidence of the more FUNDAMENTAL S16 gap — a NON-zero-top column
    # where a borrow was needed (top < bottom, top != 0) and the kid did
    # bigger-minus-smaller (wrote |top - bottom| instead of borrowing).
    # That column proves the kid doesn't borrow even when the top is
    # non-zero ("doesn't know if/why/how to borrow" = S16), which is more
    # fundamental than the zero-top-specific S23 (0-x=x). When the ONLY
    # borrow sits at a zero-top column (e.g. 90-6='96', 50-28='38',
    # 10-3='13'), there is no such evidence — those stay S23 (the cases
    # where bigger-minus-smaller and zero-top-copy are indistinguishable).
    # This restores the natural cascade order (S16 precedes S23) for the
    # cases that genuinely evidence the borrowing gap, e.g. 601-518='117'.
    _d1, _d2 = right_align_digits(n1, n2)
    _d1u = list(reversed(_d1))
    _d2u = list(reversed(_d2))
    _w = str(wi).zfill(max(len(_d1), n_digits(wi)))
    _wu = list(reversed(_w))
    _nonzero_top_bms = any(
        _d1u[k] < _d2u[k] and _d1u[k] != 0
        and k < len(_wu) and int(_wu[k]) == _d2u[k] - _d1u[k]
        for k in range(len(_d1u))
    )
    # JUDGMENT CALL (fundamental-vs-specific): see "DEFERRAL & PRECEDENCE
    # RATIONALE" (group B) at the top of this file for the full reasoning.
    if not matched_t5 and _rule_S23(s) and not _nonzero_top_bms:
        return False
    return True

def _rule_S17(s: dict) -> bool:
    """
    S17 BORROW_NON_ZERO_SMALLER_TOP_COPIES_N2_DIGIT
    (renamed in v19.29; partition with S23 made explicit in v19.32)

    Cognitive story: at a borrow column where N1's digit is non-zero but
    smaller than N2's, the kid writes N2's digit at that column instead
    of borrowing. Remaining columns are computed as if no borrow was
    needed.

    Detection:
      Tier 1: wi == ((n1 // 10) − (n2 // 10)) × 10 + (n2 % 10)
      Tier 2: wi == reverse_int(Tier 1 candidate)   (kid wrote answer reversed)

    Partition with S23 (v19.32 fix):
      S17 covers N1_digit ∈ {1..9} and < N2_digit at a borrow column.
      S23 covers N1_digit == 0 (zero-top) at a borrow column.
      The zero-top guard below enforces the partition explicitly — any
      column where d1==0 AND d2>0 means S17 returns False, and the row
      flows past S17 in the cascade so S23 can claim it.

      Before v19.32 this partition relied on a `defer if _rule_S23(s)`
      check at the end of S17. That worked for Tier 1 cases where the
      kid's wi matched both S17's formula and S23's column test. But
      Tier 2 (reversed-output) zero-top cases — e.g. 90−6='69' — slipped
      through because reverse_int(96)=69 matched S17's Tier 2 while
      S23's column test (wi_digit==N2_digit) failed since wi=69 has
      digit 9 at the borrow column, not N2's 6. Result: zero-top rows
      tagged S17 with the wrong cognitive story. v19.32 closes this
      leak by guarding at the top of S17 and adding Tier 2 to S23.
    """
    if s["wi"] is None: return False
    if not any_borrow_required(s["n1"], s["n2"]):
        return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False

    # ZERO-TOP GUARD (v19.32): if any column has d1==0 AND d2>0,
    # this is S23's territory. Reject before checking the S17 formula.
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)
    for k in range(width):
        if d1[k] == 0 and d2[k] > 0:
            return False

    # Now safe to apply the S17 formula — guaranteed non-zero top at every
    # borrow column. Tier 1: kid did upper-part minus upper-part and copied
    # N2's units. Tier 2: same, but wrote the result digit-reversed.
    matched = False
    t1 = (n1 // 10) - (n2 // 10)
    if t1 >= 0:
        candidate = t1 * 10 + (n2 % 10)
        if wi == candidate and wi != s["correct"]:
            matched = True
        if wi == reverse_int(candidate) and wi != s["correct"]:
            matched = True
    return matched

def _rule_S18(s: dict) -> bool:
    """
    S18 BORROW_NO_REDUCE
    Tier 1: w == correct + 10^lender_col (units exact).
    Tier 4 (chain): w == correct + sum(10^k for each column k that was REDUCED
                    during borrowing — both terminal lenders and chain pass-throughs).
    Tier 5 (v19.8): partial chain reduction at zero pass-throughs.
                    When borrow propagates through a zero-digit column (a "pass-through"),
                    the kid may fail to reduce some subset of these pass-throughs while
                    still reducing others (and the terminal lender). The bump equals
                    sum(10^m for m in S) for some non-empty subset S of pass-through
                    columns (cols where d1=0 that get traversed during borrow chains).
                    Examples:
                      703-74=639 (correct 629, +10): chain has pass-through {tens=col 1},
                        terminal {hundreds=col 2}. Kid reduced hundreds but not tens.
                        S = {1}, bump = 10. ✓
                      6006-97=6009 (correct 5909, +100): two pass-throughs {1, 2},
                        kid reduced col 1 but not col 2. S = {2}, bump = 100. ✓
                    Audit: +5,016 freq sheet-S18 matches, -78 freq regressions
                    (negligible). Net +4,938 freq vs v19.7.
                    Scope restricted to zero pass-throughs only — does NOT fire on
                    multi-column slips like 2374-896=1588 (no zero pass-through in
                    any chain), which correctly stay as S30.
    Tier 3 (reversed Tier 1): w == rev(correct + 10^lender).
    """
    if s["wi"] is None: return False
    if not any_borrow_required(s["n1"], s["n2"]):
        return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False

    borrows_uf = borrow_columns(n1, n2)
    # Tier 1: single-borrow case — correct + 10^lender for one borrow
    for col, borrowed in enumerate(borrows_uf):
        if not borrowed:
            continue
        lender = lender_column_for_borrow(n1, n2, col)
        if lender is None:
            continue
        candidate = correct + 10 ** lender
        if wi == candidate:
            return True
    # Tier 4 (chain): all reduced columns
    reduced_cols: set[int] = set()
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)
    d1_uf = list(reversed(d1))
    for col, borrowed in enumerate(borrows_uf):
        if not borrowed:
            continue
        j = col + 1
        while j < width:
            reduced_cols.add(j)
            if d1_uf[j] != 0:
                break  # terminal lender
            j += 1
    if reduced_cols:
        chain_bump = sum(10 ** k for k in reduced_cols)
        if wi == correct + chain_bump:
            return True
    # Tier 5 (v19.8): partial chain reduction at zero pass-throughs.
    # Collect zero pass-through cols (in any chain): cols m > borrow_col where d1[m]=0
    # AND m is traversed before reaching a terminal lender.
    pass_through_cols: set[int] = set()
    for col, borrowed in enumerate(borrows_uf):
        if not borrowed:
            continue
        j = col + 1
        while j < width:
            if d1_uf[j] == 0:
                pass_through_cols.add(j)
                j += 1
            else:
                break  # terminal lender — not a pass-through
    if pass_through_cols:
        from itertools import combinations
        pt_sorted = sorted(pass_through_cols)
        for size in range(1, len(pt_sorted) + 1):
            for combo in combinations(pt_sorted, size):
                bump = sum(10 ** m for m in combo)
                if wi == correct + bump:
                    return True
    # Tier 3: reversed Tier 1
    for col, borrowed in enumerate(borrows_uf):
        if not borrowed: continue
        lender = lender_column_for_borrow(n1, n2, col)
        if lender is None: continue
        candidate = correct + 10 ** lender
        if wi == reverse_int(candidate) and reverse_int(candidate) >= 0:
            return True
    return False

def _rule_S19(s: dict) -> bool:
    """S19 BORROW_ADDS_10_TO_BOTH_COLUMNS
    (renamed in v19.29; was BORROW_ADDS_BOTH — old name was ambiguous
    about what was added and to what.)

    Detection: units borrow required AND w == correct + 20.

    Cognitive story: at the units borrow, the kid adds 10 to N1's
    units (correct) AND ALSO adds 10 to N2's units (wrong — N2 is
    never modified during borrowing). Net effect on the answer:
    +10 − (−10) = +20 above correct.
    """
    if s["wi"] is None: return False
    if not units_borrow_required(s["n1"], s["n2"]):
        return False
    return s["wi"] == s["correct"] + 20

def _rule_S20(s: dict) -> bool:
    """
    S20 BORROW_WRITES_ZERO

    The kid wrote 0 at a column that itself needed to borrow (the
    "borrow trigger" column).

    v19.29 NOTE: This rule previously had two tiers — Tier 1 (zero at
    trigger col, kept here) and Tier 2 (zero at chain pass-through col,
    extracted to new S21 BORROW_SKIPS_INTERIOR_ZERO). The cognitive
    stories are distinct:
      - S20 (trigger col): kid recognized borrow was needed but wrote 0
        at the col, treating the borrow as "zeroing out" the col rather
        than as an exchange. Pedagogically: "borrow = exchange, not
        cancel."
      - S21 (chain pass-through): kid bypassed an interior zero col when
        chain-borrowing, leaving the zero untouched. Pedagogically:
        "interior zero gets a haircut from 10 — becomes 9, not stays 0."

    These were lumped together originally because they share the surface
    signature (kid's response has 0 at a borrow-related col). v19.29
    separates them so remediation can target the specific gap.

    Length guard (v19.14): n_digits(wi) >= n_digits(correct). If the kid
                            wrote fewer digits than the correct answer,
                            they abandoned/collapsed the answer — the
                            leading zeros in padded wi are representation
                            artifacts, not digits the kid produced.
    wi != 0 guard (v19.12): when wi == 0, the kid wrote 0 for the entire
                            answer (gave up), not the S20 mechanism.
    Option B (v19.13): at all TRULY NON-BORROW cols (not a trigger col
                       AND not a chain pass-through col), wi's digit
                       must be in {d1[col] - d2[col] (kid didn't lend),
                       correct's padded digit (kid did lend)}.
    Global cw_abs deferral (v19.11): defers to S23 when S23 fires AND
                                     cw_abs(n1, n2) == wi (kid did
                                     uniform column-wise abs).
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    # v19.12: wi == 0 is "kid gave up", not S20 mechanism.
    if wi == 0:
        return False
    # v19.14: kid's answer must be at least as wide as correct's answer.
    if n_digits(wi) < n_digits(s["correct"]):
        return False
    borrows_uf = borrow_columns(n1, n2)
    if not any(borrows_uf):
        return False
    width = max(n_digits(n1), n_digits(n2))
    w_padded = str(wi).zfill(max(width, n_digits(wi)))
    w_uf = list(reversed(w_padded))
    # v19.29: S20 fires ONLY for the original Tier 1 condition — zero at a
    # borrow trigger column. The pass-through case is now in S21.
    tier1_fires = False
    for col, borrowed in enumerate(borrows_uf):
        if borrowed and col < len(w_uf):
            if w_uf[col] == "0":
                tier1_fires = True
                break
    if not tier1_fires:
        return False
    # Compute chain pass-throughs (still needed for Option B's
    # "truly non-borrow col" check — we don't penalize pass-through
    # cols in Option B because they have their own valid pattern).
    d1, d2 = right_align_digits(n1, n2)
    d1_uf = list(reversed(d1))
    d2_uf = list(reversed(d2))
    pass_through: set[int] = set()
    for col, borrowed in enumerate(borrows_uf):
        if not borrowed:
            continue
        j = col + 1
        while j < len(d1_uf):
            if d1_uf[j] == 0:
                pass_through.add(j)
                j += 1
            else:
                break
    # Option B (v19.13): at all TRULY non-borrow cols, wi's digit must be
    # valid (either no-lend value or correct-with-lend value).
    correct = s["correct"]
    c_padded = str(correct).zfill(max(width, n_digits(correct)))
    c_uf = list(reversed(c_padded))
    for col in range(len(d1_uf)):
        if col < len(borrows_uf) and borrows_uf[col]:
            continue  # borrow trigger col, skip
        if col in pass_through:
            continue  # chain pass-through col, skip
        if col >= len(w_uf):
            continue
        kid = int(w_uf[col])
        valid: set[int] = set()
        if col < len(c_uf):
            valid.add(int(c_uf[col]))
        if d1_uf[col] >= d2_uf[col]:
            valid.add(d1_uf[col] - d2_uf[col])
        if kid not in valid:
            return False
    # Global deferral (v19.11): defer to S23 when cw_abs match indicates
    # the kid did a uniform column-wise abs mechanism (not S20-specific).
    if _rule_S23(s) and subtract_columnwise_abs(n1, n2) == wi:
        return False
    return True

def _rule_S21(s: dict) -> bool:
    """
    S21 BORROW_SKIPS_INTERIOR_ZERO (v19.29)

    Cognitive story: when a borrow needs to propagate through an interior
    zero (a column where n1's digit is 0, sitting between the borrow
    trigger and the eventual lender), the kid mentally JUMPS the borrow
    directly from the lender to the trigger, leaving the interior zero
    column UNTOUCHED. The 0 in the response at that col isn't a digit
    the kid chose — it's the original n1 digit, unchanged because they
    bypassed the col entirely.

    Mechanically: kid's response has 0 at a chain pass-through col, where
    the truth would have 9 (the col received 10 from above when borrowing,
    then lent 1 down to the next col — net result 9, not 0).

    This is the pedagogically-correct framing for what was previously
    "S20 Tier 2." The surface signature ("wrote 0 at pass-through col")
    is identical to S20 Tier 1's signature, but the cognitive story is
    different — and so is the remediation.

    Truth at a chain pass-through col:
      0 (original) → received 10 from above → 10
                  → lent 1 to col below → 9
      So the truth digit is 9, not 0.

    The kid's mental rule that produces this error:
      "To borrow, find the nearest non-zero digit above. Reduce it by 1.
       Add 10 to the column that needed to borrow. Leave the zeros in
       between alone."
    This rule works for borrows without interior zeros, but fails
    specifically for interior-zero cases.

    Examples (v19.29: was S20 Tier 2):
      601-8='503'   (correct=593): tens (interior 0) left as 0; truth 9
      408-109='209' (correct=299): same pattern
      8102-6='8006' (correct=8096): same pattern
      200-9='101'   (correct=191): same pattern
      300-7='203'   (correct=293): same pattern
      303-204='009' (correct=99): same pattern

    Remediation target: drill chain-borrow bookkeeping through interior
    zeros. The "zero gets a haircut from 10" framing. Pattern practice:
    300-1, 400-1, 500-2, 100-1 — explicitly trace tens=10-1=9 and
    narrate the receive-then-lend exchange.

    Cascade position (v19.29): inserted right after S20 in the cascade
    order, so that more-specific borrow rules (S16-S20) still preempt,
    but S21 wins over S22-S31. Critically, S21 wins over S26 (X-0
    identity failure) and S29/S30 (slip) — the borrow-skip story is
    more specific than identity-failure-or-slip at the interior zero.

    Guards (current as of v26):
      - wi != correct (basic), wi != 0 ("gave up")
      - The learner wrote at least as many digits as the correct answer
        (v26: counts the RAW digits written, so a full-width borrow-skip
        with leading zeros like 009 qualifies, but a bare units digit
        like 9 — which shows no skipped column — does not)
      - At least one column needs to borrow
      - No 0 at a borrow-trigger column (that surface is S20, not S21)
      - Pass-through set non-empty (else no interior zero on the chain)
      - Kid wrote 0 at a pass-through col
      - Internal deferrals: S23, S24, S26 win if they fire (preserved
        from legacy S20 Tier 2)
      - Strict match (v25): every column equals the correct answer EXCEPT
        the interior-zero pass-through column(s), where the kid wrote 0 —
        the only deviation from the correct answer is the skipped interior
        zero. (Replaced the former "Option B" valid-digit check and the
        global column-wise-abs deferral, which had let no-borrow answers
        such as 601-518='107' through.)
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    if wi == 0:
        return False
    # v26: count the digits the learner WROTE (raw), not the parsed value, so a
    # full-width borrow-skip with leading zeros (009) qualifies but a true
    # units-only answer (9) does not.
    if len([c for c in s["raw"] if c.isdigit()]) < n_digits(s["correct"]):
        return False
    borrows_uf = borrow_columns(n1, n2)
    if not any(borrows_uf):
        return False
    width = max(n_digits(n1), n_digits(n2))
    w_padded = str(wi).zfill(max(width, n_digits(wi)))
    w_uf = list(reversed(w_padded))
    # S21 requires: no zero at any trigger col (else it's S20, not S21)
    # AND at least one zero at a pass-through col.
    for col, borrowed in enumerate(borrows_uf):
        if borrowed and col < len(w_uf) and w_uf[col] == "0":
            # Trigger col has 0 — that's S20 territory, not S21
            return False
    d1, d2 = right_align_digits(n1, n2)
    d1_uf = list(reversed(d1))
    d2_uf = list(reversed(d2))
    pass_through: set[int] = set()
    for col, borrowed in enumerate(borrows_uf):
        if not borrowed:
            continue
        j = col + 1
        while j < len(d1_uf):
            if d1_uf[j] == 0:
                pass_through.add(j)
                j += 1
            else:
                break
    if not pass_through:
        return False
    has_zero_at_pt = any(col < len(w_uf) and w_uf[col] == "0" for col in pass_through)
    if not has_zero_at_pt:
        return False
    # Internal deferrals (preserved from legacy S20 Tier 2): more specific
    # borrow-related rules win.
    if _rule_S23(s) or _rule_S24(s) or _rule_S26(s):
        return False
    # Genuine borrow-skip (v25 tightening): the ONLY columns that may differ
    # from the correct answer are the interior-zero pass-through columns,
    # where the learner wrote 0 (skipped the column). EVERY other column —
    # including the borrow-trigger units — must equal the correct answer.
    # Pre-v25 this only required non-borrow cols to be "valid" (accepting the
    # column-wise |d1-d2| value), which let no-borrow answers with a 0 at the
    # interior zero slip through (e.g. 601-518='107'); those now go to S31.
    correct = s["correct"]
    W = max(width, n_digits(wi), n_digits(correct))
    c_uf = list(reversed(str(correct).zfill(W)))
    w_full = list(reversed(str(wi).zfill(W)))
    for col in range(W):
        if col in pass_through:
            if w_full[col] != "0":
                return False
        elif w_full[col] != c_uf[col]:
            return False
    return True
def _rule_S22(s: dict) -> bool:
    """
    S22 BORROW_INDUCED_ZERO_OMITTED
    (Introduced v19.33 as S23 — split from the former S22 Tier 2.
     Renumbered to S22 in v19.34 when the no-borrow/borrow units-only
     rules were merged into S09.)

    Cognitive story: the kid computed every column of the answer correctly
    (including all the borrow chain mechanics), but believes that zeros which
    APPEARED AS A RESULT of the borrow process aren't "real" answer digits
    and should not be written. They write all the non-zero columns in order
    and silently drop any borrow-induced zero.

    Example: 8102 − 6 = 8096. Working state after correct borrow chain:
      thousands=8, hundreds=1→0 (lent 1 to tens), tens=10→9 (received 10 then
      lent 1 to units), units=12 (received 10)→6 (=12−6). Correct answer 8096.
      The hundreds-column 0 is borrow-induced (came from the 1→0 reduction).
      The kid believes that 0 "isn't real" and writes '896' instead.

    Distinction from S09 UNITS_ONLY_SUBTRACTION: S09 catches "wrote only
    the units result" (truncation — kid stopped writing after the units
    column). This rule catches "wrote every column EXCEPT borrow-induced
    zeros" (selective omission within an otherwise complete multi-column
    answer). Different shapes (Lw=1 vs Lw close to Lc) and different
    misconceptions.

    Detection: wi is a subsequence of correct, all skipped positions in
               correct are zeros, and each skipped zero corresponds to a
               column that was a LENDER in the borrow chain (i.e., it was
               reduced from non-zero to zero by the borrow operation).

    Remediation: column-grid practice with one-digit-per-box discipline.
    Force the kid to confront the empty box for the borrow-induced 0 —
    they either write 0 there (correct) or leave it visibly blank (which
    makes the wrong answer obviously short).
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    cs = str(correct)
    ws = str(wi)
    if len(ws) >= len(cs) or not any_borrow_required(n1, n2):
        return False
    borrows_uf = borrow_columns(n1, n2)
    # Walk wi as a subsequence of correct; collect skipped positions.
    i = j = 0
    skipped_positions = []
    while i < len(cs) and j < len(ws):
        if cs[i] == ws[j]:
            i += 1; j += 1
        else:
            skipped_positions.append(i); i += 1
    while i < len(cs):
        skipped_positions.append(i); i += 1
    if j != len(ws) or not skipped_positions:
        return False
    if not all(cs[p] == "0" for p in skipped_positions):
        return False
    # Each skipped zero must be borrow-induced (lender column reduced to 0).
    for p in skipped_positions:
        col_uf = len(cs) - 1 - p
        is_lender = False
        for borrow_col, borrowed in enumerate(borrows_uf):
            if borrowed:
                lender = lender_column_for_borrow(n1, n2, borrow_col)
                if lender == col_uf:
                    is_lender = True
                    break
        if not is_lender:
            return False
    return True

def _rule_S23(s: dict) -> bool:
    """
    S23 BORROW_ZERO_TOP_COPIES_N2_DIGIT
    (renamed in v19.29; Tier 2 reversed-output added in v19.32)

    Cognitive story: at a column where N1's digit is 0 and a borrow is
    needed, the kid writes N2's digit at that column instead of
    correctly computing (10 − N2_digit) after borrowing. In effect:
    "I can't subtract N2_digit from 0, so I just write N2_digit down."

    Detection:
      Tier 1: at every zero-top column (d1[k]==0 AND d2[k]>0), wi's
              digit at column k equals d2[k], AND (v23 full-mechanism gate)
              the complete no-borrow S23 procedure reproduces wi exactly —
              i.e. _e20_mechanism_explains_wi(s) is True. The gate stops
              Tier 1 from firing when the zero-top columns copy N2 by
              coincidence but the rest of the answer doesn't follow the S23
              procedure (50-28='98'/'18' -> S30, not S23).
      Tier 2 (v19.32): wi == reverse_int(s21_natural), where
              s21_natural = (n1//10 − n2//10)×10 + (n2 % 10) — the same
              formula as S17 Tier 1. This is the natural S23 procedure
              output for cases where the units column is zero-top: kid
              wrote N2's units at units, did "upper-part minus
              upper-part" at the rest, then wrote the answer with
              digits reversed.

              Tier 2 deliberately requires an EXACT match against the
              specific reverse of S23's natural output, not "reverse
              has N2's digit at the zero-top column" (which is too
              weak — it admits noise like 50−28='87' where reverse(87)
              happens to have 8 at the right column but the kid clearly
              did something else).

    v19.32 partition note: this rule absorbs zero-top cases that were
    leaking to S17 via S17's Tier 2 reverse-formula match. The two
    rules now partition cleanly:
      S17: non-zero smaller top (d1[k] ∈ 1..9 and < d2[k]); +Tier 2 reverse
      S23: zero top (d1[k] == 0); +Tier 2 reverse

    Tier 1 example: 50−28='38'. At units, d1=0, d2=8, w_digit=8 → match.
    Tier 2 example: 50−28='83'. Tier 1 fails. s21_natural = (5−2)×10+8 =
    38; reverse_int(38) = 83 = wi → Tier 2 match.
    Tier 2 example: 90−6='69'. s21_natural = (9−0)×10+6 = 96;
    reverse_int(96) = 69 = wi → Tier 2 match.
    """
    if s["wi"] is None: return False
    n1, n2, wi = s["n1"], s["n2"], s["wi"]
    if wi == s["correct"]: return False
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)

    # Tier 1: ALL zero-top columns must have wi_digit == N2_digit.
    if n_digits(wi) <= width:
        v_str = str(wi).zfill(width)
        triggered = False
        bail = False
        for k in range(width):
            if d1[k] == 0 and d2[k] > 0:
                if int(v_str[k]) == d2[k]:
                    triggered = True
                else:
                    bail = True
                    break
        if not bail and triggered and _e20_mechanism_explains_wi(s):
            return True

    # Tier 2 (v19.32): wi == reverse(s21_natural). Requires at least one
    # zero-top column to be present (otherwise this rule isn't applicable).
    if not any(d1[k] == 0 and d2[k] > 0 for k in range(width)):
        return False
    t1 = (n1 // 10) - (n2 // 10)
    if t1 < 0:
        return False
    s21_natural = t1 * 10 + (n2 % 10)
    if wi == reverse_int(s21_natural) and wi != s["correct"]:
        return True

    return False

def _rule_S24(s: dict) -> bool:
    """
    S24 BORROW_ZERO_TOP_NO_REDUCE
    Detection: N1_orig==0 at borrow col AND N2>0: learner borrows (≠S23) but gets
               wrong units fact AND lender not reduced. Same answer length as correct.
               Other columns match correct.
    [ASSUMPTION] Spec is tightly worded but operationalisation is non-trivial.
    Heuristic: same length as correct AND there's a 0-top column where N2 is non-zero
    AND wi - correct fits the pattern of "lender not reduced and units fact off".
    Concretely: wi at units differs from correct units (wrong fact), AND
                wi has the same digits as correct elsewhere except at the lender column
                where it's 1 too high.

    [KNOWN SPEC DIVERGENCE] The spec's worked example (91−76=15 → w=85) does NOT
    fit S24's stated detection condition: 91 has no zero-top column (units digit
    is 1, not 0). Two interpretations were possible:
      (a) the spec example is wrong and S24 should fire only on genuine
          zero-top + lender-not-reduced cases;
      (b) the spec example is right and "N1_orig==0 at borrow col" is shorthand
          for something laxer.
    This implementation chose (a) — fire only when there's an actual zero-top
    column AND wi matches the unreduced-lender pattern (any units, other cols
    match unreduced-correct exactly). Conservative; may miss some cases the
    spec example would tag, but won't FP on cases where neither interpretation
    is justified.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    if n_digits(wi) != n_digits(correct):
        return False
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)
    # Find a zero-top column with N2>0
    has_zero_top = False
    for k in range(width):
        if d1[k] == 0 and d2[k] > 0:
            has_zero_top = True
            break
    if not has_zero_top:
        return False
    borrows_uf = borrow_columns(n1, n2)
    if not any(borrows_uf):
        return False
    for borrow_col, borrowed in enumerate(borrows_uf):
        if not borrowed: continue
        lender = lender_column_for_borrow(n1, n2, borrow_col)
        if lender is None: continue
        # Unreduced variant: correct with lender-column digit incremented by 1
        unreduced_candidate = correct + 10 ** lender
        if n_digits(wi) != n_digits(unreduced_candidate):
            continue
        # Compare digit by digit; allow differences only in units (column 0)
        wi_uf = str(wi).zfill(width)[::-1]
        un_uf = str(unreduced_candidate).zfill(width)[::-1]
        ok = True
        for k in range(min(len(wi_uf), len(un_uf))):
            if k == 0:
                continue  # units allowed to differ (wrong fact)
            if wi_uf[k] != un_uf[k]:
                ok = False
                break
        if ok and wi != correct:
            return True
    return False

def _rule_S25(s: dict) -> bool:
    """
    S25 BORROW_N2_DIGIT_IGNORED (renamed in v19.29; was BORROW_N2_TENS_IGNORED)

    Cognitive story: kid borrows correctly at column k, but then at the
    lender column (k+1) writes only the reduced lender value and forgets
    to subtract N2's digit at that same column. The kid mentally "ran
    out" after handling the borrow.

    Detection: for some borrow column k, N2[k+1] > 0 AND
               w == correct + N2[k+1] × 10^(k+1).

    The rule is general — the ignored digit can be at ANY place value
    above the borrow:
      - 2-digit: units borrow → kid ignored N2's tens
        e.g. 60−26='54' (correct=34; kid wrote 34+20=54)
      - 3-digit: tens borrow → kid ignored N2's hundreds
        e.g. 412−220='392' (correct=192; kid wrote 192+200=392)
        e.g. 507−216='491' (correct=291; kid wrote 291+200=491)
        e.g. 850−376='774' (correct=474; kid wrote 474+300=774)
      - 4-digit: hundreds borrow → kid ignored N2's thousands
        e.g. 9175−5205='8970' (correct=3970; kid wrote 3970+5000=8970)
        e.g. 4090−2442='3648' (correct=1648; kid wrote 1648+2000=3648)

    The pre-v19.29 name "BORROW_N2_TENS_IGNORED" was based on the
    2-digit case (where the ignored digit IS tens) but didn't generalize
    correctly to multi-digit problems. v19.29 renames without changing
    detection logic — the rule already handled all these cases correctly.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    borrows_uf = borrow_columns(n1, n2)
    d1, d2 = right_align_digits(n1, n2)
    d2_uf = list(reversed(d2))  # units-first
    width = len(d2_uf)
    for k, borrowed in enumerate(borrows_uf):
        if not borrowed: continue
        next_col = k + 1
        if next_col >= width: continue
        if d2_uf[next_col] == 0: continue
        candidate = correct + d2_uf[next_col] * (10 ** next_col)
        if wi == candidate:
            return True
    return False

def _x0_fail_col(k, n2_uf, eff, raw_n1_uf) -> bool:
    """v28.1: is engaged diff-col k a genuine X-0 identity failure — subtrahend
    digit 0, borrow-untouched? This is exactly the per-column test S26 has
    always applied, factored out so S26 can REQUIRE it while S27 can TOLERATE
    it when both column identities occur in the same problem (e.g. 621-601='11':
    units X-X failure + tens X-0 failure). No change to the test itself."""
    if n2_uf[k] != '0':
        return False
    if k < len(eff) and eff[k] != int(raw_n1_uf[k]):
        return False
    return True


def _xx_fail_col(k, eff_uf, d2_uf, wi_uf, correct_uf) -> bool:
    """v28.1: is engaged diff-col k a genuine X-X identity failure — effective
    top digit equals the subtrahend digit (!=0), the correct result there is 0,
    and the kid wrote that operand digit ("X") instead of 0? Exactly S27's
    per-column test, factored out so S27 can REQUIRE it while S26 can TOLERATE
    it. No change to the test itself."""
    eff_d = (eff_uf[k] - 10 if (k < len(eff_uf) and eff_uf[k] >= 10)
             else (eff_uf[k] if k < len(eff_uf) else -1))
    return (k < len(d2_uf) and eff_d == d2_uf[k] and eff_d != 0
            and int(wi_uf[k]) == eff_d and int(correct_uf[k]) == 0)


def _rule_S26(s: dict) -> bool:
    """
    S26 X_MINUS_ZERO_IDENTITY_FAILURE

    The kid failed to recognize X − 0 as an identity (X − 0 = X). This is
    a cognitive-gap diagnosis, broader than the specific "X − 0 = 0"
    misconception. It covers BOTH:

      (a) The annihilation belief — kid thinks 0 "makes everything 0",
          so they write 0 for X − 0. (BUGGY / VanLehn: SUB-0-N0=0.)
      (b) The compute-by-counting-back attempt — kid doesn't recognize
          X − 0 as an identity that needs no computation, tries to count
          back from X by 0 (or by some other amount), and writes the
          result, which is anything ≠ X. (Often single-digit off.)

    Both fail the same underlying competency (X − 0 = X as an identity)
    and have the SAME remediation: drill X − 0 = X. v19.20's broader
    framing surfaces this unified diagnosis.

    v19.25 cognitive principle:
        AT AN X-0 COLUMN THERE IS NOTHING TO COMPUTE.
    The answer is X by identity — there is no fact to misremember, and
    no procedure to slip on. Therefore any wrong digit at an engaged X-0
    column is necessarily identity failure (S26), NOT arithmetic slip
    (S29). S29 firing at an X-0 col is a category error — slip
    diagnoses presuppose a computation to slip on, which X-0 lacks.

    Cognitive consistency principle (preserved from v19.19):
      - If the kid wrote a non-zero digit at an X-0 col AND that digit
        equals the correct n1-digit, they DID apply the identity
        correctly there — no failure to diagnose at that column.
      - If the kid didn't engage with a column at all (wrote a shorter
        answer), we cannot infer identity failure from absence.

    Detection (v19.25 refined; v22 made this the SOLE path). Examine every
    column the kid demonstrably engaged with (k < engagement_len). S26
    fires IFF:
      (1) every diff col is an X-0 col, AND
      (2) at least one engaged X-0 col has a wrong digit.

    v22 — a former "canonical" branch ALSO fired whenever wi == 0 and every
    non-zero digit of correct sat at an X-0 column (e.g. 100-0='0'). It
    inferred X-0 annihilation at columns the kid never wrote, which
    contradicts the "no inference from absence" principle above, so it was
    REMOVED. Such short all-zero responses now resolve by engagement instead:
    5-0='0' stays S26 (units engaged, real diff), but 100-0='0' / 100-50='0'
    fall to S09 (only the units column was written).

    Engagement length:
        engagement_len = min(len(raw), width) when raw is digit-only
        engagement_len = min(n_digits(wi), width) otherwise
        (where width = max(n_digits(n1), n_digits(n2)))

    Leading zeros in raw count as engagement — '06' shows the kid wrote
    at 2 cols whereas '6' shows only 1 col. Beyond-n2-width cols are
    implicit X-0 (e.g., for 888-5, tens & hundreds are X-0 because
    n2=5 contributes nothing there).

    v23 engagement-coverage guards (both directions). A column-level X-0
    identity is read only when the answer length matches the problem's column
    count, width-1 <= engagement <= width. Outside that band the answer can't
    be a clean identity read:
      - under (engagement_len < width-1): a short answer to a wider problem is
        a give-up, not an X-0 failure read off the bottom column.
        27760-6180='3' -> S31; 50000-30000='3' -> S31. (width<=2 is never
        blocked: width-1 <= 1 <= engagement_len.)
      - over (n_digits(wi) > width): an answer longer than the problem is
        garbage, not an X-0 failure read off the bottom columns.
        63-2='511' -> S31; 96-6='100' -> S31; 9-0='10' -> S31.

    Examples — asymmetric handling (v19.25):
      17-10='6'    → S26 (units X-0; kid wrote 6, identity failure)
      17-10='06'  → S26 (same; explicit tens engagement)
      17-10='7'   → CORRECT (kid applied identity correctly)
      59-0='9'    → not S26 (units X-0 but kid wrote 9=9-0 — identity
                              CORRECT, no failure) → S09
      59-0='5'    → S26 (units X-0; kid wrote 5, identity failure)
      59-0='50'   → S26 (kid wrote 0 at units X-0 col)
      59-0='58'   → S26 (kid wrote 8 at units X-0 col; counting-back)
      445-404='1'  → not S26 (units NOT X-0 — n2's units=4; kid did
                                5-4=1 correctly) → S09
      445-404='001' → S26 (engaged tens X-0 with wrong digit 0)
      888-5='3'    → not S26 (engaged units only at non-X-0) → S09
      888-5='003'  → S26 (engaged tens/hundreds implicit X-0 wrong)
      96-6='80'    → S26 (engaged tens implicit X-0 with wrong digit 8)
      96-6='96'    → not S26 (engaged units diff at non-X-0 → S26
                                disqualified) → S05
      11-2='14'    → not S26 (engaged units diff at non-X-0) → S31
      100-0='0'    → S09 (v22: only units written; 0-0=0 is correct and
                              higher cols were never engaged — no inference
                              from absence, so NOT S26)
      100-0='400'  → S26 (per-col: kid wrote 4 at hundreds X-0)
      53-20='32'   → S26 (per-col: kid wrote 2 at units X-0)
      53-20='30'   → S26 (per-col: kid wrote 0 at units X-0)
      53-20='42'   → not S26 (kid changed tens too — diff at non-X-0)
      100-50='0'   → not S26 (kid wrote only units 0-0=0; tens never
                                engaged) → S09
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    # v22: the canonical wi==0 branch was REMOVED. It fired S26 on short
    # responses (e.g. 100-0='0', 40-0='0', 621-601='0') by reading an
    # X-0 annihilation at columns the kid never wrote — which directly
    # contradicts this rule's OWN stated principle ("if the kid didn't
    # engage with a column at all (wrote a shorter answer), we cannot
    # infer identity failure from absence"). S26 is now governed entirely
    # by the per-column engagement logic below: it fires only on a wrong
    # digit at a column the kid DEMONSTRABLY engaged with, where N2
    # contributes nothing. Net effect: 5-0='0' stays S26 (units engaged,
    # real diff), while 100-0='0' / 105-5='0' / 40-0='0' fall to S09
    # (one digit written; higher columns never engaged — no inference
    # from absence). One consistent meaning for S26.
    # v19.25 refined design: S26 fires when, at every column the kid
    # demonstrably engaged with (k < engagement_len):
    #   - Any diff col must be an X-0 col (else S26 doesn't fit; other
    #     rule should fire — e.g., 11-2='14' has diff at units which has
    #     n2=2, NOT X-0; that's not X-0 misconception, it's something else)
    #   - At least one engaged X-0 col must have a wrong digit
    #     (identity failure actually happened)
    #
    # v19.28 refinement: the X-0 col must also be BORROW-INDEPENDENT —
    # i.e., the col itself doesn't borrow AND isn't a lender for a lower
    # col's borrow. This makes S26 fire ONLY where the identity actually
    # holds (nothing to compute). When borrow involves the col, the col
    # DOES require computation (subtract 1 for lending, or take a borrow
    # from above), so the "no slip possible" principle fails. Borrow-
    # involved X-0 cols belong in borrow rules (S16-S23), S29 (slip),
    # or S31 — not S26.
    #
    # This makes S26 cleanly symmetric with S27 Tier 3 (v19.26), which
    # uses the SAME borrow check. The shared principle: column-level
    # identity-failure rules fire only where the identity actually holds.
    #
    # Cognitive principle: at an X-0 column there is NOTHING to compute
    # — the answer is X by identity. There's no fact to misremember, no
    # procedure to slip on. Any wrong digit at an engaged X-0 col is
    # identity failure (S26), not arithmetic slip (S29). Conversely:
    #   - If kid didn't write at a col (k >= engagement_len), we cannot
    #     infer identity failure from absence (handles 59-0='9'
    #     correctly: kid wrote 9 = 9-0 at units, identity correct;
    #     no inference at tens absence).
    #   - If kid wrote wrong at a non-X-0 engaged col, they're doing
    #     something other than X-0 misconception (slip, borrow error,
    #     etc.) — S26 disqualified.
    #   - If kid wrote wrong at a borrow-involved X-0 col (v19.28), the
    #     col isn't pure identity — slip / no-reduce / other story
    #     applies — S26 disqualified.
    #
    # Engagement length: prefer raw response length (when digit-only)
    # over parsed-wi digit count, because leading zeros in raw indicate
    # the kid wrote at those cols. Capped at width — over-engaged
    # responses are clipped to the problem's natural width.
    width = max(n_digits(n1), n_digits(n2))
    raw = s.get("raw")
    if raw is not None and isinstance(raw, str) and raw.isdigit():
        engagement_len = min(len(raw), width)
    else:
        engagement_len = min(n_digits(wi), width)
    # v23 coverage guard (mirror of S27 Tier 3): a short answer to a wider
    # problem (e.g. 27760-6180='3') is a give-up, not an X-0 identity failure;
    # don't diagnose off the one bottom column the child happened to write.
    if engagement_len < width - 1:
        return False
    # over-engagement guard (mirror of under-guard): an answer with MORE
    # digits than the problem (e.g. 63-2='511') is garbage, not a column-wise
    # X-0 identity failure read off the bottom columns.
    if n_digits(wi) > width:
        return False
    correct_uf = str(correct).zfill(width)[::-1]
    wi_uf = str(wi).zfill(width)[::-1]
    n2_uf = str(n2).zfill(width)[::-1]
    # v20: chain-aware purity test (replaces v19.28's borrow_columns check).
    # borrow_columns() flags ONLY the column that needed a borrow — not the
    # 0->9 pass-through columns of a borrow chain, nor the lender at the top.
    # So X0...0 - small problems (10000-9='99991', 6006-97='5009') leaked into
    # S26 even though the engaged X-0 column is buried inside the borrow chain
    # (those are borrow-across-zeros errors, not the X-0 identity failure).
    # n1_effective_digits_after_borrow() gives the effective top row AFTER
    # borrowing; a column is a PURE X-0 identity column iff borrowing never
    # touched it, i.e. its effective top digit still equals the original N1
    # digit. If borrowing changed it (borrowed, lent, or passed 0->9), the
    # column belongs to a borrow chain, not pure X-0 — S26 does not apply.
    eff = n1_effective_digits_after_borrow(n1, n2)  # units-first list
    raw_n1_uf = str(n1).zfill(width)[::-1]
    # v28.1: a diff col may be a genuine X-0 failure (this rule's own type) OR a
    # genuine X-X failure (S27's type) when both column identities occur in one
    # problem. Tolerate co-occurring X-X-failure cols; still require >=1 real
    # X-0 failure and disqualify on any diff col that is neither. Backward-
    # compatible: a pure X-0 answer has no X-X cols (unchanged), and a pure X-X
    # answer never sets x0_hit (so S26 stays silent there).
    _, _d2 = right_align_digits(n1, n2)
    d2_uf = list(reversed(_d2))
    x0_hit = False
    for k in range(engagement_len):
        if wi_uf[k] != correct_uf[k]:
            # Diff at engaged col k
            if _x0_fail_col(k, n2_uf, eff, raw_n1_uf):
                x0_hit = True          # genuine X-0 identity failure here
            elif _xx_fail_col(k, eff, d2_uf, wi_uf, correct_uf):
                continue               # co-occurring X-X failure (S27 also fires)
            else:
                # Non-identity diff col (real arithmetic/borrow/slip) → S26 unfit.
                return False
    return x0_hit

def _rule_S27(s: dict) -> bool:
    """S27 X_MINUS_X_EQUALS_X  (v23 unified column tier)

    The kid wrote the operand digit instead of 0 for an X-X subtraction.

    Tier 2 (whole-problem): n1 == n2 AND wi == n1 -> True. Catches kids who
        write the whole operand instead of 0 (10-10='10', 100-100='100').

    Column tier (single, v23 — replaces the v22 split Tier-1/Tier-3): fires
        when EVERY column where wi differs from the correct answer is a clean
        EFFECTIVE X-X failure (after borrow propagation the effective top
        digit equals N2's digit there, so the correct result is 0, and the
        kid wrote that digit — the "X" — instead of 0), with at least one
        such column, and the answer length matching the problem.

        Effective (not raw) digits are the key. They catch borrow-INDUCED
        X-X that a raw test misses: 9000-3951='5949' (hundreds 9-9 after the
        chain) and the extra-digit induced cases the v22 split tiers dropped
        because Tier 1 required equal length and Tier 3 excluded borrow —
        1000-991='999', 601-518='583', 2352-1844='1548'. Borrow-CONFUSION is
        rejected automatically: a borrowing column's effective digit is >= 10
        and can never equal N2's single digit, so 584-88='486' -> S29.

        Completeness: any diff column that is NOT a clean effective X-X
        disqualifies (424-315='112', 27763-6183='46133' -> S30).

        Engagement-coverage guards (both directions, mirroring S26); a
        column-level identity is read only when width-1 <= answer length
        <= width:
          - under (engagement_len < width-1): short answer to a wider
            problem is a give-up. 27763-6183='3', 3313-713='3' -> S31.
          - over (n_digits(wi) > width): answer longer than the problem is
            garbage. 91-82='123456789', 7-7='17' -> S31.

    Cognitive mirror of S26: X-0=X (S26) and X-X=0 (S27) are the two
    column-level subtraction identities; both rules fire only where the
    identity actually holds and the answer covers the problem.
    """
    if s["wi"] is None: return False
    n1, n2, wi, correct = s["n1"], s["n2"], s["wi"], s["correct"]
    if wi == correct: return False
    if n1 == n2 and wi == n1:
        return True
    width = max(n_digits(n1), n_digits(n2))
    raw = s.get("raw")
    if raw is not None and isinstance(raw, str) and raw.isdigit():
        engagement_len = min(len(raw), width)
    else:
        engagement_len = min(n_digits(wi), width)
    if engagement_len < width - 1:
        return False
    # over-engagement guard: an answer with MORE digits than the problem
    # (e.g. 91-82='123456789') is garbage, not a column-wise X-X failure.
    if n_digits(wi) > width:
        return False
    eff_uf = n1_effective_digits_after_borrow(n1, n2)
    _, d2 = right_align_digits(n1, n2)
    d2_uf = list(reversed(d2))
    correct_uf = str(correct).zfill(width)[::-1]
    wi_uf = str(wi).zfill(width)[::-1]
    # v28.1: mirror of S26's generalization — tolerate co-occurring X-0-failure
    # cols (S26's type) when both identities occur in one problem; still require
    # >=1 real X-X failure. Pure X-X answers unaffected; pure X-0 never sets
    # xx_hit (so S27 stays silent there).
    n2_uf = str(n2).zfill(width)[::-1]
    raw_n1_uf = str(n1).zfill(width)[::-1]
    xx_hit = False
    for k in range(engagement_len):
        if k >= len(wi_uf) or k >= len(correct_uf):
            break
        if wi_uf[k] != correct_uf[k]:
            if _xx_fail_col(k, eff_uf, d2_uf, wi_uf, correct_uf):
                xx_hit = True          # genuine X-X identity failure here
            elif _x0_fail_col(k, n2_uf, eff_uf, raw_n1_uf):
                continue               # co-occurring X-0 failure (S26 also fires)
            else:
                return False
    return xx_hit

def _rule_S28(s: dict) -> bool:
    """
    S28 CORRECT_ANSWER_DIGITS_SUBTRACTED
    (renamed in v19.29; was RESULT_DIGIT_SUBTRACTION — "RESULT" was ambiguous,
    new name makes explicit that it's the digits of the correct answer
    being subtracted from each other.)
    Detection: len(w)==1 AND len(correct)==2 AND
               w ∈ { |di - dj| for digit pairs (di, dj) of correct }.

    v19.17: restricted to 2-digit correct only.

    The cognitive story — "kid wrote a digit equal to the difference of
    two digits of correct" — is most defensible when correct has exactly
    one digit pair, so the match is unambiguous. For correct ≥ 3 digits
    the rule had multiple candidate pair-diffs and fired loosely; many
    of those fires were structural coincidence rather than diagnostic
    signal. Per the v19.16 corpus audit (1,233 rows / 12,657 freq of
    3+ digit correct cases), most of these were single-rule S28 fires
    that move to S31 (UNCLASSIFIED) — accepted as honest withholding
    in the absence of a more specific catching rule. The retained 2-digit
    cases (202 rows / 7,094 freq) are diagnostically clean.

    Note: same-digit 2-digit correct (e.g. correct=22, only pair is
    (2,2) → diff 0) is retained — kids writing 0 there may still be
    doing a degenerate digit-subtraction; deferring those cases would
    drop only 9 rows / 813 freq and adds no clear diagnostic benefit.
    """
    if s["wi"] is None: return False
    if n_digits(s["wi"]) != 1: return False
    if s["wi"] == s["correct"]: return False
    if n_digits(s["correct"]) != 2: return False
    return s["wi"] in pairwise_digit_diffs(s["correct"])

def _rule_S29(s: dict) -> bool:
    """
    S29 SINGLE_COLUMN_SLIP
    Detection: len(w)==len(correct) AND exactly 1 digit position differs.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    if n_digits(s["wi"]) != n_digits(s["correct"]):
        return False
    return digit_position_mismatches(s["wi"], s["correct"]) == 1

def _rule_S30(s: dict) -> bool:
    """
    S30 MULTI_COLUMN_SLIP
    Detection: len(w)==len(correct) AND ≥2 digit positions differ.
    """
    if s["wi"] is None: return False
    if s["wi"] == s["correct"]: return False
    if n_digits(s["wi"]) != n_digits(s["correct"]):
        return False
    return digit_position_mismatches(s["wi"], s["correct"]) >= 2

def _rule_S31(s: dict) -> bool:
    """S31 UNCLASSIFIED_ERROR — fallback. Always fires if wi parseable and != correct."""
    return s["wi"] is not None and s["wi"] != s["correct"]

# Predicate registry
_PREDICATES: dict[str, Callable[[dict], bool]] = {
    "S01": _rule_S01,
    "S02": _rule_S02,
    "S03": _rule_S03,
    "S04": _rule_S04,
    "S05": _rule_S05,
    "S06": _rule_S06,
    "S07": _rule_S07,
    "S08": _rule_S08,
    "S09": _rule_S09,
    "S10": _rule_S10,
    "S11": _rule_S11,
    "S12": _rule_S12,
    "S13": _rule_S13,
    "S14": _rule_S14,
    "S15": _rule_S15,
    "S16": _rule_S16,
    "S17": _rule_S17,
    "S18": _rule_S18,
    "S19": _rule_S19,
    "S20": _rule_S20,
    "S21": _rule_S21,
    "S22": _rule_S22,
    "S23": _rule_S23,
    "S24": _rule_S24,
    "S25": _rule_S25,
    "S26": _rule_S26,
    "S27": _rule_S27,
    "S28": _rule_S28,
    "S29": _rule_S29,
    "S30": _rule_S30,
    "S31": _rule_S31,
}

# ---------------------------------------------------------------------------
# Cascade traversal — handles spec's special cases (S26 early, S02 override)
# ---------------------------------------------------------------------------

def _derive_cascade_primary(matched: list[str], signals: dict) -> str:
    """
    Derive the cascade primary diagnosis from the list of matched rules.

    v19.25: One cascade-level special-case is retained — the "leading-
    zero raw" override that routes to S26 when:
      (a) raw is digit-only, AND
      (b) len(raw) > n_digits(wi) (raw has leading zeros indicating
          engagement at cols the parsed value doesn't naturally fill), AND
      (c) n_digits(wi) <= width (the parsed value fits within the
          problem's width — i.e., kid's "real" answer is plausibly an
          answer-sized number, not a concatenation/junk overflow), AND
      (d) S26 in matched (the identity-failure cognitive story
          independently fits).

    Why the override:
    Many rules (S14 Tier 1, S16 Tier 4, S16 Tier 5, S22 Tier 1, etc.)
    fire structurally based on the parsed wi value, with cognitive
    stories that assume the kid wrote a SHORTER response than width
    (e.g., S16 Tier 5 = "kid skipped units"). For leading-zero raw,
    the kid actually engaged at those cols — those cognitive stories
    don't fit. The leading-zero override systematically routes such
    cases to S26 instead of adding per-rule deferrals to every affected
    rule.

    Why the n_digits(wi) <= width bound (not len(raw) <= width):
    The bound's purpose is to exclude cases where the parsed value
    overflows the problem (concat patterns like 5-0='50' produce wi=50
    in a width=1 problem). Bounding on n_digits(wi), not len(raw),
    allows for arbitrary leading-zero padding (e.g., 180-68='0012' or
    '00012') as long as the parsed value (12) fits within the problem
    width (3). The cognitive interpretation: padding is engagement
    flagging, the parsed value is the kid's "real" answer; if the real
    answer is appropriately sized and S26 fits, route to S26.

    Examples this catches:
      180-68='012'   — Tier 5 (S16) fires structurally; SC routes to S26
      180-68='0012'  — over-width padding; SC routes to S26
      9175-5205='00' — Tier 4 (S16) fires; SC routes to S26
      72-7='05'      — S22 Tier 1 fires; SC routes to S26
      445-404='001'  — SC routes to S26 (redundant with S09/S14 deferrals)
      17-10='06'     — SC routes to S26 (redundant with S09 deferral)

    Examples this does NOT catch (correctly):
      5-0='50'  — len(raw)=2 = n_digits(wi)=2; not leading-zero
      60-10='5' — len(raw)=1 = n_digits(wi)=1; not leading-zero
      5-0='050' — n_digits(wi)=2 > width=1; over-width junk where the
                  parsed value doesn't fit the problem (S03 concat wins)
      11-2='14' — S26 doesn't fire (units diff at non-X-0)

    The v19.24 n2==0 early-fire is NOT restored — it was over-aggressive,
    routing cases like 5-0='50' to S26 over S03 by structural fiat.

    v19.23: replaces _cascade_first_match. The previous function walked
    the cascade independently and then classify() re-walked it to build
    `matched`. Now classify() walks once, and this helper just inspects
    `matched`. Predicate-call count for typical cases drops from 5x to
    2-3x (internal deferrals from S16/S17/S20 to S23 etc. still account
    for some duplication).
    """
    if "S26" in matched:
        raw = signals.get("raw")
        wi = signals.get("wi")
        if (raw is not None and isinstance(raw, str) and raw.isdigit()
                and wi is not None):
            width = max(n_digits(signals["n1"]), n_digits(signals["n2"]))
            if len(raw) > n_digits(wi) and n_digits(wi) <= width:
                return "S26"
    if matched:
        return matched[0]
    return "S31"

# ---------------------------------------------------------------------------
# Score computation (same formula as Addition)
# ---------------------------------------------------------------------------

def _priority_weight(code: str) -> float:
    pos = SUBTRACTION_CASCADE_ORDER.index(code) + 1
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
    normalized.sort(key=lambda x: (-x[1], SUBTRACTION_CASCADE_ORDER.index(x[0])))
    return normalized

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

SCORE_INCLUSION_THRESHOLD = 0.01

SUBTRACTION_PRIORS_BY_GRADE: dict[Optional[int], dict[str, float]] = {
    None: SUBTRACTION_PRIORS_ALL,
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
    Classify a Subtraction response into one or more misconception codes.

    Args:
        n1, n2: Operands (N1 - N2 = correct). Strings or integers.
        learner_response: The learner's submitted answer.
        learner_grade: Optional learner grade for prior lookup.
        return_debug: If True, includes computed signals in the result.
    """
    n1_p = parse_operand(n1)
    n2_p = parse_operand(n2)
    if n1_p is None or n2_p is None:
        return ClassifyResult(
            cascade_code="S31",
            cascade_name=SUBTRACTION_ERROR_NAMES["S31"],
            ranked=[("S31", SUBTRACTION_ERROR_NAMES["S31"], 1.0)],
            debug={"error": "operand parse failed"} if return_debug else {},
        )
    if n1_p < n2_p:
        # v19.18: invalid problem (subtraction spec assumes n1 >= n2).
        # Several rules (notably S28) assume correct >= 0 and crash on
        # negative correct (e.g. str(-2) → '-2' breaks digits()). Return
        # early with a controlled S31 rather than letting the cascade
        # raise on bad input.
        return ClassifyResult(
            cascade_code="S31",
            cascade_name=SUBTRACTION_ERROR_NAMES["S31"],
            ranked=[("S31", SUBTRACTION_ERROR_NAMES["S31"], 1.0)],
            debug={"error": "n1 < n2 (invalid subtraction problem)"} if return_debug else {},
        )

    raw = normalize_raw(learner_response)
    wi = parse_response(learner_response)
    correct = n1_p - n2_p

    signals: dict = {
        "n1": n1_p,
        "n2": n2_p,
        "wi": wi,
        "raw": raw,
        "correct": correct,
    }

    # Correct answer
    if wi is not None and wi == correct:
        return ClassifyResult(
            cascade_code="CORRECT",
            cascade_name="",
            ranked=[],
            debug=signals if return_debug else {},
        )

    # S01 fast path for invalid input (None, decimals, etc.)
    if wi is None:
        return ClassifyResult(
            cascade_code="S01",
            cascade_name=SUBTRACTION_ERROR_NAMES["S01"],
            ranked=[("S01", SUBTRACTION_ERROR_NAMES["S01"], 1.0)],
            debug=signals if return_debug else {},
        )

    # v19.23: single-pass cascade traversal. Previously classify() called
    # _cascade_first_match() (which walked the cascade) and then re-built
    # `matched` by walking the cascade a second time — every predicate
    # was evaluated 2x at minimum, more when internal deferrals re-called
    # the same rules. The single-pass version builds matched once and
    # derives cascade_primary from it.
    matched = [code for code in SUBTRACTION_CASCADE_ORDER if _PREDICATES[code](signals)]
    cascade_primary = _derive_cascade_primary(matched, signals)
    if "S31" in matched and len(matched) > 1:
        matched = [c for c in matched if c != "S31"]

    priors = SUBTRACTION_PRIORS_BY_GRADE.get(learner_grade) or SUBTRACTION_PRIORS_ALL
    ranked_full = _compute_scores(matched, cascade_primary, priors)
    ranked = [
        (c, SUBTRACTION_ERROR_NAMES.get(c, ""), s)
        for c, s in ranked_full
        if s >= SCORE_INCLUSION_THRESHOLD
    ]

    return ClassifyResult(
        cascade_code=cascade_primary,
        cascade_name=SUBTRACTION_ERROR_NAMES.get(cascade_primary, ""),
        ranked=ranked,
        debug=signals if return_debug else {},
    )

# ===========================================================================
# v27 — Applicable-interpretations flag layer
# ===========================================================================
# Two-layer tagging:
#   * classify(...).cascade_code = the SINGLE final error code, resolved by the
#     cascade + deferral rules. Unchanged by anything below.
#   * applicable_codes(...)      = the multi-hot set of codes whose mechanism
#     genuinely reconstructs the learner's typed answer (every plausible
#     interpretation, including ones the cascade defers away when choosing the
#     single winner). This is what the corpus flag columns (I..AK) hold.
#
# The set is the post-deferral matched set PLUS any deferred-but-reconstructing
# rule. Per the v26 deferral audit the genuinely deferred-but-reconstructing
# rules are S06/S10/S13/S20; each addition is gated on its own pattern firing
# (deferral suppressors neutralised) AND a reconstruction check, so loose
# width-blind matches are not introduced.

_APPLICABLE_CANDIDATES = ("S06", "S10", "S13", "S20")
_APPLICABLE_SUPPRESSORS = {
    "S06": ("S23",),
    "S10": ("S19",),
    "S13": ("S15",),
    "S20": ("S23",),
}


def _pattern_without_deferral(code: str, signals: dict) -> bool:
    """Evaluate a rule's predicate with its cascade-deferral suppressor(s)
    neutralised, exposing the rule's raw mechanism match independent of which
    higher-priority rule would win the single final code. Restores the
    suppressors afterwards (single-threaded tagging helper)."""
    suppressors = _APPLICABLE_SUPPRESSORS.get(code, ())
    g = globals()
    saved = {x: g["_rule_" + x] for x in suppressors}
    try:
        for x in suppressors:
            g["_rule_" + x] = lambda s: False
        return _PREDICATES[code](signals)
    finally:
        for x, fn in saved.items():
            g["_rule_" + x] = fn


def applicable_codes(n1, n2, learner_response, learner_grade=None) -> list[str]:
    """Multi-hot set of applicable interpretation codes for a response — the
    corpus flag set. See the v27 module note on the two-layer design. The
    single final code is classify(...).cascade_code, which this does not alter.
    """
    res = classify(n1, n2, learner_response, learner_grade, return_debug=True)
    cc = res.cascade_code
    sig = res.debug
    if cc == "CORRECT":
        return []
    # Early-return paths (operand parse fail / n1<n2 -> S31 ; wi None -> S01)
    # never build the full matched set; the flag set is just the final code.
    if "wi" not in sig or sig.get("wi") is None:
        return [cc]

    matched = [c for c in SUBTRACTION_CASCADE_ORDER if _PREDICATES[c](sig)]
    if "S31" in matched and len(matched) > 1:
        matched = [c for c in matched if c != "S31"]
    flagged = set(matched)

    n1_p, n2_p, R = sig["n1"], sig["n2"], sig["raw"]
    for code in _APPLICABLE_CANDIDATES:
        if code in flagged:
            continue
        if not _pattern_without_deferral(code, sig):
            continue
        if code == "S06":
            ok = (R == str(n1_p + n2_p))                 # sum written as-is
        elif code == "S13":
            ok = (len(R) <= max(n_digits(n1_p), n_digits(n2_p)))  # within width
        else:
            ok = True                                    # S10/S20 self-gated
        if ok:
            flagged.add(code)

    # S31 (unclassified) must never co-exist with a real interpretation.
    if len(flagged) > 1 and "S31" in flagged:
        flagged.discard("S31")
    return sorted(flagged)
