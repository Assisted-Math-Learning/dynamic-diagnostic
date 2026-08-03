# AML Misconception Classifier - Runtime

Two scripts. **Script 1 (`aml_tag.py`)** tags each question with the misconception
codes that could fire on it and writes a versioned eligibility table. **Script 2
(`aml_classify.py`)** classifies a learner's responses against that table and
outputs a per-operation ranked `misconception_evidence_index`.

## When each runs

| | Script 1: `aml_tag.py` (tagger) | Script 2: `aml_classify.py` (runtime) |
|---|---|---|
| Job | Tag questions with reachable codes; fold in real misses | Classify a learner; aggregate to the evidence index |
| Run when | Rules change, new questions added, or pending log misses to fold | Every set of learner responses |
| Speed | Slow, one-time (multiplication-bound) | Fast (loads the table) |
| Dependencies | pandas, pyarrow | standard library only |

## The evidence index

```
index(code) = sum of the code's within-question scores over the learner's
              questions where it fired
              ----------------------------------------------------------
              learner's questions (same operation) where the code was ELIGIBLE
```

Eligibility = the precomputed table for the question's operands, UNION any code
that fired on the actual response (so the index can never exceed 1). It is a
bounded [0,1] proxy, not a calibrated probability.

## Script 1: the tagger

```
python aml_tag.py --questions delhi_question_list.parquet --mode all --mult-window fast
python aml_tag.py --mode log                 # fold pending log misses
python aml_tag.py --status                   # is a fold needed?
```

### Question input

A parquet or CSV with the seven-field identity key (eligibility is computed from
the last four; the rest are carried as labels):

`q_l1_skill | q_l2_5_skill | q_type | q_text | q_n1 | q_n2 | response_includes_remainder`

plus `question_id`. Only `q_type == "Fib"` rows are tagged. If
`response_includes_remainder` is absent it is derived from `q_correct_answer`
for division (JSON answer = remainder expected), null otherwise.

### Run modes

| Mode | Does |
|---|---|
| `all` | Re-probe every question; fold ALL log rows. Use after a rules change. |
| `new` | Probe only questions not already in the table; fold pending log rows into existing and new questions. |
| `log` | Fold pending log rows only; no probing. No-op (no new version) when nothing is pending. |

Fallbacks, announced at start: no table -> forced to `all`; table present but no
log + `new` -> probe new questions only; table present but no log + `log` ->
nothing to do.

### `--mult-window`

`fast` (±25, default) or `regular` (±200). Controls the dense probe window for
multiplications where both operands are multi-digit (each probe there costs
~50 ms). `regular` reduces but does not eliminate multiplication misses, and is
slower to tag. Affects the tagger only.

### Versioning and the pointer

Every run that changes the table writes a new file
`eligibility_table_<date>_v<n>.json` and updates the pointer
`eligibility_table_current.txt` to name it. Nothing is overwritten, so past
versions remain for reproducing past runs.

## Script 2: the runtime

```
python aml_classify.py input.json -o output.json --table-dir tables
python aml_classify.py input.json --table-dir tables --table-version 20260626_v2   # reproduce
cat input.json | python aml_classify.py --table-dir tables
```

It resolves the table once (via the pointer, or `--table-version` /
`--table-file`), stamps the version on the output, classifies each item,
aggregates, and **appends any fired code not in the table to `miss_log.csv`**.
The runtime only appends; it never edits the table or rewrites the log.

### Input JSON

```json
{
  "learner_id": "L123",
  "learner_grade": 3,
  "items": [
    {"operation": "addition", "n1": 1006, "n2": 2, "response": "1,008"},
    {"operation": "division", "n1": 400, "n2": 3, "response": "133 R 1",
     "system_expects_remainder": true}
  ]
}
```

`system_expects_remainder` (division only) is taken from the caller if present,
else inferred from the math. `learner_id` and `learner_grade` are collected once.

### Output JSON

Top level carries `eligibility_table_version`. Per operation: an `accuracy`
block, an `invalid_responses` block (the RANDOM_OR_INVALID code, reported
separately from the misconception ranking), and a `ranked` list sorted by
`misconception_evidence_index`. Codes that never fired are omitted. Malformed
items go to `errors`.

## The miss log lifecycle

1. Runtime appends `(question key, response, fired code)` to `miss_log.csv` for
   any fired code not in the table. Append-only, no locking needed.
2. `aml_tag.py` (any mode that folds) rotates `miss_log.csv` aside, deduplicates
   into `miss_log_master.csv` on `(operation, n1, n2, response_includes_remainder,
   response, code)` with a hit count and last-seen, and folds the codes into the
   table. Each consumed row is stamped with `folded_in_version` (null = pending).
3. `--status` reports the current version and how many rows are pending.
4. A logged response is, in effect, a probe result for its own question; it
   improves only that question's tags. Generalizing a response into a new probe
   *family* (to help other questions) is a manual analyst step, not automated.

Stale codes from old rules are harmless: an extra tag only widens the eligible
set, never corrupts it. The dedup key includes the code, so the same response can
keep both its old-rules and new-rules codes without re-running old responses.

## Off-table questions (side-cache)

A question whose `(operation, n1, n2, response_includes_remainder)` key is not in
the table is "off-table" - it was administered but never tagged. The runtime
handles it in three tiers: labelled table, then a side-cache, then inline
compute.

- The first time an off-table key appears, the runtime computes its eligibility
  inline (slow, especially multiplication) and writes it to
  `eligibility_sidecache.jsonl` (append-only, keyed by the operand key, no
  labels). Every later occurrence, even in a separate process, is an O(1)
  side-cache hit instead of a re-compute (measured: ~6.4 s first hit vs ~0.1 s
  cached for a hard multiplication).
- The side-cache is deterministic, so concurrent writes are last-write-wins and
  safe without locking. It is superseded automatically by a proper re-tag,
  because the labelled table is checked first.
- Every off-table key also raises a stderr warning and is recorded in
  `unknown_questions.csv`, so drift between the tagged set and the administered
  set is visible. The fix for drift is to add the question to the question list
  and re-run `aml_tag.py --mode new`.
- `--no-sidecache` disables reading and writing the side-cache.

The side-cache is a performance layer, not a source of truth: it carries no
labels and does not make pre-tagging optional. Tag the full administered set via
the question list; the side-cache only keeps the runtime fast if something slips
through untagged.

## Scope

Fib questions only (MCQ and Number-Sense are out of scope and not tagged).
Content class 1-5. Multiplication tagging is the slow step; the runtime is fast.

## Files

```
aml_tag.py                Script 1 (tagger).
aml_classify.py           Script 2 (runtime). Stdlib only.
aml_engine.py             Shared core: dispatch, probe generator, eligibility.
addition.py subtraction.py multiplication.py division.py utils.py  classifier modules.
delhi_question_list.parquet  example question input (467 questions, 432 Fib).
tables/                   built eligibility table + pointer (ready to use).
```
