# v9 Diagnostic Engine Bundle (delivered)

This bundle is the delivered v9 dynamic diagnostic engine plus its specs, calibration and lookup data, and provenance records. The misconception-classifier integration has landed: engine **0.9.0, 597 tests green**, with `question_x_id` wire fields and the 667-item calibration. The engine code and its data live in **`diagnostic_engine_v9/`** - the single code+data copy in this bundle.

## Two version numbers (keep them distinct)

- **Engine package version: `0.9.0`** - in `diagnostic_engine_v9/engine/__init__.py`, `pyproject.toml`, and `config/engine_config.yaml`. This is what the engine stamps on every stored session and verdict.
- **Design / document version: `v9`** - the dynamic diagnostic design and its document set (specs, note, audit).

The directory name `diagnostic_engine_v9/` tracks the engine release line (0.9.0). It is only a folder name: the project is `aml-diagnostic-engine` and the importable package is `engine`, so nothing in the code depends on the directory name.

## Provenance (historical, not a build step)

This engine was built from a 0.8.0 base (588 tests) by applying the misconception-integration change set (8 tests), the post-review fixes (P0-1 version stamp, P0-4 `question_x_id` wire rename, P2-4 test-path portability), and the entry-preferring lookup: 588 + 8 + 1 version-stamp = **597**. That base engine (`diagnostic_engine_v8.zip`) is **not shipped** in this combined bundle - the delivered `diagnostic_engine_v9/` already contains it merged. The four classifier module versions (addition 17, subtraction 29, multiplication 20, division 47) are per-module file identifiers and are unchanged.

Start with `v9_engine_integration_note.md` for the implementation record and the as-landed closeout (Sections 5 and 5.1).

## What landed (delivered in `diagnostic_engine_v9/`)

1. **Calibration swap.** `data/question_parameters.csv` is the seven-field 667-item bank (55 estimated / 612 borrowed-provisional). Loads with no scope-coverage warning.
2. **Seven-field lookup.** `inputs/tenant_question_lookup_v2.csv` (2,536 rows) is the entry-preferring resolution (tiebreak: entry > dlg > `_b` > lexicographic). Rendering-only: calibration is item-keyed, so verdicts, coverage, and savings are unchanged. Delhi `36|3` -> `q_dlg3_div_00611_b`; Karnataka `36|3` -> `q_entry_div_00611_b`.
3. **Stage B in-process integration.** `engine/stage_b_integration.py` connects mastery verdicts to the misconception classifier (vendored at `diagnostic_engine_v9/stage_b_classifier/`); `tests/test_stage_b_integration.py` covers it, including the `"False"`-string resolver regression and the e2e.
4. **Post-review fixes.** Version bumped to 0.9.0 with a verdict-stamp test (stored, not on the wire); the API wire field `question_id` renamed to `question_x_id`; real-data test paths parameterized via `AML_TEST_DATA_DIR`.

Out of scope (engineering team): the online completion trigger, the offline sync job, the production response-fetch endpoint (8.4), storing the remainder flag in the production ingest schema, and deploy.

## One thing that changed since the spec was written

The question-bank owner dropped the `fib_quotient_remainder` (`|True`) answer-format half from all 8 two-format division pairs:

- The calibration file has **667 items, not 675** (8 removed). Method split is 55 estimated / 612 borrowed.
- The 8 former split operands (`36/3, 60/5, 75/3, 80/4, 18/6, 4/2, 5/1, 7/7`) are now single `|False` items. There are **no two-format division pairs in this bank**.
- The seventh key field (`response_includes_remainder`) is **retained but currently inert** - kept as future-proof (owner-confirmed). Full detail: `calibration/reference/CHANGELOG.md`.

## Contents

| Path | What it is |
|---|---|
| `diagnostic_engine_v9/` | The delivered engine, sole code+data copy: `engine/` (package), `data/question_parameters.csv` (667 items), `inputs/tenant_question_lookup_v2.csv` (2,536 rows), `tests/` (597), `config/`, `stage_b_classifier/` (vendored), `pyproject.toml`. Engine 0.9.0. |
| `v9_engine_integration_note.md` / `.docx` | The implementation record and as-landed closeout. Start here. |
| `applied_change_set/CHANGES.md` | The landed-change manifest (what changed and why), retained as a standalone provenance record. The code it describes is in `diagnostic_engine_v9/`. |
| `specs/` | The v9 integration spec and the pool-build spec (Section 3 is the authoritative key definition; the tiebreak is entry > dlg > `_b` > lexicographic). |
| `calibration/reference/` | Why the calibration file looks the way it does: CHANGELOG (with the seventh-field keep decision), the 16 split-key status table, the consistency report, and `calibrate_questions.py` / `rekey_question_parameters.py` (the key-derivation source). |
| `lookup/tenant_question_lookup_v2.csv` | Provenance copy of the finalized lookup (content-identical to `diagnostic_engine_v9/inputs/tenant_question_lookup_v2.csv`). |
| `audit/` | The lookup-vs-bank audit record (zero disagreements across all 2,536 rows). |

## Verification

| Artifact | Status | How verified |
|---|---|---|
| `diagnostic_engine_v9/data/question_parameters.csv` | 667 items | Distinct `item` count = 667; zero `\|True` split orphans; byte-identical to `calibration/reference` rev-2 file (md5 `091063c2`). |
| `diagnostic_engine_v9/inputs/tenant_question_lookup_v2.csv` | 2,536 rows | Entry-preferring resolution; content-identical to the `lookup/` provenance copy (0 differing `question_x_id`, 0 flag diffs). |
| Engine version | 0.9.0 | `__init__.py`, `pyproject.toml`, `config/engine_config.yaml` all 0.9.0; verdict-stamp test asserts stored `engine_version == "0.9.0"`. |
| API wire fields | `question_x_id` | `grep question_id engine/api/schemas.py` = 0. |
| Test suite | 597 passing | Re-run in place after assembly; no dead harness. |
