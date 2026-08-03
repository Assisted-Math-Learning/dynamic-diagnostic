# Implementation note: v9 misconception integration (as landed)

> **Delivered.** This branch has landed and is delivered as `diagnostic_engine/` in this bundle (engine 0.9.0, 597 tests). The steps below are the integration record - the how and why - not a to-do list. The base it was built from (0.8.0, 588 tests) is provenance, not a build target you diff against.

**For:** implementation record / engineering reviewer
**Built from:** the 0.8.0 base (588 tests); **delivered as:** `diagnostic_engine/` (engine 0.9.0, 597 tests)
**Scope:** three coupled changes that must land and be tested together: the seven-field key through the pool, the calibration swap, and the in-process Stage B step. None is independently testable, so do them in one branch and keep all 588 tests green plus the new tests below.

This note is the spec writer/reviewer chat's hand-off. It is grounded in the current engine source; where it says "verified," that was checked against the repo.

> **Grounding (historical).** This note and the prebuilt lookup were grounded against the 0.8.0 base tree (588 tests, with `data/` and `inputs/`). That base zip is not shipped in this combined bundle; the delivered code is `diagnostic_engine/`, which already contains the changes merged.

> **Revision 7 (closeout).** The branch landed: 597 tests green (588 existing + 8 integration + 1 version-stamp), nothing in engineering scope touched. Sections 5 and 5.1 record the as-landed result and follow-ups. The one substantive item: the raw learner response is an injected dependency in the in-process glue (`raw_response_of`), because the session stores only `is_correct`. The 8.4 contract already requires the endpoint to return the raw response (Section 8.4), but that rests on the assumption the raw typed response is persisted per attempt in production. That assumption is now an explicit engineering checklist item below, since all of Stage B depends on it and the in-process session object does not carry it.

> **Revision 6.** Adds Section 4, a required test repoint, after the prototyping chat found that the four real-data tests fail at baseline (584/588) for a reason outside the three changes. Those tests read params from `/mnt/project/question_parameters.csv`, which is already the seven-field 667 bank, but read their lookup from a hardcoded `/mnt/user-data/outputs/calibration/tenant_question_lookup.csv` that is still the stale six-field copy. The mismatch is a key-format problem, not a coverage change: against seven-field params, every division item fails the resolvability join and the four division misconceptions drop, producing the `{2:6,3:7,4:7,5:7}` artifact. Proven by reproduction: the same params with the seven-field lookup returns the audit `{2:7,3:8,4:11,5:11}` exactly. Do not flip the audit expectations; repoint the lookup. A one-step `test_lookup_repoint.diff` is included and was verified to apply cleanly and make the three tests pass.

> **Revision 5.** Reconciled the body text to the corrected calibration figures that the Revision 4 banner already carried: **667 items, 55 estimated, 612 borrowed** throughout (was 675 / 620 in the body). The Section 1 and Section 2 statements that described the 8 split operands as two-format pairs yielding 16 items are corrected: the question-bank owner dropped the `fib_quotient_remainder` (`|True`) half of every split pair, so each of the 8 operands is now a single `|False` item and no two-format division pairs remain in this bank. The seventh key field is retained (committed requirement, future-proof) but is currently inert. The Section 2 new test is rewritten accordingly. Source: calibration CHANGELOG rev 2, included at `calibration/reference/CHANGELOG.md`. Open design question raised by the calibration chat: with no two-format pairs left, is the seventh field still required? That is the engine owner's call; the field is harmless to keep.

> **Revision 4.** The seven-field lookup is finalized to 2,536 rows after the question-bank owner removed the `fib_quotient_remainder` rows for the 8 split operands and the calibration was re-run (now 667 items: 55 estimated, 612 borrowed; the 8 `|True` split orphans are gone). The 3 non-Delhi `5/1` rows were dropped (operand is Delhi-only in the corrected bank). Private's split x_ids are now mapped to `_z`, matching the corrected bank's explicit per-tenant listing (the v8 `_b` was stale). Two minor pre-existing serving choices on Delhi/Karnataka 36/3 are flagged in Section 2, not changed.

> **Revision 3.** Grounding correction after the prototyping chat asked which engine tree to build against. Build against the complete `diagnostic_engine_v8` tree provided alongside this note (engine 0.8.0, 588 tests, with `data/` and `inputs/`), not the partial copy at `/mnt/user-data/outputs/diagnostic_engine` (which lacks `data/` and `inputs/` and has one fewer test file). Section 2 file references corrected: the per-tenant lookup is `inputs/tenant_question_lookup_v2.csv` and the calibration file is `data/question_parameters.csv`. The offline lookup builder `build_question_lookup.py` is named only in a code comment and is not in the repo; Section 2 now reflects that.

> **Revision 2.** Incorporates the prototyping chat's review. The string-truthiness bug it found at the division-flag seam (`bool("False")` is `True`) is real and is now fixed in the shipped `aml_stageb.py` and `aml_classify.py` in this bundle (both resolvers coerce `"True"`/`"False"` correctly and reject unrecognized values); Section 3 also requires the glue to pass a real bool. Sections 3 and its acceptance now add the guarded positional parse, the exact `q_type == "Fib"` requirement, and a verdict-distribution check against the 638-item baseline.

---

## 0. One correction that changes where the work lands

The seven-field key is **not** a code change inside `engine/question_pool.py`. The pool treats `item` as an opaque content string: it reads the `item` column from `question_parameters.csv` and from `tenant_question_lookup.csv`, keys no-repeat and dedup on that string, and maps `q_x_id -> item`. There is no positional parsing of `item` anywhere in `engine/` (verified: no `split("|")` on the key). So a seventh field does not break the pool.

The seven-field key therefore enters through the **upstream files and the offline lookup build**, not through pool internals:

- `question_parameters.csv` already carries seven-field division keys (the calibration re-run).
- `tenant_question_lookup.csv` must be rebuilt so `(tenant, item)` uses the seven-field key.
- The offline builder (`build_question_lookup.py`) must construct the key from individual fields with the division-only seventh field.

So "seven-field key in the pool" means: make the build and the files use it, and verify the pool joins on it. Treat `question_pool.py` as verify-not-rewrite.

---

## 1. Calibration swap

**What:** replace the engine's calibration input with the seven-field re-run.

- Current: `data/question_parameters.csv` = 638 items, six-field keys (verified, 0 seven-field division rows).
- New: the calibration chat's seven-field `question_parameters.csv` = 667 items; division rows seven-field, non-division six-field; the 8 former split operands are now single `|False` items (the `fib_quotient_remainder` half was dropped in the bank correction, so no two-format pairs remain); 55 estimated, 612 borrowed.

**Do:**
1. Drop in the new file as `data/question_parameters.csv`.
2. Confirm `CsvQuestionPool` loads it: all engine scope skills covered, every item has an `all` grade row, the scope-coverage startup warning does not fire.

**Acceptance:**
- Existing `tests/test_question_pool.py` passes with counts updated to 667 items.
- The two `test_api.py` end-to-end tests still confirm a calibrated slip/guess reaches the Bayes update.
- Flag, do not fix: 612 of 667 items are borrowed-provisional (only Delhi has estimation data). This is expected, not a regression; the verdict distribution may shift slightly versus the 638-item file.

---

## 2. Seven-field key through the lookup build and the join

**What:** make the offline lookup build and the resulting files use the seven-field key, then verify the pool joins on it.

**Do:**
1. Rebuild the per-tenant lookup, `inputs/tenant_question_lookup_v2.csv`, so `(tenant, item)` uses seven-field keys: six fields for non-division, seven for division, the seventh being `response_includes_remainder` derived from the stored correct answer (a structured quotient-plus-remainder answer is `True`, a plain quotient is `False`), never from `n1 % n2`. **A finalized seven-field lookup is provided in this bundle at `lookup/tenant_question_lookup_v2.csv` (2,536 rows); drop it into `inputs/`, replacing the six-field baseline.** It was originally re-keyed from the v8 lookup (non-division rows byte-identical, division rows with the flag appended). As of 2026-07-06 it is instead regenerated from the committed builder (`calibration/reference/build_question_lookup.py` + `item_key.py`) against the `20260628` corrected all-tenant bank: 2,536 rows, all joining the seven-field `question_parameters.csv` with zero misses and zero uncalibrated rows, and with seven Private split rows corrected from `_b` to `_z`. The builder is now in the repo under `calibration/reference/`; see `audit/v9_lookup_bank_audit_record.md` for the regeneration record.
   - **Split operands, now resolved.** The 8 split operands (`36/3, 60/5, 75/3, 80/4, 18/6, 4/2, 5/1, 7/7`) are single `|False` items in this lookup. After the question-bank owner removed the `fib_quotient_remainder` rows for these evenly-dividing operands, each carries only `fib_standard`, so the earlier ambiguity is gone and `split_lookup_to_resolve.csv` has been retired. The only rows removed versus the v8 lookup are the 3 non-Delhi `5/1` rows (Karnataka, Private, Telangana), which the corrected bank confirms no longer exist (`5/1` is Delhi-only).
   - **Private x_id, resolved.** The corrected bank explicitly assigns Private the `_z` x_id (identical to Delhi's) for all 7 operands Private serves; the v8 lookup's `_b` was stale. This lookup now maps Private to `_z`. Two 36/3 serving choices were flagged here for confirmation and have since been resolved (see Section 2, and Engine Spec 7.8 / Appendix E, which are authoritative on this point and supersede this note): (a) Delhi 36/3 keeps its grade-3 variant `q_dlg3_div_00611_b` (dlg tier), though the bank also offers `q_div_00611_z` plus grade 4-8 variants; (b) Karnataka 36/3 resolves to its entry-test variant `q_entry_div_00611_b`, which the lookup carries as Karnataka's served variant. Both are bank-consistent and rendering-only.
2. Drop in the seven-field `data/question_parameters.csv` (the calibration swap, Section 1) so the lookup and the params agree on the key.
3. `question_pool.py`: verify, do not rewrite. Confirm it enumerates the seven-field items, no-repeat keys on the seven-field `item`, and `_qxid_to_item` resolves. (The pool already reads the lookup at `inputs/tenant_question_lookup_v2.csv` and treats `item` as opaque, so no code change is expected here.)

**Acceptance:**
- Item-key parity: every active question's built `item` matches a `question_parameters.csv` row or is logged uncalibrated. Zero silent misses.
- No six-field division `item` remains in `data/question_parameters.csv` or `inputs/tenant_question_lookup_v2.csv`.
- New test: division items carry the seventh field and round-trip through the key. Each of the 8 former split operands (`36/3, 60/5, 75/3, 80/4, 18/6, 4/2, 5/1, 7/7`) resolves to exactly one `|False` calibration row (the `|True` half was dropped in the bank correction; do not assert any `|True` split row exists). If a two-format division pair is ever reintroduced, the seven-field key must keep the two variants distinct - keep this as the regression intent, but the current bank has no two-format pairs to assert against.
- All 588 existing tests pass (the key is opaque to them, so they should be unaffected once the files are consistent).

---

## 3. Stage B in-process integration

**What:** after a session is finalized and verdicts computed, classify the learner's responses and merge the misconception layer into the learner state, in process. This is the `aml_stageb.build_learning_state` call, not the live-service triggers.

**Do:**
1. After `finalize_session` / `compute_verdicts`, build two payloads:
   - **Mastery payload** from the verdicts: per skill, `verdict`, `posterior`, `recommendation`, `resolved_by`, `n_questions_asked`, `operation`. Use the `mastery_from_verdicts` adapter shape from the prototype.
   - **Responses payload** from the session's answered questions: per answered question, `operation`, `n1`, `n2`, `response`, `q_type`, and `response_includes_remainder` for division. Recover each answered question's `item` via the pool's `_qxid_to_item`, then take `operation`/`n1`/`n2` (and the division seventh field) from the item. Three things the glue must get right at this seam:
     - **The division flag must be passed as a real boolean, not the text `"True"`/`"False"`.** Parsing the item string yields text, and `bool("False")` is `True` in Python, which would silently flip a no-remainder item to remainder-expected and reintroduce exactly the AC6 failure the seventh field exists to prevent. Set `response_includes_remainder = (parsed_field == "True")` so it is a real bool. As a backstop, the shipped resolvers (`aml_stageb._resolve_sysrem_strict` and `aml_classify._resolve_sysrem`) are now hardened to coerce `"True"`/`"False"` correctly and to reject any other value with an error rather than mis-coerce, so the seam is safe even if a string slips through. Do not remove that hardening.
     - **Positional parse, guarded.** Section 0 notes the engine proper never positionally parses `item`; this glue is the one new place that does, as the in-process stand-in for the production response-fetch endpoint (8.4). It is safe today only because `q_text` is empty for every Fib item, so the key has no embedded `|`. Make that dependency loud: assert the split yields exactly 6 fields (non-division) or 7 (division), and that the `n1`/`n2` positions parse as integers; raise on anything else so a future `q_text`-bearing or malformed item fails fast instead of mis-parsing. (If you prefer to avoid the positional dependency entirely, source `n1`/`n2`/operation from the question metadata by `q_x_id` instead of from the key; either is acceptable, the parse-with-guards is the documented default.)
     - **`q_type` must be exactly `"Fib"`.** Stage B filters `q_type == "Fib"` case-sensitively, and the bank also carries `"Mcq"` and `"Number-Sense"`. The glue must set `q_type` to exactly `"Fib"` for Fib items, or they are dropped silently from classification.

     This in-process resolution is the stand-in for the production response-fetch endpoint (8.4), which is the engineering team's job, not this branch's.
2. Call `aml_stageb.build_learning_state(responses, mastery, meta, table_dir=...)` against the all-tenant union eligibility table, and merge its output into the learner state.
3. Side files: `build_learning_state` already persists the miss log, side-cache, and drift log (the fixed `aml_stageb.py`); point `table_dir` at writable storage.

**Acceptance (e2e on a real finalized session):**
- Every in-scope skill is present; classified vs `no_classifiable_responses` is correct; `errors` is empty.
- `provenance.classifier_modules == aml_engine.MODULE_VERSIONS`; `low_support_k` recorded.
- `low_support` invariant holds (`n_eligible < k` exactly), every evidence index in `[0, 1]`.
- A division split item classifies under the correct format (the seventh field reaches the classifier as `system_expects_remainder`), not operand-inferred. Run this with the flag arriving as the text `"False"` specifically, to prove the truthiness trap is closed.
- **Record the verdict distribution against the 638-item baseline.** The calibration swap (Section 1) moves the engine onto the 667-item file with 612 borrowed items, so some movement is expected. Capture per-skill verdict counts before and after, so a large unexpected swing is surfaced and reviewed rather than assumed benign. This is a confirm step, not a fix.

---

## 4. Real-data test repoint (landed)

> **Landed (P2-4).** The repoint is folded: the tests read the engine's own `inputs/` lookup, and the data directory is overridable via `AML_TEST_DATA_DIR`. There is no manual diff step. The diagnostic below is retained for context (the key-format invariant still matters).

**What:** four tests read real data from absolute paths and fail at baseline in this environment, before any of the three changes. One is a stale assertion; three share a single root cause. Resolve all four as part of this branch.

**Why they fail (not your three changes):** these tests read params from `/mnt/project/question_parameters.csv`, which is already the seven-field 667 bank, but read their lookup from the hardcoded `/mnt/user-data/outputs/calibration/tenant_question_lookup.csv`, which is still the old six-field copy. The applicability count only credits a misconception if an item carrying its tag is grade-resolvable, and `CsvQuestionPool._resolve_row` resolves by joining the lookup `item` to the params `item`. A six-field division key never matches a seven-field division key, so every division item fails the join and the four division misconceptions (`zero_end_n1`, `zero_mid_n1`, `zero_end_quotient_no_zero_n1`, `zero_mid_quotient_no_zero_n1`) drop. That is the entire `11 -> 7` fall at G4/G5 and the `{2:6,3:7,4:7,5:7}` you see. It is a key-format mismatch in the test's inputs, not a bank coverage change.

**Proven:** with the same `/mnt/project` 667 params, the stale six-field lookup yields `{2:6,3:7,4:7,5:7}` (no division misconceptions at G4/G5); the seven-field lookup yields `{2:7,3:8,4:11,5:11}` (the audit, all four division misconceptions present). So the misconception-coverage audit is still correct against the current bank.

**Do:**
1. No manual diff is needed (landed P2-4). The `LOOKUP` constant in `tests/test_coverage_e2e.py` and the `_REAL_LOOKUP` constant in `tests/test_misconception_ledger.py` read the engine's own `inputs/tenant_question_lookup_v2.csv` (the seven-field file dropped in at Section 2) via a repo-relative path, overridable with `AML_TEST_DATA_DIR`. No expectation values change.
2. Keep the existing audit assertions as they are: `{2:7,3:8,4:11,5:11}` and Delhi-G3 `== 8`. **Do not** change them to the artifact values. The repoint makes the params and the lookup the test reads both seven-field, so the audit holds.
3. The fourth failure is the skill-count assertion (`39 -> 40`). The 667 params has 40 distinct skills; updating the count is correct. Before keeping it, confirm the 40th skill, `1D - 1 to 4`, is a real in-scope skill in the bank and not a stray or mis-keyed params row.

**Invariant to record (the comment in the diff states it):** the params file and the lookup these tests read must share the same key format - both seven-field on division (the division-only `response_includes_remainder` seventh field). If they ever diverge again, division items silently fail the resolvability join and applicability under-counts with no error.

**Acceptance:** with Section 1 (667 params in `data/`) and Section 2 (seven-field lookup in `inputs/`) applied, `tests/test_misconception_ledger.py::test_real_data_applicability_matches_audit`, `::test_real_data_end_to_end_ledger_populates`, and `tests/test_coverage_e2e.py::test_reserve_enabled_session_fires_backfill_and_reaches_floor` all pass with the audit values unchanged. (Verified: the three tests pass reading the engine's own `inputs/` lookup.)

**Note on remaining `/mnt/project` reads:** these tests still read `priors`, `anchors`, `lattice`, and `milestone` from `/mnt/project` via `scripts/smoke`. That is unrelated to the key-format issue and fine to leave. If you want to remove the external-path fragility entirely later, repoint the params constant to the engine's `data/question_parameters.csv` as well; not required for green.

## 5. Closeout (as landed)

The branch landed as one coupled set off the 0.8.0 base and is delivered as `diagnostic_engine/`. Final state and the report-back from the prototyping chat:

- **Tests:** 597 green (588 existing + 8 integration + 1 version-stamp). Nothing in engineering scope was touched.
- **Calibration swap:** 667 items, 40 skills, 55 estimated / 612 borrowed-provisional; loads with no scope-coverage warning. (The 40th skill, `1D - 1 to 4`, is real: 3 Subtraction Fib items, served Karnataka/Private/Telangana, not Delhi, so the Delhi scope stays 39. Verified independently.)
- **Item-key parity:** zero silent misses; no six-field division `item` left in params or lookup.
- **E2E (grade 3, real finalized session):** 21 in-scope skills, 21 classified, 0 `no_classifiable`, 0 errors, 39 questions answered; provenance `classifier_modules == MODULE_VERSIONS`, eligibility table `20260628_v1`.
- **Verdict distribution vs the 638 baseline (grade 3, 10 seeded learners):** `confident_mastered` 156 to 155, `confident_not_mastered` 37 to 32, `uncertain` 17 to 23. A small shift toward `uncertain`, the expected direction (borrowed-provisional items are slightly less discriminating); no large unexpected movement.

The landed change set is in `applied_change_set/` in this bundle (`engine/stage_b_integration.py`, `tests/test_stage_b_integration.py`, `CHANGES.md`), for the engineering team to apply alongside the data/lookup drop-ins.

**Follow-ups (none blocking the branch):**

1. **Raw-response persistence (engineering, before 8.4).** Confirm the raw typed response is persisted per attempt in the production schema. The in-process session object carries only `is_correct`, so the glue injects the raw response via `raw_response_of`; production 8.4 reads it from the attempt record. The spec assumes that record exists; verify it before building 8.4. Added to the engineering checklist below.
2. **Two 36/3 serving choices - resolved.** The entry-preferring tiebreak (Section 5.1) plus owner decision settles both: Delhi 36/3 keeps its grade-3 variant `q_dlg3_div_00611_b` (dlg tier), and Karnataka 36/3 resolves to the entry variant `q_entry_div_00611_b` (entry tier). Both bank-consistent; rendering-only.
3. **Fib-filter ordering (minor, noted in review).** The in-process `build_responses_payload` runs `parse_item` on every answered question and relies on Stage B's internal `q_type == "Fib"` filter, whereas Section 8.4 specifies filtering to Fib before classifying. Harmless today (the diagnostic pool is Fib-only with empty `q_text`; the e2e parsed 39 questions with 0 errors), but a non-Fib item with a non-6/7-field key or an embedded `|` would raise rather than be dropped. To match the spec and the production 8.4 path, filter to Fib before `parse_item`, or guard the parse for non-Fib items.

### 5.1 Post-review changes landed (2026-07)

After the change set above, these review fixes and decisions landed on the same integrated branch (final: **597 tests**):

- **Version stamp (P0-1).** `__version__`, `pyproject.toml`, and `config/engine_config.yaml` bumped to `0.9.0`; a new end-to-end test asserts a driven session stamps `engine_version == "0.9.0"` on the stored record (the version is stored, not returned on the wire). This is the +1 test (597 total).
- **API wire field (P0-4).** The request/response schema field `question_id` was renamed to `question_x_id` (it always carried a `question_x_id` value). Internal names unchanged. This also disambiguates from AML's own `question_id` in `learner_proficiency_question_level_data`, whose equality to `question_x_id` is still the join to confirm (C-1).
- **Portable test paths (P2-4).** Real-data test paths are parameterized via `AML_TEST_DATA_DIR` (repo-relative default) and read the engine's own `inputs/` lookup; `test_lookup_repoint.diff` is folded/unneeded and no longer shipped.
- **Entry-preferring lookup.** The build tiebreak is now entry > dlg > `_b` > lexicographic (see the pool-build spec). `inputs/tenant_question_lookup_v2.csv` carries the resulting entry-preferring resolution: **47 rows changed** vs the prior lookup, rendering-only (calibration is item-keyed, so no verdict, coverage, or savings number changes). Rationale: the dynamic diagnostic replaces the Entry Diagnostic, so serving Entry-Diagnostic-purposed questions is correct and creates no duplication for the learner.

**Owner decisions recorded:**
- Delhi `36|3` division keeps its grade-3 variant `q_dlg3_div_00611_b` (served via the `dlg` tier).
- The seventh calibration key field `response_includes_remainder` is retained though currently inert (no two-format division pairs remain); kept as future-proof.

**Forward constraint (out of scope here).** A future Dynamic Main Diagnostic mode must exclude questions a learner already saw in the entry-role diagnostic (a no-repeat check against the entry-served set). The constraint originates from the entry-replacement design and is recorded so the Main-mode work accounts for it.

**Reproducibility item (RESOLVED 2026-07-06).** The lookup toolchain is now committed as one runnable unit under `calibration/reference/`: `build_question_lookup.py`, the shared `item_key` module (the single source of truth for the seven-field composite key), `test_item_key.py`, and the two-function delegation patch to `calibrate_questions.py`. The lookup was regenerated from this toolchain against the `20260628` corrected all-tenant bank (2,536 rows, 0 uncalibrated, all 130 division items joined). This also corrected seven Private split rows from `_b` (orphan) to `_z`; see `audit/v9_lookup_bank_audit_record.md`. Regenerate future lookups (Telangana) from this toolchain and a current corrected bank.

## Explicitly NOT in this branch (engineering team)

- The online completion trigger and the offline sync job that invoke the Stage B step.
- The production response-fetch API endpoint reading the live datastore (8.4).
- **Confirm the raw typed response is persisted per attempt in the production schema, and that 8.4 returns it.** Stage B classifies the actual response, not `is_correct`; the in-process session does not carry it. The spec assumes this record exists (Section 8.4); verify before building 8.4.
- Storing `response_includes_remainder` on the question record in the production ingest schema.
- Deploy and validation against live MongoDB and real traffic.

The in-process call and its unit/e2e tests are in scope; the triggers, the live-datastore endpoint, and the deploy are not.

---

## Testing discipline

- Keep all 588 tests green throughout; add the new tests named above.
- When behavior changes, keep the old test with a flipped expectation as a regression check rather than deleting it.
- Report back: final test count, the 667-item load confirmation, the item-key parity result, and the e2e summary (skills, classified vs not, errors).

## Files provided in this bundle

- `calibration/question_parameters.csv` (seven-field, 667 items) for the calibration swap, plus `calibration/reference/` (CHANGELOG, the 16 split-key status table, the consistency report, and `calibrate_questions.py` / `rekey_question_parameters.py` showing how the seven-field key is derived - your byte-identical-key check should match these).
- `stage_b_classifier/aml_stageb.py` plus the classifier package (`aml_classify.py`, `aml_engine.py`, the four op modules, `utils.py`) for Stage B, and `stage_b_classifier/tables/eligibility_table_20260628_v1.json` (all-tenant union, 670 intrinsic keys) as the server-side table.
- The prototype's earlier standalone e2e harness (`test_stageb_e2e.py`) is **not shipped** - it targeted old prototype paths and is superseded by `tests/test_stage_b_integration.py`, which covers the e2e and the `bool("False")` resolver regression.
- `lookup/tenant_question_lookup_v2.csv` (2,536 rows, audited zero-disagreement; see `audit/`).
- `diagnostic_engine/` - the delivered engine (0.9.0, 597 tests), the sole code+data copy. Built from the 0.8.0 base (not shipped here).
- `test_lookup_repoint.diff` - the Section 4 one-step patch. Apply from the bundle root with `git apply` or `patch -p1`. Repoints the two real-data tests' lookup constant to the seven-field `inputs/tenant_question_lookup_v2.csv`; no expectation values change.
- `specs/question_pool_build_and_resolution_spec.md` (Section 3 is the authoritative key definition) and the v9 spec (Revision 7) for reference.
