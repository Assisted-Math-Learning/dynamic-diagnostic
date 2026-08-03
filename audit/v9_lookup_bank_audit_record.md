# v9 Tenant Lookup vs Corrected Question Bank - Audit Record

**Date:** 2026-06-29
**Scope:** Full consistency check of the v9 seven-field tenant question lookup against the corrected June 2026 question bank, across all four tenants (Delhi, Karnataka, Private, Telangana).
**Trigger:** The Q X ID suffix distribution (`_b`, `_b2`, `_c1`, `_z`, none) is not a clean per-tenant label. After the Private split bug (lookup pointed Private at a `_b` ID the tenant does not use), the open question was whether the same wrong-ID error existed on any other row.

## 2026-07-06 update: lookup regenerated from the corrected bank; 7 Private rows fixed

**What changed:** The shipped lookup file (`diagnostic_engine/inputs/tenant_question_lookup_v2.csv`) still carried the pre-correction Private `_b` ids on the seven split operands. Those ids do not exist for Private in the corrected bank (Private has only `_z`), so they were orphans: the engine could not have served Private those seven questions. The lookup was regenerated from the corrected all-tenant bank, and the seven Private rows now resolve to `_z`, matching the split-operand table below. This makes the shipped file match what the June-29 verdict had claimed but the file did not yet reflect.

**How:** Regenerated with the committed toolchain (`calibration/reference/build_question_lookup.py` + `item_key.py`), the 667-item `question_parameters.csv`, and `retired_questions_v2.csv` (27 item-scope keys), run against the `20260628` corrected all-tenant bank.

**Result vs the previously shipped file:**

| Property | Value |
|---|---|
| Rows | 2,536 (0 added, 0 removed) |
| question_x_id changes | 7, all Private, all `_b` -> `_z` (operands 36/3, 60/5, 75/3, 80/4, 18/6, 4/2, 7/7) |
| Misconception flag changes | 0 |
| Uncalibrated items written to the lookup | 0 |
| Division params items joined | 130 of 130 |
| 5/1 Relationship | Delhi-only; the Karnataka/Private/Telangana copies remain correctly absent (deleted questions, per "One false positive, cleared" below) |

**Bank pinned:** `20260628_AML_All_Diagnostic_Qs_of_the_4_Main_Ops_for_Calibration_With_MC_Tagging.xlsx` (sheet `Query result`, 5,067 rows). This supersedes the `20260608` workbook (pre-correction: it still held the deleted false-remainder rows and the Private `_b` split ids) and the `20260617` workbook named in the original provenance section. Regenerate future lookups, including Telangana, from this bank or a newer corrected one, never from `20260608`.

**Tests after the change:** full engine suite 597 passed; the two lookup-reading tests (`test_coverage_e2e`, `test_misconception_ledger`) 18 passed. The seven changes are Private and the real-data tests are Delhi-scoped, so no expectation shifted.

## Terms (defined once)

| Term | Meaning |
|---|---|
| Lookup | The routing table the engine uses. One row per (tenant, item) giving the question ID to serve. |
| Bank | The question bank: every physical question, each with a tenant and a Q X ID. |
| x_id | A physical question's stored identifier (e.g. `q_div_00611_z`). One logical item can have many x_ids. |
| Item | The seven-field key: Operation, Skill, Q type, MCQ text, n1, n2, remainder flag. |
| Remainder flag | Final field of a division item. True only when the stored answer format expects a remainder (`Q FiB Type = fib_quotient_remainder`). |
| Split operand | A division operand that genuinely has two answer formats. Eight were confirmed; the false-remainder rows were deleted in the correction. |
| Orphan | A lookup row whose (tenant, x_id) the bank does not have for that tenant. |

## Verdict

The shipping lookup is fully consistent with the corrected bank. Zero ID disagreements across all 2,536 rows and all four tenants. The risk raised by the suffix distribution was real but does not bite: the eight split operands were the only instances, they are fixed in the deliverable, and the rest of the lookup is clean.

One real finding remains, and it is file hygiene rather than lookup correctness: a loose working copy named `tenant_question_lookup_v2_FINAL.csv` still carried the old Private `_b` IDs. It has been synced to the correct version. See Finding 1.

## Audit result

| Check | Meaning | Result |
|---|---|---|
| A. Orphan x_ids | Lookup serves a (tenant -> x_id) the bank does not have for that tenant | 0 |
| B. Item mismatches | An x_id maps to a different item than the lookup claims | 0 |
| C. Reverse under-coverage | Bank serves an item to a tenant the lookup silently omits | 0 |

All 2,536 lookup rows checked. The membership check (every lookup x_id exists for its tenant in the bank) passed for all 2,536 before item comparison, which on its own proves the Private-style orphan class is now empty.

## Finding 1 - stale working file (resolved)

Two copies of the lookup existed on disk and disagreed on exactly the Private split rows.

| File | Private split IDs | Status |
|---|---|---|
| `v9_engine_integration_bundle.zip` -> `lookup/tenant_question_lookup_v2.csv` | `_z` (correct) | Authoritative deliverable |
| `tenant_question_lookup_v2_FINAL.csv` (loose working copy) | `_b` (old bug) | Stale, pre-remap |

The Private to `_z` remap landed in the bundle but the loose copy was never re-saved. Because the loose file is named "FINAL", it was a trap: anyone using it instead of the bundle would have re-introduced the exact Private bug. Resolution: the loose file was overwritten with the bundle's version. Both now agree (2,536 rows, Private splits at `_z`).

Action for the prototyping chat: build against the lookup inside the bundle. Treat the bundle as the single source of truth for the lookup.

## Split-operand verification

The eight split operands are the rows that caused the Private bug, so each split row in the lookup was verified individually against the corrected bank. All consistent.

| Operand | Skill | Delhi | Karnataka | Private | Telangana |
|---|---|---|---|---|---|
| 36/3 | 1D/2D by 1D without remainder | `q_dlg3_div_00611_b` | `q_div_00611_b` | `q_div_00611_z` | `q_div_00611_b` |
| 60/5 | 1D/2D by 1D without remainder | `q_div_00612_z` | `q_div_00612_b` | `q_div_00612_z` | `q_div_00612_b` |
| 75/3 | 1D/2D by 1D without remainder | `q_div_00528_z` | `q_div_00528_b` | `q_div_00528_z` | `q_div_00528_b` |
| 80/4 | 1D/2D by 1D without remainder | `q_div_00468_z` | `q_div_00468_b` | `q_div_00468_z` | `q_div_00468_b` |
| 18/6 | Relationship between Multiplication and Division | `q_div_00242_z` | `q_div_00242_b` | `q_div_00242_z` | `q_div_00242_b` |
| 4/2 | Relationship between Multiplication and Division | `q_div_00387_z` | `q_div_00387_b` | `q_div_00387_z` | `q_div_00387_b` |
| 5/1 | Relationship between Multiplication and Division | `q_div_00274_z` | not served | not served | not served |
| 7/7 | Relationship between Multiplication and Division | `q_div_00279_z` | `q_div_00279_b` | `q_div_00279_z` | `q_div_00279_b` |

Notes: every split is single-format (`fib_standard`, remainder flag False) after the correction. Delhi 36/3 is on the grade-3 variant `q_dlg3_div_00611_b`; this is a grade-specific serving choice for the engine owner to confirm, not an ID error. 5/1 exists only for Delhi in the corrected bank, and the lookup serves it only to Delhi.

## Method and data provenance

The bank was not re-keyed by hand from the 5,000-row paste (transcription risk). It was derived from the June bank workbook, which carries per-row Tenant, Q X ID, and Item Key, and adjusted to the corrected state in two ways:

1. The workbook `Item Key` column is the old six-field key (no remainder flag). The seventh field was rebuilt from `Q FiB Type` (`fib_quotient_remainder` -> True, otherwise False).
2. The eight split operands were judged against the corrected split map, not the stale workbook rows, because the correction deleted the false-remainder split rows.

Why this is safe: every one of the lookup's 2,536 (tenant, x_id) pairs is present in the workbook-derived bank, so the workbook covers 100 percent of the IDs the lookup actually touches. The workbook's per-tenant suffix counts match the stated distribution exactly for Delhi (411 `_b`, 641 `_z`, 58 none) and differ elsewhere only by the `q_entry_*` entry-test questions, which the lookup never uses. The corrections were confined to the splits, the entry-test questions, and re-calibration (which changes parameters, not the ID-to-item mapping), so outside the eight splits the workbook and the corrected bank agree.

## One false positive, cleared

The reverse check (C) initially flagged 5/1 ("Relationship between Multiplication and Division") as served by the bank to Karnataka and Private but by the lookup only to Delhi. This was a stale-workbook artifact. The pre-correction workbook held Karnataka, Private, and Telangana copies of 5/1, including `fib_quotient_remainder` variants, all of which the correction deleted. In the corrected bank 5/1 exists only for Delhi, which is exactly what the lookup does. After purging stale split-operand IDs and applying only the corrected split map, check C returned zero.

## Why this matters (mechanism)

Difficulty parameters (slip, guess) are keyed by item, not x_id, so suffix variety is invisible to calibration. The only place x_ids matter is the ID-to-item seam in the lookup: a wrong tenant-to-ID pairing never crashes, it degrades silently. Either the engine tries to serve an ID the tenant does not have (the item drops from what the tenant can be asked), or a real response arrives with an ID the lookup does not recognise (the evidence is discarded and the learner is placed less efficiently). This audit confirms that seam is clean for every row in the deliverable.

## Files

| File | Role |
|---|---|
| `v9_engine_integration_bundle.zip` -> `lookup/tenant_question_lookup_v2.csv` | Authoritative lookup, 2,536 rows (7 Private split rows corrected `_b` -> `_z` on 2026-07-06) |
| `tenant_question_lookup_v2_FINAL.csv` | Loose working copy, now synced to the authoritative version |
| `20260628_AML_All_Diagnostic_Qs_of_the_4_Main_Ops_for_Calibration_With_MC_Tagging.xlsx` | Corrected all-tenant bank (current; supersedes `20260608` and `20260617`) used to regenerate the lookup on 2026-07-06 |
| `bank_split_map.tsv` | Corrected split map (eight operands) used as the split authority |
