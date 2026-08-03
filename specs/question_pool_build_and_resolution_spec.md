# Implementation Spec: Per-Tenant Question Resolution, Retired-List, and Misconception Tagging

**Date:** June 2026
**For:** the prototyping chat (engine and question-pool implementation)
**Companion files shared with this spec:**
- `question_parameters.csv` (the calibration sidecar, keyed on `item`)
- `20260608_AML_All_Diagnostic_Qs_..._With_MC_Tagging.xlsx` (the validated misconception fixture; see Section 5.5)

**Status:** Ready to build. This spec revises the existing `CsvQuestionPool` (from `csv_question_pool_spec.md`) and adds a new offline build step. It does not change the discrimination-window selection logic (Sections 5.1-5.5 of the existing pool spec stand).

---

## 1. What this spec covers, in one paragraph

The engine selects questions by content (the `item` key) but must return a tenant-correct `question_x_id` the AML product can load. This spec defines (A) a new offline **build step** that turns each tenant's active-question list into a `(tenant, item) -> question_x_id` lookup and, in the same pass, derives each item's **11 misconception tags** and a **retired-list** filter; and (B) the change to **`CsvQuestionPool`** so its final step resolves the chosen `item` to the session tenant's `question_x_id` and carries the misconception tags. Calibration data is untouched throughout.

## 2. Why these four pieces are one spec

They share one join key (`item`) and one execution point (the offline build step, run when inputs change). Splitting them would duplicate the `item`-key construction, which is the main correctness risk. The four pieces:

| Piece | What it does |
|---|---|
| A. Per-tenant lookup build step | `(tenant, item) -> question_x_id`, from each tenant's active-question list |
| B. `CsvQuestionPool` resolution change | select in `item` space, return the tenant's `question_x_id` |
| C. Retired-list filter | exclude content or instances the content team has retired |
| D. Misconception tagging | derive 11 per-item misconception flags for the selection logic |

## 3. The `item` key (shared by all four pieces)

Every join in this spec is on the `item` content key, constructed identically to the calibration script:

```
item (non-division) = Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2
item (division)     = Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2 | response_includes_remainder
```

For division questions the key carries a **seventh field**, `response_includes_remainder`. Non-division keys are unchanged (six fields). The seventh field distinguishes the two division answer formats: some division questions ask the learner for a quotient and a remainder, and some ask only for the quotient. The same operands can appear in both formats as genuinely different questions, so without this field the two would collapse to one key and one calibration row, which is incorrect. (This is the same class of problem that put `Q Text` in the key.)

**Deriving the seventh field.** `response_includes_remainder` is derived from the question's stored correct answer: a quotient-plus-remainder answer (a structured answer that carries a remainder value) yields `True`; a plain quotient answer yields `False`. It MUST be derived from the stored answer, never inferred from the operands (`n1 % n2`): a remainder-format question whose operands happen to divide evenly is still `True`, and operand inference would mislabel exactly those. The build step derives this field per division question and stores it on the question record so it is available wherever the key is constructed.

**Field mapping (important):** in the shared workbook the operation field is named `Final Q L1 Skill` (column E); there is no column literally named `Q L1 Skill`. The build step reads `Final Q L1 Skill` into the L1 position of the key. The other five base fields are named as shown (`Q L2.5 Skill`, `Q Type`, `Q Text`, `Q N1`, `Q N2`). Do not look for a `Q L1 Skill` column; it does not exist.

The build step MUST construct `item` from these individual fields using the exact same field order, separator, normalization, and division-only seventh-field rule as `calibrate_questions.py` (`composite_key`): the base fields joined by `|`, each normalized as the empty string when null and `str(value)` otherwise, with `response_includes_remainder` appended for division rows only. Construct the key from the individual fields; do not consume any precomputed key column. `Q N1` and `Q N2` are stored as integers, so there is no `3` versus `3.0` drift (the most common silent-miss cause). If the construction differs by even a trailing space, or if the seventh field is appended to non-division rows or omitted from division rows, the join to `question_parameters.csv` silently misses and questions fall back to default calibration. This is the single most important correctness property in the spec: the build step and the calibration script must produce byte-identical keys from the same fields. The build step should assert that every active question's `item` either matches a calibration row or is explicitly logged as uncalibrated. (The calibration `question_parameters.csv` is the seven-field re-run on the current all-tenant bank: 667 content items. The eight operand pairs that were formerly two-format are now single `|False` items after the bank owner dropped the remainder-format half, so the bank currently has no two-format division pairs; the build step must still reproduce the seven-field keys to join to them. If a two-format pair is reintroduced later, this same key derivation keeps the variants distinct.)

---

## 4. Piece A: the per-tenant lookup build step

A standalone offline script, run when any tenant's active-question list changes (the same regenerate-on-input-change discipline as the offline tree). It is not part of the live engine.

### 4.1 Input

Per tenant, a list of active diagnostic questions. The content team provides **columns A to T** of the shared workbook (no misconception columns; those are derived in Piece D). The fields the build step needs from that input:

| Field | Use |
|---|---|
| `Tenant` | The tenant this row belongs to |
| `Final Q L1 Skill` (column E; the operation) | Read into the L1 position of `item`; also gates misconception derivation. There is no `Q L1 Skill` column; use `Final Q L1 Skill` |
| `Q L2.5 Skill` | Part of `item` |
| `Final Q Content Class` (column with values `class-one`..`class-five`) | Gates the `zero_minus_x` misconception (see 5.4); not part of `item` |
| `Q Type` (`Fib`/`Mcq`) | Part of `item`; misconceptions are Fib-only |
| `Q Text`, `Q N1`, `Q N2` | Part of `item`; operands drive misconception derivation |
| `Q Correct Answer` | Drives division and answer-digit misconception logic |
| `Q X ID` (the `question_x_id`) | The value the lookup maps to |

### 4.2 Output

A single combined artifact the engine loads at startup, with one logical record per `(tenant, item)`:

- `tenant`
- `item`
- `question_x_id` (resolved, see 4.3)
- the 11 misconception flags (from Piece D)

Plus a small **build report** listing: items with no calibration match, items dropped by the retired-list, and any `(tenant, item)` that resolved to multiple `question_x_id`s (with the tiebreak applied).

### 4.3 Resolving `(tenant, item) -> question_x_id`

1. Construct `item` from the six raw fields (Section 3).
2. Group the tenant's rows by `item`.
3. Where one `item` has several `question_x_id`s within the tenant, apply a deterministic tiebreak so selection and the offline tree always resolve identically. **Tiebreak (precedence): prefer a `question_x_id` containing `entry`, then one containing `dlg` (a Delhi grade-specific variant), then one ending in `_b`, then the lexicographically smallest.** The `entry` tier is deliberate: the dynamic diagnostic replaces the Entry Diagnostic, so where an Entry-Diagnostic-purposed question exists for an `item` it is the correct one to serve (verified: every `entry`-tier pick lands on an `Entry Diagnostic` QSet purpose). The `dlg` tier keeps Delhi's grade-specific variants; `_b` and lexicographic are the fallbacks. This precedence is rendering-only - calibration is keyed on `item`, so all of an item's variants share identical slip/guess and the choice changes only which concrete question renders, not any verdict. Of 8,605 ids, 5,709 end in `_b`; multi-id groups commonly mix different base numbers (for example `q_add_00124_b`, `q_add_80002_b`, `q_entry_add_80002_b`), so the precedence, not an "unsuffixed base" rule, decides. The tiebreak fires constantly, not rarely: 895 of 2,628 `(tenant, item)` pairs map to more than one id (up to 10 each), so it must be deterministic. Of the 895 multi-id groups, 860 contain at least one `_b` id; the remaining 35 contain none (all `_z`) and resolve by the lexicographic-smallest fallback. Note one consequence to be aware of: the `_dlg<N>_` prefix is a grade tag, and when a group contains per-grade `_dlg` `_b` variants, lexicographic-smallest selects the lowest-numbered available `_dlg` grade variant (not necessarily `_dlg1`; most content has no grade-1 variant, so for example `2-digit Addition with carry` starts at grade 3 and resolves to its `_dlg3` variant where a `_b` exists). This is accepted: the decision is to keep the simple lexicographic rule rather than add a learner-grade-match step. The per-grade variants are the same content, and the AML product can load a `question_x_id` whose `_dlg` grade prefix differs from the learner's grade, so the served question is unchanged. One downstream consequence to keep in mind: a learner's response may be logged against a `question_x_id` carrying a different grade prefix than the learner's grade; this is accepted because the content is identical.

### 4.4 Why per-tenant

The base `question_x_id` is consistent across tenants, so this is not ID translation. The lookup is per-tenant because (a) the active set of questions differs by tenant, and (b) within a tenant one `item` can map to several `question_x_id`s. The lookup absorbs both.

**Data reality (the build machinery runs against multi-tenant data from day one).** The shared workbook is already multi-tenant: Private (3,134 rows), Karnataka (1,909), Telangana (1,863), Delhi (1,699); 8,605 data rows in total. So the per-tenant build and resolution are exercised immediately, not only in some future state. Tenant coverage of the calibrated item set is uneven: of the 667 calibrated items, Delhi serves 595, Karnataka 649, Private 646, and Telangana 646 (650 distinct items are served across all tenants, and 594 are served by all four). No tenant carries the full set. This unevenness is the concrete reason the tenant-availability filter (Section 7.2, step 3) is required.

---

## 5. Piece D: deriving the 11 misconception tags

The build step derives 11 misconception flags per `item` from the raw fields (operation, type, N1, N2, correct answer). The content team will NOT ship these columns; the build step computes them. The logic below has been validated against the content team's reference workbook across all 8,605 rows with zero mismatches.

### 5.1 The 11 misconceptions

| # | Op | Tag | Fires when (for a `Fib` question of that operation) |
|---|---|---|---|
| 1 | Addition | `x_plus_0` | At some aligned place value, exactly one of the two operands' digits is 0 and the other is nonzero |
| 2 | Addition | `x_plus_x` | At some aligned place value, both operands have the same nonzero digit |
| 3 | Subtraction | `x_minus_0` | At some aligned place value, the top digit is nonzero and the bottom digit is 0 |
| 4 | Subtraction | `zero_minus_x` | At some column, the effective top digit (after borrow propagation) is 0 while the bottom digit is nonzero. Forced to 0 for `class-one` skills (see 5.4) |
| 5 | Subtraction | `x_minus_x` | At some column, the effective top digit (after borrow propagation) equals the bottom digit and is nonzero |
| 6 | Multiplication | `x_into_x` | The multiplier and multiplicand share at least one common digit that is neither 0 nor 1 (a nonzero, non-one digit of one operand appears in the other) |
| 7 | Multiplication | `x_into_0` | Either operand contains a 0 digit |
| 8 | Division | `zero_end_n1` | N1 (the dividend) ends in 0 |
| 9 | Division | `zero_mid_n1` | N1 contains a 0 that is not solely the trailing zero (a non-trailing 0) |
| 10 | Division | `zero_end_quotient_no_zero_n1` | The quotient ends in 0 AND N1 contains no 0 |
| 11 | Division | `zero_mid_quotient_no_zero_n1` | The quotient contains a non-trailing 0 AND N1 contains no 0 |

A question carries a flag of 1 for each misconception it covers and 0 otherwise; a single question can carry several (multi-tagging). MCQ questions and questions of a different operation carry 0 for all flags (the reference fixture uses `-`; represent as "not applicable / 0" in the engine).

### 5.2 Supporting computations the flags depend on

These are the validated helper logics the flags build on. Implement them once and reuse.

**Place-value digits.** For an operand, extract digits right to left into ones (O), tens (T), hundreds (H), thousands (Th), ten-thousands (TTh). A place is absent if the number is too short; absent places never satisfy a "both digits present" condition.

**Parsing the correct answer.** The `Q Correct Answer` is either a bare number (most questions) or, for division, a JSON object `{"quotient":Q,"remainder":R}`.
- Quotient: if the answer contains `quotient`, parse the JSON and take `quotient`; otherwise the bare answer is the quotient.
- Remainder: if the answer contains `remainder`, take it from the JSON; otherwise there is no remainder.
- The answer-digit decomposition (used for division misconceptions) uses the **quotient** digits, never the remainder. None of the 11 misconceptions inspect the remainder.

**Subtraction borrow propagation (the `Sub_B_Top` logic).** Misconceptions 4 and 5 depend on the **effective top digit at each column after borrowing**, not the raw N1 digit. Borrows cascade through zeros: e.g. `6006 - 97`, the tens column's effective top becomes 9 (after the borrow cascade), so `9 - 9` at the tens triggers `x_minus_x`. Implement a faithful columnar borrow: process O upward, carry a borrow flag, and at each column compute the effective top digit (raw digit, minus 1 if it lent to the right, plus 10 if it borrowed from the left). The validated reference for this is the workbook's `Sub_B_Top` columns; the port must reproduce them.

### 5.3 Exact derivation rules (validated)

For precision, the rules below are the validated logic. "aligned place" means same place value in both operands. All misconception flags are computed only when `Q Type == Fib` and the operation matches; otherwise 0.

- `x_plus_0` (Addition): 1 if for any place present in both operands, exactly one digit is 0 (one is 0, the other nonzero).
- `x_plus_x` (Addition): 1 if for any place present in both operands, the two digits are equal and nonzero.
- `x_minus_0` (Subtraction): 1 if for any place present in both, the top digit is nonzero and the bottom digit is 0.
- `zero_minus_x` (Subtraction): if `Final Q Content Class == class-one`, force 0. Otherwise 1 if at any column the effective top digit after borrow propagation is 0 and the bottom digit is nonzero. (Equivalent validated form: the borrow-resolved top value at that column is a multiple of 10, i.e. the top presents as 0 there, with bottom nonzero.)
- `x_minus_x` (Subtraction): 1 if at any column the effective top digit after borrow propagation equals the bottom digit and is nonzero.
- `x_into_x` (Multiplication): 1 if any nonzero, non-one digit of one operand also appears among the other operand's digits.
- `x_into_0` (Multiplication): 1 if either operand's digit string contains a 0.
- `zero_end_n1` (Division): 1 if the last digit of N1 is 0.
- `zero_mid_n1` (Division): 0 if N1 is a single digit; 0 if N1's only 0 is the trailing one; 0 if N1 has no 0; otherwise 1.
- `zero_end_quotient_no_zero_n1` (Division): 1 if the quotient's last digit is 0 AND N1 contains no 0; else 0.
- `zero_mid_quotient_no_zero_n1` (Division): 0 if quotient is a single digit; 0 if the quotient's only 0 is trailing; 0 if quotient has no 0; otherwise 1 only if N1 contains no 0; else 0.

### 5.4 The `class-one` exclusion

`zero_minus_x` is forced to 0 when `Final Q Content Class == class-one` (grade-1 content). Note this gates on the content-class column, not `Q L2.5 Skill`: the `class-*` values live in `Final Q Content Class`, while `Q L2.5 Skill` carries skill names (such as `1D - 0 to 9`), so gating on `Q L2.5 Skill` would never fire. Rationale (from the content team): the AML product covers no negative numbers, the borrow concept is introduced only in grade 2, and grade-1 `10 - x` problems are solved by finger counting, not columnar borrowing. So `0 - x` is not a meaningful misconception for class-one content.

### 5.5 Acceptance test: match the reference fixture exactly

The shared workbook `20260608_AML_All_Diagnostic_Qs_..._With_MC_Tagging.xlsx` contains the content team's reference tags in columns AQ to BA. **The port is correct if and only if, for every one of the 8,605 rows, the derived 11 flags reproduce columns AQ to BA exactly** (treating the workbook's `-` as the not-applicable/0 case). Build this as the primary regression test for Piece D. The mapping of workbook column to tag:

| Workbook column | Tag |
|---|---|
| AQ `x + 0` | `x_plus_0` |
| AR `x + x` | `x_plus_x` |
| AS `x - 0` | `x_minus_0` |
| AT `0 - x` | `zero_minus_x` |
| AU `x - x` | `x_minus_x` |
| AV `x into x` | `x_into_x` |
| AW `x into 0` | `x_into_0` |
| AX `0 end n1` | `zero_end_n1` |
| AY `0 mid n1` | `zero_mid_n1` |
| AZ `No 0 in n1 but 0 end Quotient` | `zero_end_quotient_no_zero_n1` |
| BA `No 0 in n1 but 0 mid Quotient` | `zero_mid_quotient_no_zero_n1` |

**Fixture-bank caveat.** The misconception-parity regression above is written against the `20260608` workbook's AQ-BA reference columns, which encode `zero_minus_x` PRE-gate (class-one Subtraction not yet zeroed). The `20260628` bank's AQ-BA columns encode it POST-gate (class-one Subtraction zeroed per Section 5.4). The build pipeline applies the class-one gate after derivation, so the shipped flags already match `20260628`. If this fixture is ever re-pointed from `20260608` to `20260628`, the comparison MUST use the gated flags (`derive_flags(..., gate=True)`); a raw pre-gate comparison will false-alarm on 31 class-one Subtraction `zero_minus_x` rows (derived=1 vs post-gate reference=0). Re-validated 2026-07-06: the gated derivation reproduces the `20260628` AQ-BA columns with 0 mismatches across all 5,067 rows of that bank; separately, of the 4,107 `(tenant, Q X ID)` questions surviving from `20260608`, none had a modified flag-input field (the June 28 changes were row deletions plus the 7 Private id corrections, not operand or answer edits), so the derivation itself is unchanged.

### 5.6 MCQ and future extension

All 11 tags are Fib-only today; MCQ questions carry 0 for all. This is intended: the content team may add MCQ-based misconception tags later. When they do, the derivation for MCQ will come from the content team (MCQ misconceptions cannot be derived from operands the same way), so leave a clean seam: the tag-derivation function should be dispatched by `Q Type`, with the MCQ branch currently returning all-zero.

---

## 6. Piece C: the retired-list filter

A maintained list of content or instances the content team has retired from active selection, while their calibration data is retained. Applied in both the build step (Piece A) and the pool (Piece B).

### 6.1 Format

| Column | Meaning |
|---|---|
| `scope` | `item` or `question_x_id` |
| `key` | the `item` content key (for `item` scope) or the `question_x_id` (for `question_x_id` scope) |
| `reason` | free-text justification |
| `retired_date` | ISO date |

### 6.2 Two scopes

- **`item` scope:** retire all questions with this content (this N1/N2/skill combination), in every tenant. Use when the content itself is the problem. This is global because the defect is the content.
- **`question_x_id` scope:** retire one specific question instance. Use when a particular rendering is broken but the same content is fine elsewhere. Effect is naturally per-tenant, since a `question_x_id` lives in only one tenant.

### 6.3 Filter rule

Exclude a candidate if **either** its `item` matches an `item`-scope entry **or** its `question_x_id` matches a `question_x_id`-scope entry. Apply this:
- in the build step, so retired content never enters the lookup or the offline tree; and
- in the pool's candidate enumeration, so retired content is never selected even though it remains in `question_parameters.csv`.

### 6.4 Validation and guards

- **Scope/key consistency:** an `item`-scope key must parse as a 6-field `item`; a `question_x_id`-scope key must look like a question id. Reject malformed rows at load.
- **Resolve-or-warn:** a retired key matching nothing in the current pool gets a warning, not a hard error (content churns).
- **Coverage guard:** if filtering leaves a skill with zero selectable questions for a tenant, surface it (ties into `NO_QUESTION_FOR_SKILL`); a retirement must not silently strip a skill to empty.

**Current-data check (verified):** all 18 retirements (Section 6.5) are present in both `question_parameters.csv` and the workbook, so the resolve-or-warn check finds every one and emits no warnings. After retirement, no `(tenant, skill)` is stripped to zero selectable questions: Delhi `2-digit Addition with carry` drops to 6 selectable items and all other `(tenant, skill)` pairs remain populated, so the coverage guard is satisfied on current data.

### 6.5 The current retirements

27 questions are retired now, all `item` scope, in two batches. The first 18 (`retired_date` 2026-06-08, reason "grey-area validity: solvable without the tagged skill (finger-counting vs the formal procedure); retained for calibration") are content-level retirements whose calibration data stays in `question_parameters.csv` unchanged. A second batch of 9 (`retired_date` 2026-06-17) removes 4 duplicate items (each shares its L1 skill, Q Type, N1, and N2 with a kept item under a different L2.5 skill; calibration retained on the kept item) and 5 uncalibrated Private-tenant Repeated-addition items. So the "calibration unchanged" statement holds for the 18 grey-area retirements but not universally; the engine's `retirement_guard.py` enforces a `DECALIBRATED_ALLOWLIST` of 10 `item` keys permitted to be absent from the 667-item calibration set.

---

## 7. Piece B: the `CsvQuestionPool` change

The existing pool (per `csv_question_pool_spec.md`) does six steps and returns a single global `question_id`. This spec changes only the inputs it loads and its final resolution step. **The discrimination-window selection (steps 1-5) is unchanged.**

### 7.1 What the pool loads at startup

| Input | Source | Note |
|---|---|---|
| Calibration | `question_parameters.csv`, keyed on `item` | unchanged |
| Per-tenant lookup + misconception tags | the build-step output (Piece A + D) | new |
| Retired-list | the retired-list file (Piece C) | new |

### 7.2 Changed selection flow

1. Enumerate candidate `item`s for the skill from `question_parameters.csv` (unchanged).
2. **Apply the retired-list filter** (new, Section 6.3): drop retired `item`s and any candidate whose resolved `question_x_id` is retired.
3. **Apply the tenant-availability filter** (new): drop any candidate `item` that the session tenant's lookup cannot resolve to a `question_x_id`. This is essential because tenant coverage of the calibrated item set is partial (Delhi carries only 595 of 667 calibrated items; the other tenants carry more but none carries all - Karnataka 649, Private 646, Telangana 646; see Section 4.4). Filtering here means the discrimination window in step 5 only ever sees items this tenant can actually serve, so a Delhi session never picks one of the 72 Delhi-missing items and then fails, as long as the skill has any other Delhi-available question.
4. No-repeat on `item` (unchanged).
5. Resolve parameters at the learner's grade (unchanged).
6. Discrimination window + floor (unchanged), now applied to the tenant-available candidates only.
7. Pick one (unchanged: random online, deterministic for the offline tree).
8. **Resolve to `question_x_id` (changed):** look up `(session.tenant_id, chosen item)` in the per-tenant lookup and return that `question_x_id` plus the chosen row's `slip` and `guess`. After step 3 this lookup always succeeds, so a missing entry here is an internal invariant violation, not a normal path. `NO_QUESTION_FOR_SKILL` is raised earlier, at enumeration: it fires only when steps 2 and 3 leave zero candidates for the skill in this tenant, which is the genuine coverage gap (no tenant-available, non-retired calibrated question exists for the skill), not the incidental case of a single unavailable item.

**Implementation note (code readability):** the step-number comments inside `pick_question_for_skill` should follow this 1-to-8 sequence exactly. Earlier code carried out-of-order step labels (a duplicated step number and a jump in the sequence); align the comments to the numbering above. This is a comment-only cleanup with no logic change.

### 7.3 Misconception tags are carried, not acted on (yet)

The pool attaches each candidate's 11 misconception tags to what it returns, so the selection layer can use them for coverage. **This spec does not implement the misconception-coverage selection logic** (the per-misconception counters, opportunistic pick, and backfill); that is a separate design that depends on the coverage audit. This spec only makes the tags available. The `QuestionPick` dataclass gains an optional field carrying the 11 tags (or the pool exposes a `misconceptions_for_item(item)` accessor); choose whichever fits the interface with least disruption, keeping the existing three fields intact.

### 7.4 Interface stability

Do not change `pick_question_for_skill`'s signature. `QuestionPick`'s existing three fields (`question_id`, `slip_override`, `guess_override`) stay; `question_id` now carries the tenant-resolved `question_x_id`. Any misconception data rides as an added optional field with a default, so existing call sites and tests do not break.

---

## 8. Test cases

1. **`item`-key parity with calibration.** Every active question's constructed `item` matches a `question_parameters.csv` row, or is explicitly logged uncalibrated. Zero silent misses. Includes division: the seventh field is present on division keys and absent on non-division keys, and each of the eight former split operands joins to its single `|False` calibration row. (The bank currently holds no two-format division pair; if one is reintroduced, the two formats must produce two distinct keys that each join to their own calibration row - keep that as the regression intent.)
2. **Misconception parity (the big one).** Derived 11 flags reproduce workbook columns AQ-BA for all 8,605 rows (Section 5.5).
3. **Borrow cascade.** `6006 - 97` yields `x_minus_x = 1` (tens column 9-9 after cascade). `52 - 5` yields the expected per-column flags. Single-digit `class-one` subtraction yields `zero_minus_x = 0`.
4. **Division parsing.** A `{"quotient":162,"remainder":0}` answer yields quotient 162; division misconceptions key off the quotient; bare-number answers parse as quotient with no remainder.
5. **Per-tenant resolution.** A chosen `item` returns the session tenant's `question_x_id`; a multi-`question_x_id` `item` applies the entry > dlg > `_b` > lexicographic precedence deterministically. Include an `entry`-variant case (expect the `entry` id), a per-grade `_dlg` `_b` family (expect the lowest-numbered available `_dlg` `_b` id, not necessarily `_dlg1`), and a no-`entry`/no-`dlg` group (expect the `_b`/lexicographic fallback).
6. **Retired-list, `item` scope.** A retired `item` is never selected in any tenant, yet its row remains in `question_parameters.csv` (calibration intact). The 18 current retirements are all excluded.
7. **Retired-list, `question_x_id` scope.** A retired instance is excluded; if its `item` has other instances, the `item` stays selectable via the tiebreak; if not, the `item` drops out.
8. **Coverage guard.** Retiring all questions for a skill in a tenant surfaces a `NO_QUESTION_FOR_SKILL`-style signal, not a silent empty.
9. **No selection regression.** With an empty retired-list and a single tenant, the pool's selections match the pre-change `CsvQuestionPool` (the window logic is untouched).

## 9. What this spec deliberately leaves out

- **Misconception-coverage selection** (counters, opportunistic pick, backfill, the per-grade reserve). Depends on the coverage audit; separate design.
- **The offline-tree generator.** Separate spec; it consumes this build step's output (the lookup, tags, and retired-filtered pool) and must use the deterministic pick.
- **Any change to calibration, priors, lattice, or anchors.** None are touched by anything here.
