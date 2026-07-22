# v9 integration branch — change manifest

One coupled branch off `diagnostic_engine_v8` (engine 0.8.0). Final state: **597 tests green** (588 existing + 8 integration + 1 version-stamp). The Changes section below is the original 8; the post-review fixes (P0-1/P0-4/P2-4 and the entry-preferring lookup) landed on the same branch and are listed at the end. Nothing in the engineering-team scope was touched.

## Changes

1. **Calibration swap.** `data/question_parameters.csv` replaced with the bundle's seven-field 667-item file (drop-in). 667 items, 40 skills, 55 estimated / 612 borrowed-provisional. Loads cleanly, no scope-coverage warning.

2. **Seven-field lookup.** `inputs/tenant_question_lookup_v2.csv` replaced with the bundle's seven-field lookup (2,536 rows, drop-in). Item-key parity: zero silent misses against params; zero six-field division remnants in either file; all division items seven-field. (Post-review, this file was regenerated with the entry-preferring tiebreak; see the post-review section.)

3. **Stage B in-process integration.** New `engine/stage_b_integration.py`:
   - `parse_item` — guarded positional parse (exactly 6 or 7 fields, integer operands, `True`/`False` seventh field, raises otherwise).
   - `build_responses_payload` — recovers each answered question's `item` via `pool._qxid_to_item`, takes operation/n1/n2/q_type from the item, passes the division flag as a **real bool** (`parts[6] == "True"`), and sources the raw response from an injected `raw_response_of(question_id)` callable.
   - `run_stage_b` — `compute_verdicts` → mastery payload, session → responses payload, `aml_stageb.build_learning_state`, returns the merged learning state.
   - Classifier package vendored at repo-root `stage_b_classifier/` (flat imports; path wired in the glue).

4. **Test reconciliation (not behavior changes):**
   - `tests/test_question_pool.py`: skill-count assertion 39 → 40 (`test_loads_40_skills`); the 40th skill `1D - 1 to 4` is real (3 calibrated items; served Karnataka/Private/Telangana; not a Delhi skill, so the Delhi scope stays 39).
   - `tests/test_misconception_ledger.py`, `tests/test_coverage_e2e.py`: lookup constant repointed from the stale external six-field copy to `inputs/tenant_question_lookup_v2.csv` expectations unchanged at `{2:7,3:8,4:11,5:11}`. Post-review P2-4: these paths are now parameterized via `AML_TEST_DATA_DIR`, `test_lookup_repoint.diff` is folded/unneeded and no longer shipped.
   - `tests/test_stage_b_integration.py`: new, 8 tests (parse guards, the `"False"`-string resolver regression, end-to-end on a real driven session).

## Report

- **Final test count:** 597 green (588 + 8 integration + 1 version-stamp).
- **667-item load:** confirmed (667 items, 40 skills, 55 estimated / 612 borrowed-provisional).
- **Item-key parity:** zero silent misses; no six-field division `item` in params or lookup.
- **E2E (grade 3, real finalized session):** 21 in-scope skills, 21 classified, 0 no_classifiable, 0 errors, 39 questions answered; provenance `classifier_modules == MODULE_VERSIONS`, eligibility table `20260628_v1`.
- **Verdict distribution vs 638 baseline (grade 3, 10 seeded learners):** confident_mastered 156→155, confident_not_mastered 37→32, uncertain 17→23. Small expected shift toward uncertain (612 borrowed-provisional items are slightly less discriminating); one per-skill swing ≥3 learners, no large unexpected movement.

## Flags / notes for follow-up (not blockers)

- **Raw response is an injected dependency.** The session stores only `is_correct`, not the raw response string the classifier needs. The glue takes it via `raw_response_of(question_id)` — the stand-in for the response-fetch endpoint (8.4). The 8.4 endpoint (engineering-team scope) must supply raw responses for production Stage B.
- **Section 2 secondary observations left unchanged** per the note: Delhi 36/3 grade-3 variant `q_dlg3_div_00611_b` (vs `_z`), and the Karnataka 36/3 entry-test variant. Engine-owner decisions.
- **Prototype e2e harness superseded and not shipped.** The earlier standalone `test_stageb_e2e.py` targeted old prototype paths; its intent is covered by `tests/test_stage_b_integration.py` (including the e2e and the `bool("False")` resolver regression). It is not included in this bundle.
- **Seventh field currently inert** (no two-format division pairs in this bank); retained as the committed, future-proof requirement. Whether to keep it long-term is the engine owner's open call.
## Post-review fixes (landed on the same branch; final 597 tests)

- **P0-1 version 0.9.0.** `__version__`, `pyproject.toml`, `config/engine_config.yaml` -> `0.9.0`; +1 end-to-end test asserting the stored verdict stamps `engine_version == "0.9.0"` (stored, not returned on the wire).
- **P0-4 wire field rename.** `question_id` -> `question_x_id` in `SessionResponseRequest` and `QuestionRef` (plus `routes.py` and tests). It always carried a `question_x_id` value; internal names unchanged. Disambiguates from AML's own `question_id` (C-1).
- **P2-4 portable test paths.** Real-data paths parameterized via `AML_TEST_DATA_DIR`; `test_lookup_repoint.diff` folded/unneeded and no longer shipped.
- **Entry-preferring lookup.** Build tiebreak changed to entry > dlg > `_b` > lexicographic; `inputs/tenant_question_lookup_v2.csv` regenerated (47 rows changed vs prior; rendering-only, calibration is item-keyed, so no verdict/coverage/savings change). Rationale: the dynamic diagnostic replaces the Entry Diagnostic.
