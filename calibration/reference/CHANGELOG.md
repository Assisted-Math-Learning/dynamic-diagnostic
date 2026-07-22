# v9 seven-field key calibration

`question_parameters.csv` keyed on the seven-field question key
(`response_includes_remainder` appended for division rows only).

## Version history

| Date | Bank | Items | Notes |
|---|---|---|---|
| 2026-06-28 (rev 2) | 20260628 all-tenant, items dropped (5,067 rows) | 667 | Bank revision: the second answer-format (`\|True`, remainder) was dropped from all 8 two-format division pairs. 8 content items removed, 1 Q X ID removed. No estimated item affected; every surviving estimate is byte-identical to rev 1. Consistency PASS. |
| 2026-06-28 (rev 1) | 20260628 all-tenant (5,126 rows) | 675 | Re-run on the current bank; refined consistency check; `qset_x_id` cleared. |
| (prior) | 20260617 all-tenant (8,552 rows) | 675 | First seven-field run. |

## Effect of the rev-2 drop

The drop removed the remainder-expecting half of every two-format division question.
After it, **no Q X ID spans more than one content item and no operand/skill base carries
both `|True` and `|False`** - the two-format ambiguity that the seventh key field was
added to resolve no longer exists in this bank. The seventh field is retained (committed
requirement, harmless, and correct if two-format pairs return), but it is currently inert
here: every division base key maps to a single format. Division items still carry the
`|True` / `|False` suffix (81 and 49 distinct items respectively, each a single-format
operand pair).

The eight original split keys that lost their `|True` half are listed, with status, in
`division_split_reestimation_16_keys.csv` (8 in-bank, 8 dropped).

## Script layers (over the six-field script)

1. **AC11 patch (yours).** Seventh key field for division rows only, derived from
   `Q Correct Answer` JSON (a `remainder` key means True), never from `n1 % n2`.
2. **Column aliases (added).** Renames `Final Q L1 Skill` / `Final Q Content Class`.
3. **Output dedup (added).** Collapses question-in-QSet duplication to one row per
   (question, content item) x grade.
4. **Refined consistency check (added).** Flags only genuine ambiguity (rows sharing a
   key that differ in a tiebreak field, default `Q MCQ Options` / `Q Correct MCQ Option`),
   not benign grade/version/tenant pooling; remainder-only splits are treated as benign.

Isolated diffs: `calibrate_questions_AC11.diff` and
`calibrate_questions_my_additions_over_AC11.diff`.

## Results (rev 2 bank)

| Measure | Value |
|---|---|
| Content items (seven-field keys) | 667 |
| Estimated from Delhi data | 55 |
| Borrowed (provisional) | 612 |
|   - nearest-skill / same-skill | 327 / 285 |
| Question rows (Q X ID x item) | 1,967 (no remaining splits) |
| Output rows (x grade) | 11,598 |
| Estimated slip / guess (median) | 0.126 / 0.092 |
| Grade-specific (of 55 estimated) | 34 |
| MCQ guess floor applied | 5 items |
| Consistency | PASS (0 genuine; 107 benign poolings, 0 remainder splits) |

Estimated by operation (est / borrowed): Addition 15 / 171, Subtraction 15 / 189,
Division 13 / 117, Multiplication 12 / 135.

## Open flags

1. **Division two-format splits removed.** Of the original 16 split keys, the 8 `|True`
   halves were dropped; 8 `|False` remain (1 estimated - `36/3` with 24,173 Delhi
   responses - and 7 borrowed-provisional). With no two-format pairs left, consider
   whether the seventh key field is still required going forward (design decision; the
   field is currently inert but harmless and future-proof).

2. **The bank's `Item Key` column uses a different convention than the patch** (seventh
   field on all rows vs division-only). The pool-build should derive keys via the patched
   `composite_key`, not that column.

3. **Tenant is not a separable unit.** The four tenants share one bank; estimates are
   reported per item, and Delhi's estimates apply to the shared items used by the others.
## Decisions

- **Seventh key field retained (2026-07, owner-confirmed).** `response_includes_remainder` is currently inert - after rev 2 dropped the remainder-format half of all 8 two-format division pairs, no operand pair carries both formats, so the field never disambiguates today. It is kept as future-proof: if two-format division questions return, the key derivation and lookup already handle them without a schema change. Recorded so it is not re-litigated.
