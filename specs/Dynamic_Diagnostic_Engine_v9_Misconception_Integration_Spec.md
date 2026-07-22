# Dynamic Diagnostic Engine v9

### Misconception classifier integration specification (for the prototyping chat)

**Target: engine v9 (0.9.0)  |  June 2026  |  Revision 7 (post bank-correction)**

> **Revision 7 changes (factual reconciliation, one open design flag).** After Revision 6, the question-bank owner revised the bank: the `fib_quotient_remainder` (`|True`) answer-format half was dropped from all 8 two-format division pairs. Consequences, now verified against the re-run calibration file: the bank has **667 content items, not 675** (8 removed); each of the 8 former split operands is now a **single `|False` item**, so **no two-format division pairs remain in this bank** and the "16 distinct items" framing no longer holds; the method split is **55 estimated / 612 borrowed**. The seventh key field is **retained but currently inert** (every division base key maps to a single format). Where the body below still describes the 8 pairs as two-format or as 16 items (notably Section 6 and acceptance criterion 11), read it through this banner; inline `[v7 reviewer note]` tags mark those spots rather than rewriting the original text. **Open design decision for the engine owner:** with no two-format pairs left, is the seventh field still required going forward? The calibration chat raised this; the field is harmless and future-proof to keep, but it is no longer load-bearing in this bank. Source: calibration CHANGELOG rev 2.
>
> **Revision 6 changes.** The calibration re-run on the current all-tenant bank is complete and verified: `question_parameters.csv` is now seven-field-keyed (675 content items, the 8 division two-format pairs present as 16 distinct items, the two reassigned operand pairs resolved). Section 7.1 and acceptance criterion 11 are sharpened on the pool-build coupling: the pool-build must derive the seven-field key from the individual question fields with the same `composite_key` logic as calibration (division-only seventh field, derived from the stored correct answer, never from `n1 % n2`), so pool and params produce byte-identical division keys; the per-question remainder-format signal must exist on the question record for this derivation. The authoritative version of this requirement lives in `question_pool_build_and_resolution_spec.md`, Section 3.
>
> **Revision 5 changes.** The seven-field key validated by real data (8 confirmed two-format division splits); the all-tenant union eligibility table built (670 intrinsic keys, both variants per split); the Stage B entry point now persists the side files; two reassigned division operand pairs noted.
>
> **Revision 4 changes.** The classifier package now defines a `__version__` constant per module and an `aml_engine.MODULE_VERSIONS` map, so packaging defect #1 is fully resolved: provenance reads module versions from `aml_engine.MODULE_VERSIONS` (Sections 3, 4, 9, acceptance 10). No classification logic, taxonomy, or table content changed (the module diffs are the version constants only; the shipped table remains consistent, verified 0 mismatches on a sample).
>
> **Revision 3 changes.** The classifier package was updated to fix the off-table behavior: Section 7.5 (and 7.4, Section 8, acceptance criterion 8) now describe the implemented three-tier lookup (labelled table, then a performance side-cache, then inline compute) plus an `unknown_questions.csv` drift log, replacing the earlier inaccurate claim that off-table questions are auto-folded into the table. The operand-inference requirement (8.1, 8.4, acceptance 6) is tightened to match the verified runtime behavior (the absent-flag path is the unsafe inference). Section 7.1 makes the engine question key a seven-field key by adding `response_includes_remainder` (a committed v9 requirement), with the empirical collision finding.
>
> **Revision 2 changes.** Defect #1 rewritten around the missing version constant; skill-id examples use real L2.5 name strings; division `system_expects_remainder` sourced from metadata; eligibility table placed server-side only; Section 7.1 reconciled the per-question artifact with the intrinsic-key lookup; `mean_score_when_fired` defined; coverage-payoff softened to documentary-only; taxonomy-supersession work item added.

---

## 1. What v9 adds, in one paragraph

v9 bolts the misconception classifier onto the existing dynamic diagnostic engine without touching the mastery logic. Two jobs are added. A **tagger** (`aml_tag`) runs offline inside the calibration stage and pre-computes, for each question, the misconception codes that could ever fire on it; it writes a versioned **eligibility table**. A **runtime classifier** (`aml_classify`) runs once per learner after the diagnostic ends: it fetches the learner's raw responses to every diagnostic question through an API call, classifies each one with the deterministic rule modules, and aggregates the results to a **per-skill misconception evidence index**. The diagnostic's per-skill mastery verdicts and the classifier's per-skill misconceptions are then merged into a single **learning-state file** that represents the learner's current state. The three-band verdict path is unchanged.

**Define the terms used throughout.** *Misconception classifier:* a deterministic rule engine (not a machine-learning model) that maps a single arithmetic response to misconception codes. *Eligibility:* the set of codes that could appear for some response to a given question, pre-computed by probing. *Evidence index:* a bounded [0,1] proxy for how strongly a misconception is present, defined in Section 5. *Fib:* a fill-in-the-blank question where the learner types a numeric answer (the only question type the classifier handles). *Intrinsic key:* the four fields eligibility depends on, (operation, n1, n2, response_includes_remainder).

---

## 2. Pipeline

![v9 two-stage pipeline](img/v9_pipeline.png)

Stage A is build-time and shared across all learners and tenants. Stage B runs per learner at the same trigger points as the offline history scorer: online, immediately when the session ends; offline, on the next sync. The merge produces one learning-state file per learner per completed diagnostic.

---

## 3. The classifier (what is being integrated)

The classifier is the uploaded `bulk_misconception_classifier_v1` package. It is a deterministic rule cascade: the same input always yields the same output, there is no training, no GPU, and every decision is explainable from the rules. Four operation modules each expose `classify(...)` returning a `ClassifyResult` with a top `cascade_code`, a `ranked` list of `(code, name, score)` for all codes that fired, and optional debug signals.

**Pin these module versions as the v9 baseline.** The taxonomy below is the canonical one for v9 and supersedes every earlier code list (including the v8 documents, which must be corrected separately).

| Operation | Module | Codes | Range | RANDOM_OR_INVALID code |
|---|---|---|---|---|
| Addition | `addition.py` | 26 | A01-A26 | A01 |
| Subtraction | `subtraction.py` | 31 | S01-S31 | S01 |
| Multiplication | `multiplication.py` | 46 | M01-M46 | M01 |
| Division | `division.py` | 36 | D01-D36 | D01 |
| **Total** | | **139** | | |

Note for anyone carrying forward the older numbering: subtraction was renumbered from E-codes to S-codes and expanded from 28 to 31, division grew from 32 to 36, and addition was renumbered (for example A06 is now CONCAT_FORWARD). Do not assume the old code meanings.

The shared core `aml_engine.py` provides `classify_one`, the probe generator `make_probes`, and `eligible_codes`. Division's `classify` additionally takes `system_expects_remainder`; the other three do not.

**Each module exposes a `__version__` constant, and `aml_engine` aggregates them.** The package now defines `__version__` per module (`addition` = "17", `subtraction` = "29", `multiplication` = "20", `division` = "47") and `aml_engine.MODULE_VERSIONS` reads those four into one map. The provenance block (Section 9) reads `classifier_modules` from `aml_engine.MODULE_VERSIONS`, a single structured source, never parsed from a docstring or inferred from a filename.

---

## 4. Package defects to fix in v9

1. **Provenance version source: resolved in the package.** Both halves of the original defect are now fixed. The package ships **unversioned** filenames (`addition.py` ... `division.py`) and imports cleanly (the versioned-filename variant is retired), and each module now defines a machine-readable `__version__` constant, aggregated by `aml_engine.MODULE_VERSIONS` (`{"addition": "17", "subtraction": "29", "multiplication": "20", "division": "47"}`). The only remaining requirement on the build is to read the provenance block's `classifier_modules` from `aml_engine.MODULE_VERSIONS` rather than hardcoding it. Do not reintroduce versioned filenames as the version carrier.

2. **The `S01` invalid code is correct here; do not "fix" it back to `E01`.** `aml_engine.INVALID_CODES = {"A01", "S01", "M01", "D01"}` is right for these modules. Called out only because earlier drafts used `E01` for subtraction; that is the old taxonomy and must not be reintroduced.

---

## 5. Evidence index (the core metric)

For a code on one question, the classifier returns a within-question normalized score (the share of that response's evidence assigned to the code; scores for all codes that fired on a response sum to 1.0). The learner-level index aggregates these:

```
index(code, group) = sum of the code's within-question scores over the learner's
                     questions IN THE GROUP where the code fired
                     -------------------------------------------------------------
                     number of the learner's questions IN THE GROUP where the code
                     was ELIGIBLE
```

Eligibility per question = the precomputed table for the question's intrinsic key, UNION any code that actually fired on the real response (the "firing-union"). The firing-union guarantees the denominator always includes the numerator's questions, so **the index can never exceed 1**. It is a bounded proxy, deliberately not a calibrated probability.

In v8 the tool grouped by operation. **In v9 the group is the L2.5 skill** (Section 7). The index, the firing scores, and the eligibility counts all aggregate per skill.

Two reported values accompany the index. **`mean_score_when_fired`** is the mean of the code's within-question scores over only the questions where it fired (numerator divided by `n_fired`); it says how dominant the code was on the responses that triggered it, independent of how often it was eligible. The **`misconception_evidence_index`** is the numerator divided by `n_eligible` (Section 6). The two differ whenever a code was eligible on more questions than it fired on.

**The index is not a probability and must never be displayed as one.** A code eligible on a single question that fires once scores 1.0; a code firing on 6 of 10 eligible questions scores 0.6 but rests on far more evidence. To make this visible, every index in v9 output travels with `n_fired` and `n_eligible`, and carries a precomputed `low_support` flag (Section 6).

---

## 6. The `low_support` flag

A code is flagged `low_support = true` when it was eligible on fewer than `low_support_k` of the learner's questions in its skill group:

```
low_support = (n_eligible < low_support_k)
```

`low_support_k` is an **independent parameter, default 2**. It is deliberately NOT bound to the engine's `conditional_extra` (which ships at 0; binding to it would disable the flag entirely). If a future decision ties the two, track the code default (2), never the deployed value. The flag is advisory: it does not remove the code from the ranking, it marks it as resting on thin evidence so downstream consumers can de-emphasize it.

**Recommended default consumer rule.** Because the ranking sorts by index value, a `low_support` code at 1.0 (one eligible question, fired once) will out-rank a well-supported code at 0.6. So the top-ranked entry is often a thin-evidence artifact. The recommended default for any consumer (display, remediation routing) is to sort or surface well-supported codes first and demote `low_support` codes (for example, show them in a separate "weak signal" group), rather than presenting the raw index order as a confidence ranking. This is a consumer convention, not a change to the index itself.

---

## 7. Stage A: the tagger inside calibration

### 7.1 Placement

`aml_tag` becomes a job within the calibration stage. Calibration and tagging share the question pool and run in the same offline stage, but they are **separate jobs with different keys and different cadence**:

| | Slip/guess calibration | Eligibility tagging (`aml_tag`) |
|---|---|---|
| Keyed on | Full question identity (per question) | Intrinsic key: (operation, n1, n2, response_includes_remainder) |
| Output | Per-question slip/guess parameters | Versioned eligibility table |
| Runs when | Response data refreshes | Rules change, new questions added, or pending log misses to fold |
| Cost | Moderate | Slow, multiplication-bound |

> **Required engine-side change: extend the engine question key to seven fields.** The engine's question identity key today is six fields (`Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2`). v9 adds `response_includes_remainder` as the **seventh field**, so the engine key matches the classifier's question identity. This is a committed requirement, not optional, for two reasons:
>
> - **Data flow:** the response-fetch API (Section 8.4) must return `response_includes_remainder` for each division item so the orchestration can pass `system_expects_remainder` explicitly (Section 8.1). Carrying the field on the engine's question record, as part of its identity, makes the engine the single source of truth for it and guarantees it is always present to pass, removing any path to the unsafe operand-inference fallback.
> - **Silent-collapse guard, now confirmed by real data:** without the seventh field, two division questions identical in the six fields but differing in remainder expectation merge to one key, the same failure mode that previously forced adding `Q Text` as the sixth field. This is no longer hypothetical. The all-tenant calibration workbook contains **8 division six-field keys that carry both remainder formats** (skills "1D/2D by 1D without remainder" at 36/3, 60/5, 75/3, 80/4 and "Relationship between Multiplication and Division" at 18/6, 4/2, 5/1, 7/7), and these are confirmed to be **legitimate two-format questions**: one variant asks the learner for the remainder, the other does not. The six-field key would silently merge each pair; the seven-field key keeps them distinct, which is correct. (The earlier Delhi-only sample showed 0 such collisions, which is why this was first framed as latent; the full multi-tenant workbook surfaces the real cases.) **[v7 reviewer note: superseded by the bank correction. The bank owner subsequently dropped the `|True` (remainder) half of all 8 of these pairs, so they are no longer two-format in the current bank - each is a single `|False` item, and the calibration file has 667 items with zero `|True` split rows. The mechanism described here (why the seventh field exists) still stands as the rationale, but the claim that this bank contains 8 two-format pairs is no longer true. See the Revision 7 banner and the open design flag on whether the seventh field is still needed.]**
>
> The change is low-risk and backward compatible: `response_includes_remainder` is null for non-division questions, normalized to the empty string, so non-division keys are unchanged in effect; it only ever splits division items that genuinely differ in remainder expectation. This reaches beyond the classifier integration into the engine's question-pool build and key resolution (see `question_pool_build_and_resolution_spec.md`, Section 3), so it must be implemented there, not just in the classifier glue. The pool-build must construct the key from the individual question fields using the same `composite_key` logic as `calibrate_questions.py` (the seventh field appended for division rows only, derived from the stored correct answer, never from `n1 % n2`), so the pool and the calibration params produce byte-identical division keys and join correctly. A prerequisite follows: the per-question remainder-format signal (the structured correct answer that distinguishes a quotient-plus-remainder answer from a plain quotient) must be available on the question record at pool-build time, so that `response_includes_remainder` can be derived and stored on the record; if the database does not already carry it, adding it is part of this work.

**The stored artifact is per-question; the lookup is by intrinsic key.** The eligibility table on disk is a list of question entries, each carrying `question_id`, operands, `q_l2_5_skill`, and `eligible_codes`. At load time the runtime collapses this into an intrinsic-key map: it unions the `eligible_codes` of all entries that share an (operation, n1, n2, response_includes_remainder), and looks up by that key. So the eligibility *value* depends only on the intrinsic key and is **tenant-agnostic** (two questions with the same operands resolve to the same eligible set), but the table only *covers* operand combinations that appeared in the question lists fed to the tagger.

**Build from the union of all tenants' Fib questions (done).** The earlier shipped table was built from `delhi_question_list.parquet` and covered Delhi operands only. The union table has now been built from the all-tenant calibration workbook: 670 distinct intrinsic keys across all four tenants (Delhi, Telangana, Karnataka, Private), with both remainder variants present for each of the 8 split operand pairs. This is a single shared table (no per-tenant tables), because eligibility does not depend on tenant. The remainder flag for the build was taken from the workbook's authoritative `Q FiB Type` column (`fib_quotient_remainder` vs `fib_standard`).

**Calibration-pool reconciliation (two items for the calibration re-run).** Two consequences for `question_parameters.csv` follow from the seven-field key and the workbook. First, the 8 legitimate-split keys cannot be re-keyed by pure string manipulation: each existing six-field calibration row pooled two answer formats, so the 16 resulting seven-field items need slip/guess re-estimation, not a mechanical re-key. Second, two division operand pairs are skill-reassigned between the calibration snapshot and the current workbook (4/2 and 6/3 are swapped between "Division using Distribution" and "Relationship between Multiplication and Division"). Both are resolved cleanly by re-running calibration (`calibrate_questions.py`, already patched for the seven-field key, plus slip/guess estimation) on the current workbook, which regenerates `question_parameters.csv` with the correct seven-field keys, separate estimates for the splits, and current skill assignments in one pass. That re-run is a calibration-pipeline operation (it needs the raw response data and the estimation environment).

### 7.2 Scope

Only `q_type == "Fib"` questions are tagged. MCQ and Number-Sense questions are out of scope: the classifier parses a typed numeric response, which those types do not provide. They are skipped by the tagger and carry no misconceptions in the merged file (Section 9).

### 7.3 Run modes and the table contract

Retain the package's three modes: `all` (re-probe everything, fold all log rows; use after a rules change), `new` (probe only new questions, fold pending log), `log` (fold pending log only, no probing). Every run that changes the table writes a new file `eligibility_table_<date>_v<n>.json` and updates the pointer `eligibility_table_current.txt`. Nothing is overwritten, so any past version can be reproduced. `--mult-window fast` (default) keeps tagging tractable; `regular` reduces multiplication gaps at higher cost. The `--status` command reports the current version and pending log rows.

### 7.4 The miss-log lifecycle (probe-gap repair)

The miss log repairs gaps in the probe generator, not gaps in question coverage. The runtime appends `(question key, response, fired code)` to an append-only `miss_log.csv` only when a code fires that is **not in the question's eligible set**, which for a tagged question means the probe generator failed to anticipate that code for that operand pattern. The tagger (any folding mode) rotates the log aside, deduplicates into `miss_log_master.csv` keyed on (operation, n1, n2, response_includes_remainder, response, code) with a hit count and last-seen, folds the codes into the affected questions' tags, and stamps each consumed row with `folded_in_version`. Stale codes from old rules are harmless: an extra tag only widens the eligible set, it never corrupts the index (the denominator only grows). This lifecycle was verified end-to-end.

This is distinct from off-table questions (Section 7.5). For an off-table key the eligible set is the inline probe set, so a response that fires only codes the probe predicts logs nothing here; off-table questions are handled by their own mechanism, not the miss log.

### 7.5 Off-table questions: three-tier lookup, flagged but not auto-folded

An off-table question is one whose intrinsic key was administered but never tagged (set drift between the tagged pool and what the learner saw). The runtime does not treat it as a hard error. It resolves eligibility in three tiers: the labelled table first, then a performance **side-cache**, then inline compute.

- The first time an off-table key appears, the runtime computes its eligibility inline (slow, especially multiplication) and writes it to `eligibility_sidecache.jsonl` (append-only, keyed by the operand key, no skill labels). Every later occurrence, including in a separate process, is an O(1) side-cache hit. Measured on a hard multiplication (4567 x 8912): about 12s on the first inline compute, about 0.2s from the side-cache thereafter.
- Every off-table key also raises a stderr warning and is recorded in `unknown_questions.csv` (timestamp, table version, operands) so drift is visible to operators.
- The labelled table is always checked first, so a proper re-tag automatically supersedes the side-cache.
- `--no-sidecache` disables reading and writing the side-cache.

**Correction to the earlier draft: off-table questions are not auto-folded into the labelled table.** The miss log (Section 7.4) only captures probe-gaps on already-tagged operand patterns; an off-table question whose response fires only codes the inline probe predicts logs nothing and the fold adds nothing. The side-cache is a performance layer, not a source of truth: it carries no labels and does not make pre-tagging optional. **Pre-tagging the full union of administered questions is required, not optional.** The way to onboard an off-table question is to add it to the question list and re-run `aml_tag --mode new`; the side-cache only keeps the runtime fast if something slips through untagged in the meantime.

The shipped sample table covers only `delhi_question_list`, so even basic pairs drift today (for example, 47 + 38 is off-table in the sample). This is not a defect; it reflects that the sample table was built from one tenant's list. Once the all-tenant union build (above) runs over the full administered set, off-table drift should be rare and confined to genuinely new questions.

---

## 8. Stage B: the runtime classifier, per learner

### 8.1 Trigger and input assembly

`aml_classify` runs once per learner when the diagnostic session ends (online) or on sync (offline), the same trigger points as the history scorer. **Stage B runs server-side.** The raw typed response persists per question on both the online and offline paths, the diagnostic cannot complete until those raw responses reach the server, and the classifier triggers only on completion, so there is never a need to classify on the device. The orchestration fetches the learner's responses through an API call (Section 8.4), then assembles the classifier input: one item per Fib diagnostic question with the learner's **raw** response.

```json
{
  "learner_id": "L123",
  "learner_grade": 3,
  "items": [
    {"skill_id": "2-digit Addition with carry", "operation": "addition",
     "n1": 64, "n2": 18, "response": "712"},
    {"skill_id": "1D/2D/3D by 1D with remainder", "operation": "division",
     "n1": 400, "n2": 3, "response": "133 R 0", "system_expects_remainder": true}
  ]
}
```

`skill_id` is new in v9 and is required on every item (Section 8.2); it is the L2.5 **name** string, the canonical id (Section 8.2). `response` is the raw entered string, not a score or option id; raw capture is confirmed available on both paths. **`system_expects_remainder` (division only) must be passed explicitly on every division item; it must never be left absent.** It is the question's `response_includes_remainder` attribute, already a populated column on the question list the tagger consumes (set upstream, not derived by the tagger; it reflects whether `q_correct_answer` is a JSON quotient-remainder answer). The orchestration sources it from the engine question record, where `response_includes_remainder` is now the seventh key field (Section 7.1), so it is always present to pass. This is load-bearing because of the verified runtime behavior: when the flag is absent, the package's `_resolve_sysrem` silently falls back to operand inference, returning `n2 != 0 and n1 % n2 != 0`. That inference is unsafe (a remainder-expecting skill can contain an instance that divides evenly, which the inference then mishandles), and the runtime gives no signal that it fell back. So "pass explicitly" is a hard requirement on the orchestration, not a preference; the seven-field engine key (Section 7.1) is what guarantees the field is always available to pass.

### 8.2 The skill-level aggregation change (the main code change)

The package aggregates `fired_scores[op][code]` and `elig_counts[op][code]` keyed on operation. v9 changes the aggregation key to the **L2.5 skill**:

- Each input item carries `skill_id`. Aggregate `fired_scores[skill_id][code]`, `elig_counts[skill_id][code]`, and the per-skill accuracy and invalid counts.
- The evidence-index denominator becomes "the learner's questions **of that skill** where the code was eligible." A code such as CONCAT_FORWARD is eligible across an operation, but at skill level its denominator counts only that skill's questions, which is the correct granularity for remediation.
- Keep a per-operation rollup (Section 9) for convenience, computed by summing the skill groups within an operation.
- `RANDOM_OR_INVALID` codes (A01/S01/M01/D01) stay excluded from the ranking and counted separately in an invalid block, as today.

`skill_id` is the engine's canonical L2.5 skill id, which is the L2.5 **name string** itself (for example `"2-digit Addition with carry"`, `"2D x 1D"`, `"1D/2D/3D by 1D with remainder"`). There is no structured-id scheme; the name is the id, identical to the id the mastery verdict uses, so the two halves join cleanly in the merge. At runtime, `skill_id` comes from the response-fetch API item (Section 8.4), not from the eligibility table: Section 7.1 collapses the table to an intrinsic-key map at load and drops the per-question skill, so the runtime must not look for skill on the table. The table's `q_l2_5_skill` is used only at build time, for the assertion that follows. Add a build-time assertion that every table `q_l2_5_skill` is in the engine's in-scope skill list, matched as an **exact string** (whitespace and casing significant). This passes today for all 38 in-scope skills; the only L2.5 value not present is the MCQ-only skill "Repeated addition", which is out of scope by design.

### 8.3 Output (intermediate, before the merge)

Per skill: an `accuracy` block, an `invalid_responses` block, and a `ranked` list sorted by `misconception_evidence_index`, each entry carrying `code`, `name`, `misconception_evidence_index`, `n_fired`, `n_eligible`, `mean_score_when_fired`, and `low_support`. The output stamps the `eligibility_table_version` used. Malformed items go to an `errors` block.

### 8.4 The response-fetch API

The classifier needs, for each Fib diagnostic question the learner answered: the canonical `skill_id`, the operation, the operands `n1` and `n2`, the raw response, and `response_includes_remainder` for division. Define one read endpoint that returns exactly this for a given `(learner_id, session_id)`:

```
GET /diagnostic/responses/{session_id}
-> { "learner_id", "learner_grade",
     "items": [ {question_id, skill_id, operation, n1, n2, response,
                 response_includes_remainder, q_type} ... ] }
```

The orchestration filters to `q_type == "Fib"` before classifying. Operands come from the question content resolved via `question_id`; the raw response comes from the per-question attempt record (the field already persisted per the repo review). For division items, the endpoint returns `response_includes_remainder` straight from the engine question record, where it is now the seventh key field (Section 7.1); it is populated at question-pool build time by deriving it from `q_correct_answer` (a JSON quotient-remainder answer means a remainder is expected). This field must always be present on division items so the orchestration can pass `system_expects_remainder` explicitly (Section 8.1). This endpoint is the one new piece of AML-side glue Stage B requires.

---

## 9. The merged learning-state file

One file per learner per completed diagnostic. The organizing unit is the skill; mastery and misconceptions both sit under each skill. A schema version is included for forward compatibility.

```json
{
  "schema_version": "1.0",
  "learner_id": "L123",
  "learner_grade": 3,
  "tenant": "delhi",
  "generated_utc": "2026-06-26T10:15:00Z",

  "diagnostic_session": {
    "session_id": "sess_abc",
    "mode": "online",
    "completed_utc": "2026-06-26T10:14:50Z"
  },

  "provenance": {
    "engine_version": "0.9.0",
    "calibration_version": "slipguess_20260601_v3",
    "eligibility_table_version": "20260626_v1",
    "classifier_modules": {"addition": "17", "subtraction": "29",
                           "multiplication": "20", "division": "47"},
    "low_support_k": 2
  },

  "skills": [
    {
      "skill_id": "2-digit Addition with carry",
      "operation": "addition",

      "mastery": {
        "verdict": "confident_not_mastered",
        "posterior": 0.06,
        "recommendation": "take_maind",
        "resolved_by": "direct_evidence",
        "n_questions_asked": 6
      },

      "misconceptions": {
        "status": "classified",
        "n_questions_classified": 6,
        "accuracy": 0.3333,
        "n_invalid": 0,
        "ranked": [
          {"code": "A13", "name": "CARRY_APPENDED",
           "misconception_evidence_index": 1.0,
           "n_fired": 3, "n_eligible": 3,
           "mean_score_when_fired": 1.0, "low_support": false},
          {"code": "A23", "name": "SINGLE_COLUMN_SLIP",
           "misconception_evidence_index": 0.5,
           "n_fired": 1, "n_eligible": 2,
           "mean_score_when_fired": 1.0, "low_support": false}
        ]
      }
    },
    {
      "skill_id": "1D/2D/3D by 1D with remainder",
      "operation": "division",

      "mastery": {
        "verdict": "uncertain",
        "posterior": 0.55,
        "recommendation": "take_maind",
        "resolved_by": "direct_evidence",
        "n_questions_asked": 2
      },

      "misconceptions": {
        "status": "classified",
        "n_questions_classified": 2,
        "accuracy": 0.5,
        "n_invalid": 0,
        "ranked": [
          {"code": "D11", "name": "Q_RIGHT_R_ZERO",
           "misconception_evidence_index": 1.0,
           "n_fired": 1, "n_eligible": 1,
           "mean_score_when_fired": 1.0, "low_support": true}
        ]
      }
    },
    {
      "skill_id": "2D x 1D",
      "operation": "multiplication",
      "mastery": {
        "verdict": "confident_mastered",
        "posterior": 0.97,
        "recommendation": "skip_maind",
        "resolved_by": "lattice_propagation",
        "n_questions_asked": 0
      },
      "misconceptions": {
        "status": "no_classifiable_responses",
        "reason": "skill_not_directly_tested",
        "n_questions_classified": 0,
        "ranked": []
      }
    }
  ],

  "operation_rollup": {
    "addition": {"n_classified": 6, "accuracy": 0.3333, "invalid_rate": 0.0},
    "division": {"n_classified": 2, "accuracy": 0.5, "invalid_rate": 0.0}
  },

  "errors": [
    {"reason": "malformed_item", "operation": "addition",
     "question_id": "q_xyz", "detail": "missing n2"}
  ]
}
```

### 9.1 Merge rules

| Rule | Detail |
|---|---|
| Top unit is the skill | Mastery and misconceptions nest under the same `skill_id`, which is the L2.5 name string, joined on exact match. No separate `skill_name` field is needed since the id is the name. |
| Mastery is present for every in-scope skill | Mastery coverage is a superset of misconception coverage. |
| `misconceptions.status` distinguishes the cases | `classified` (responses existed; `ranked` may still be empty if all were correct), or `no_classifiable_responses` with a `reason` (skill resolved by prior or lattice propagation, or tested only via MCQ/Number-Sense, so nothing to classify). Skills with no classifiable responses stay in the file, they are not omitted. |
| Index always carries its support | `n_fired`, `n_eligible`, and `low_support` accompany every index. |
| Classifier accuracy is kept separate from mastery | They are different measurements: classifier `accuracy` is raw correctness on Fib items; `mastery.verdict` is the Bayesian verdict over all question types. Label both, never conflate. |
| Provenance is mandatory and structured | engine version, calibration version, eligibility-table version, the four classifier module versions (read from `aml_engine.MODULE_VERSIONS`), and `low_support_k`. |
| Errors are surfaced | malformed or unclassifiable items go to `errors`, not silently dropped. |

---

## 10. Deployment and dependencies

The runtime classifier (`aml_classify` plus the four modules, `aml_engine`, `utils`) is pure Python and stdlib-only at runtime. Run it inside the existing sibling Python service that hosts the engine, invoked at session end (online) or sync (offline). The tagger (`aml_tag`) needs pandas and pyarrow and runs as an offline batch job in the calibration stage (a CronJob), not in the request path. **The eligibility table lives server-side only.** Because Stage B runs on the server (Section 8.1), the table does not ship to the device and is not bundled with the offline trees; the offline trees go to the device for the live diagnostic, while misconception classification reads the server-side table after the responses sync back. The runtime resolves the table through its pointer file. The runtime's two side files, `eligibility_sidecache.jsonl` (the off-table performance cache) and `unknown_questions.csv` (the drift log), live in the same server-side table directory; provision it as writable, durable storage so the cache persists across processes and the drift log accumulates for operators. Note that `unknown_questions.csv` is append-only with no dedup: it writes one row per off-table key per run, so the same key recurs across runs (two keys over two runs produced four rows in testing). It will grow with traffic until the keys are tagged, so operators should dedup on read (group by the operand key) or rotate the file periodically. The side-cache, by contrast, is keyed and effectively deduplicated (one entry per off-table key, last-write-wins). The Stage B entry point (`aml_stageb.build_learning_state`) writes all three side files itself, in the same on-disk format as `aml_classify`, so the off-table performance cache and drift visibility hold on the server-side Stage B path and not only when classification is run through the `aml_classify` CLI.

---

## 11. Out of scope for v9 (non-goals)

- The three-band mastery verdict path is unchanged. The classifier is purely a downstream consumer.
- The in-engine misconception coverage layer (Pass-2 backfill, `conditional_extra`) is unchanged. The two stages are fully decoupled, so the link is **documentary only**: there is no mechanical guarantee that a misconception the coverage layer satisfied will be well-supported in Stage B. Stage B classifies Fib items only, so a misconception covered via an MCQ or via a Fib question on which it is not eligible can still end up low-support (low `n_eligible`). v9 does not make coverage target eligibility; it only notes the relationship.
- MCQ and Number-Sense questions are not classified.
- `learner_grade` is carried for future per-grade priors and currently has no effect on output (the per-grade prior tables hold only the default).
- No per-tenant eligibility tables: eligibility is tenant-agnostic (depends only on operands).

**Adjacent work item (owner needed, not part of the engine build).** The 139-code taxonomy supersedes the old 132-code / E-code numbering, which still lives in `aml_classifier_v2.html`, the four v8 documents, and any taxonomy reference tables. These will mismatch the engine until updated. This needs an explicit owner and is tracked separately from the v9 engine work.

---

## 12. Acceptance criteria

The prototyping chat should verify, against the pinned module versions:

1. **Taxonomy:** 139 codes total (A01-A26, S01-S31, M01-M46, D01-D36); invalid codes A01/S01/M01/D01 excluded from ranking and counted separately.
2. **Determinism:** identical output across repeated runs on the same input and table.
3. **Eligibility completeness:** on a probe set across the tagged pool, every fired non-invalid code is in the table (zero misses), and every index is in [0,1].
4. **Skill-level aggregation:** the evidence index, accuracy, and invalid counts aggregate per L2.5 `skill_id`, not per operation; the operation rollup equals the sum of its skills.
5. **`low_support`:** flagged exactly when `n_eligible < low_support_k`, default 2, independent of `conditional_extra`.
6. **Division remainder sourcing:** the four-case framing is correct for (system expects remainder) x (learner gave QR or integer). `system_expects_remainder` is passed explicitly on every division item; verify the orchestration never leaves it absent, because the runtime's absent-flag path silently falls back to operand inference (`n1 % n2`), which is unsafe for remainder-expecting skills that divide evenly. Test that a remainder-expecting item which happens to divide evenly is handled correctly when the flag is passed, and document that absent-flag behavior is a defect to be prevented at the orchestration, not relied upon.
7. **Merge fidelity:** the learning-state file joins mastery and misconceptions on the L2.5 name as the skill id; `status`/`reason` correctly mark skills with no classifiable responses; provenance is complete.
8. **Off-table behavior:** an untagged question classifies via inline compute on first hit, is recorded in `unknown_questions.csv` with a stderr warning, and its eligibility is written to `eligibility_sidecache.jsonl`; a second occurrence is served from the side-cache (no recompute, no duplicate cache row); the labelled table takes precedence over the side-cache; `--no-sidecache` disables it. Off-table questions are not folded into the labelled table; the miss log (criterion separate) only repairs probe-gaps on already-tagged operand patterns. Onboarding an off-table question is via adding it to the question list and re-running `aml_tag --mode new`.
9. **Performance:** a fully tagged full-grade batch (up to 76 items) classifies in well under one second. State the scope of the budget: it should cover process start plus import of the four modules (multiplication is the largest, about 2,300 lines) plus table load plus classification. Per-item classification on the fast path is about 3 ms; the cold-start fixed cost is import and table load, which dominate for small batches.
10. **Packaging and provenance:** the modules import cleanly under their standard names; each exposes `__version__` and `aml_engine.MODULE_VERSIONS` returns `{"addition": "17", "subtraction": "29", "multiplication": "20", "division": "47"}`; verify the merged file's `classifier_modules` is read from `aml_engine.MODULE_VERSIONS`, not hardcoded or parsed from a docstring or filename.
11. **Seven-field engine key:** the engine question identity key carries `response_includes_remainder` as the seventh field (Section 7.1), populated at build time from the stored correct answer, null/empty for non-division. Verify non-division keys are unchanged in effect, that two division questions identical in the first six fields but differing in remainder expectation now resolve to distinct keys, and that the response-fetch API returns the field from the engine record so `system_expects_remainder` is always passed explicitly. **Key parity:** the pool-build and `calibrate_questions.py` must produce byte-identical keys from the same individual fields (both deriving the division seventh field from the stored answer, never from `n1 % n2`); spot-check that every active division question's constructed key joins to a calibration row, including the eight two-format pairs that appear as sixteen distinct keyed items. **[v7 reviewer note: after the bank correction these eight pairs are single-format, so the spot-check should expect eight `|False` items, not sixteen. The byte-identical-key requirement and the "derive the seventh field from the stored answer, never from `n1 % n2`" rule are unchanged and remain the core of this criterion.]**

A practical sequencing note carried over from the review: criteria 1 (taxonomy), 2, 3, 6, 8, and 10 are runnable against the shipped package now, before any v9 code exists, and are worth running first to de-risk the build. Criteria 4, 5, 7, and 11 depend on v9 engine and orchestration changes (skill-level aggregation, the merge, and the seven-field key) and can only be checked after the prototyping chat builds them.
