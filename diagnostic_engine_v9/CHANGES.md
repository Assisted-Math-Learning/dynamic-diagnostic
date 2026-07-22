# CHANGES.md

This document summarises the changes from the initial prototype delivery (`diagnostic_engine.zip`, 368 tests) to this revised delivery (`diagnostic_engine_v2.zip`, 494 tests). Each change in the fix-pack section corresponds to a numbered item in the `prototype_fix_pack_handover.md` review document; later sections cover work done after the fix pack.

Test count progression: 368 baseline → 457 (fix pack #1-#10) → 465 (cleanup metrics) → 494 (CsvQuestionPool) → 501 (per-tenant lookup) → 504 (misconception tags carried) → 506 (tag accessor). All passing. Smoke test passes for all four grades (G2, G3, G4, G5).

## Offline-tree runtime wiring (B1) and raw-response persistence (B2)

Test count: 597 -> 623 (all passing; +26 new). **Engine version stays 0.9.0** by
decision: both features complete already-scoped v9 work (the offline path and the
response-fetch dependency are named in the v9 docs), so this is v9-scope
completion rather than a new release. Note for the record: B2 adds a
backward-compatible optional request field plus a new read-only endpoint, which
under strict semantic versioning (MAJOR.MINOR.PATCH) would normally be a MINOR
bump (0.10.0); the semver-correct alternative was surfaced and the release was
kept at 0.9.0 deliberately, not by oversight. No mastery verdict, calibration
value, or other measured v9 number changed, and the v9 comparison simulation was
not re-run.

**B1 - offline_tree runtime wiring.** `session/start` now populates the
`offline_tree` field, previously always null, with a small REFERENCE (not the
inlined tree) to the precomputed offline decision tree for the session's
(tenant, resolved-grade): `{available, grade, engine_version, size_bytes,
sha256, fetch_path}`. The tree itself is served by a new endpoint,
`GET /api/v1/diagnostic/offline-tree/{tenant}/{grade}` (same
X-Internal-Service-Token model), because the deserialized G5 tree is ~24.8 MB of
JSON and inlining it into every start response was untenable. Grade resolution
mirrors the online engine (`config.get_engine_params`): G2-G4 serve their own
tree, G5-G8 fall back to the G5 tree, below G2 has none; a tenant with no shipped
artifacts (every non-Delhi tenant today) has none. Missing tree, unsupported
grade, non-Delhi tenant, or engine-version drift all yield `offline_tree: null`
and HTTP 200 - offline is a fallback and must never break an online session, so
`session/start` never raises `NO_TREE_FOR_GRADE`. That error is now a 404 that
lives ONLY on the fetch endpoint (it was previously defined-but-unraised dead
code mapped to 500). On version drift the stale tree is not served (null + a WARN
log). Trees are loaded once at startup from a configurable artifact directory
(`OFFLINE_ARTIFACT_DIR` env / `offline_artifact_dir` create_app arg, default
repo-relative `artifact/`, no /mnt dependency); the precomputed artifact is
served as-is, never recomputed per request. The reference's `size_bytes` and
`sha256` describe exactly the canonical JSON bytes the fetch endpoint returns.

**B2 - raw-response persistence + response-fetch endpoint (spec section 8.4
to-build item).** The response request gained an optional, nullable
`raw_response` (the learner's typed answer) for Stage B misconception
classification. It is deliberately declared so it is allow-listed past the
`extra='forbid'` PII guard, but it is NEVER consumed by mastery (`is_correct`
remains the only mastery input) and NEVER written to logs (it is not in the
logging allow-list, which is default-deny, so the filter drops it). A response
without `raw_response` succeeds and produces a verdict unchanged. The raw answer
is persisted on the session's `question_history` entry and returned by a new
read-only endpoint, `GET /api/v1/diagnostic/session/{sub_session_id}/responses`
(same X-Internal-Service-Token model, tenant resolved from the session), which
returns `{sub_session_id, learner_id, grade, responses: [{question_x_id,
raw_response, is_correct, skill_id}]}`. The Stage B glue's `raw_response_of`
injection point is kept, but its default now reads the persisted raw answers off
the session rather than a stand-in; the integration test persists real answers
and no longer injects a placeholder. External note: AML actually sending the raw
answer on each response is a separate integration and remains an open external
confirmation - only the engine contract (accept, store, expose) is built here.



**What:** `CsvQuestionPool` can now consume `tenant_question_lookup.csv` (built offline by `build_question_lookup.py`), which maps each `(tenant, item)` to one resolved `question_x_id` (variant precedence: entry, then dlg, then _b, then lexicographic tiebreak applied at build time) and carries the 11 misconception flags. Two new optional constructor params: `lookup_path` and `retired_path`. When `lookup_path` is unset the pool behaves exactly as before (params `q_x_id`, tenant ignored), so all prior tests are unaffected; this is why the legacy path is preserved rather than replaced.

**Tenant-aware selection (spec section 7.2):** when a lookup is supplied, the retired-list and tenant-availability filters are applied at ENUMERATION (before the discrimination window), so the window only ever sees items the tenant can serve and that are not retired. `NO_QUESTION_FOR_SKILL` then fires only on the genuine coverage gap (no tenant-available, non-retired calibrated question for the skill), not on the incidental case of the window landing on a tenant-missing item. The chosen item resolves to the tenant lookup's `question_x_id`; `slip`/`guess` still come from the (Delhi-derived, tenant-agnostic) calibration row. No-repeat recognises lookup-served ids. Tenant coverage is uneven (Delhi carries 613 of 638 calibrated items; the other three tenants all 638), which is the reason the filter moved to enumeration.

**Wiring:** `create_app_from_env` reads optional `TENANT_QUESTION_LOOKUP_PATH` and `RETIRED_LIST_PATH` env vars. The smoke gained `--lookup` and `--tenant` (default Delhi); `scripts/smoke.py --seed 42 --lookup tenant_question_lookup.csv --tenant Delhi` reproduces the same verdict distribution as the legacy seeded run (served ids differ; calibration is unchanged). 7 new pool tests cover tenant resolution, the availability filter, the coverage-gap error, no-repeat on served ids, and both retired scopes.

**Misconception tags carried (spec 7.3-7.4):** `QuestionPick` gained a fourth, optional field `misconceptions` (tag name -> 0/1), defaulting to None so the existing three fields and all prior call sites are untouched. In tenant-aware mode the pool reads the 11 flag columns from the lookup and attaches the chosen item's tags to the returned pick; in legacy mode the field is None. The engine does not act on the tags yet (the misconception-coverage selection layer is a separate design); this only makes them available. The `pick_question_for_skill` step-number comments were also realigned to the spec's 1-to-8 sequence (a duplicated label and a sequence jump from the earlier filter insertion); comment-only, no logic change. A `misconceptions_for_item(item)` accessor reads through the same item-keyed table, so a caller (diagnostics, logging, or a future coverage layer running outside the pool) can inspect tags for candidates the pool did not pick; flags are tenant-invariant per item (verified), with a load-time consistency check. 5 new tests cover the carried tags, the legacy None case, `QuestionPick` field stability, and the accessor (including unpicked items and unknown/legacy None).

## CsvQuestionPool: production question pool (post-priors-swap)

**What:** Replaced the default question source with `CsvQuestionPool`, a drop-in implementation of the existing `QuestionPool` interface that reads `question_parameters.csv` (the calibration output) and returns a real question id (`q_x_id`) plus that question's calibrated `slip` and `guess`. The engine's Bayes update now uses per-item calibrated values where the placeholder `StubQuestionPool` previously supplied none.

**Selection rule (spec section 5):** For a chosen skill, enumerate its distinct items, drop any already asked this session (matched on the `item` content key, not `q_x_id`), resolve each item's parameters at the learner's grade (grade-specific row if present, else the `all` row), keep items whose discrimination is within `window_width` (default 0.10) of the best and at or above `discrimination_floor` (default 0.50), then pick one uniformly at random. A `selection="deterministic"` mode (highest discrimination, lexicographic `item` tiebreak) is implemented as the hook the future offline-tree generator will use; production uses `"random"`. An optional `seed` makes the random pick reproducible for tests.

**Data verification:** Against the real `question_parameters.csv`: 638 distinct questions across the exact 39 engine scope skills (no missing, no extra), 10-26 questions per skill, every item has an `all` row so grade-2 fallback always resolves, and across all 273 (skill, grade) combinations the window plus floor never empties a non-empty skill. One spec claim was corrected: discrimination ranges 0.4789-0.9384 (not 0.542-0.93), so the 0.50 floor does bind, but only on 2 `Fib` items at grade 5 and never to the point of emptying a skill.

**Wiring:** `create_app_from_env` builds `CsvQuestionPool` from `QUESTION_PARAMETERS_PATH` (default `/etc/engine/question_parameters.csv`) and passes the config's scope skills as `expected_skills`, so a scope skill with zero questions logs a loud startup WARNING (mirrors the priors-coverage warning). `StubQuestionPool` stays the `create_app` default for unit tests. No routing, schema, or verdict changes.

**Tests:** +29 (27 in `tests/test_question_pool.py` covering enumeration, no-repeat keyed on item, the window rule including weak-tail exclusion and floor, grade-row-then-`all` fallback, the `NoQuestionForSkillError` paths, seed reproducibility, deterministic mode, and the scope-coverage warning; plus 2 end-to-end tests in `tests/test_api.py` confirming a calibrated slip/guess reaches the Bayes update and the factory builds the CSV pool with the scope warning). Two existing `create_app_from_env` tests were updated to provide `QUESTION_PARAMETERS_PATH`.

**Smoke:** Now uses `CsvQuestionPool` against the real file; all four grades pass with real `q_x_id`s. The verdict distribution shifts versus the stub-pool run (more `confident_mastered`) because real calibrated slip/guess are often sharper than the uniform 0.10/0.15 defaults, so correct answers move the posterior faster. Selection is random, so an unseeded run varies by a skill or two between runs (matching production); the smoke takes an optional `--seed` for a reproducible run. Reference distribution (`scripts/smoke.py --seed 42`): G2 8m+4u, G3 15m+6u, G4 23m+1nm+6u, G5 29m+1nm+9u.

**Out of scope (unchanged, per spec section 9):** the offline-tree generator, discrimination-weighted routing, online top-k variety, and a live `questions`-collection pool. `CsvQuestionPool` is the interim production pool until the collection-backed pool exists.

## Cleanup metrics wiring (post-fix-pack)

`run_cleanup` now takes an optional `EngineMetrics` and increments `diagnostic_cleanup_job_runs_total{outcome}` (success/error per run) and `diagnostic_cleanup_job_recovered_sessions_total` (by recovered count); these counters were previously defined but never incremented. The `cleanup` CLI builds a fresh registry, passes it in, and pushes to a Prometheus Pushgateway when `PROMETHEUS_PUSHGATEWAY_URL` is set (a one-shot CronJob process can't be scraped directly); when unset it logs a note and the counts remain in the summary log. Push failures are logged at WARN and never change the exit code. +8 tests.

## Critical fix: priors data source (post-#10)

**Problem:** The smoke test with the all-correct policy returned 7/21/30/39 confident-only verdicts for G2/G3/G4/G5 — the engine was declaring every skill mastered without asking real questions, because the input priors were uniformly above 0.95 and Rule 2 (priors-only resolution) fired on almost every skill.

**Root cause (data, not code):** `priors_table.csv` was computed from MainD response data — a selection-biased subset of learners who had already progressed past each skill — rather than from the raw Delhi diagnostic response population. G3 mean p_mastered in that file was 0.965; sample sizes varied wildly (n=3 for hard skills, n=1000+ for foundational ones); and there was no G2 data at all.

**Fix:** Repointed the priors loader at `priors_table_delhi_only.csv`, derived from the raw Delhi diagnostic response population (n_DL ≥ 130 per skill). The new file has:
- 48 rows across G2-G5 (G2: 6 skills, G3: 10, G4: 14, G5: 18)
- Per-grade means: G2 0.62, G3 0.42, G4 0.38, G5 0.38
- Zero skills at p ≥ 0.95

**Verification:**
- `simulate-session --policy by-prior --grade 3` now produces a properly mixed distribution: 32 questions → 4 confident_mastered + 14 confident_not_mastered + 3 uncertain.
- Smoke (all-correct policy) at the time of this change still used the placeholder `StubQuestionPool`, so its exact verdict counts are superseded by the later CsvQuestionPool run (see the "Smoke test output" section at the end of this document for the current authoritative numbers). The point that mattered then and still holds: the priors swap produced a genuinely mixed distribution instead of all-mastered, and the G4/G5 `confident_not_mastered` entries are real signal, since the Division skills `4D by 1D ...` and `2D/3D/4D/5D by 2D ...` have Delhi p_mastered ≈ 0.085 (below the 0.10 not_mastered threshold), hitting Rule 7 priors-only.

**Files touched:** `scripts/smoke.py` (default priors filename), `engine/cli.py` (--priors help text), `engine/cli_io.py` (load_priors docstring), `tests/test_cli.py` (test fixture filenames), README §2 (seed-config example), README §4 (missing-priors-handling subsection rewritten), README §6 (production-checklist item #7 rewritten), README §10 (smoke output table added). No engine code, schema, or test logic changes. 457 tests still pass.

**Coverage gap to be aware of:** the Delhi diagnostic tested about half of the in-scope skills per grade. Untested skills (e.g. "Repeated addition", "Tables 1 to 9", "3-digit Addition without carry" at G3) fall back to the engine's 0.5 default prior. This is expected behaviour and the engine handles it correctly; it is NOT caught by the existing missing-priors WARN logic, which only fires for grades with zero priors at all (no grade hits that under the Delhi-only file). Partial-coverage gaps are a content-team coverage question, not a deployment blocker.

---

## Change 1 — MongoDB env var bridge (CRITICAL)

**Problem:** `get_storage_backend()` accepted `mongo_url` and `database_name` as kwargs but did not read the `MONGODB_URL` / `MONGODB_DATABASE` environment variables. Starting the engine in MongoDB mode without explicit kwargs produced a confusing `TypeError`.

**Fix:** `engine/storage/__init__.py:get_storage_backend` now uses `setdefault` to bridge `MONGODB_URL` → `mongo_url` and `MONGODB_DATABASE` → `database_name` when the kwargs are absent. Raises a clean `ValueError("STORAGE_BACKEND=mongodb requires the MONGODB_URL env var ...")` when neither the kwarg nor the env var is set. Explicit kwargs win over env vars. 4 new tests in `TestStorageFactory`. README env-var table corrected (`MONGODB_DATABASE` default is now `aml_engine`).

## Change 2 — Missing-priors WARN, /health field, and STRICT_PRIORS_REQUIRED

**Problem:** A configured grade with no priors silently falls back to a default 0.5 prior for every skill. Safe for testing, but a hidden behaviour change in production. The canonical `priors_table.csv` has no G2 priors, so this silent fallback is live today for any G2 deployment.

**Fix:** New pure function `engine.config.check_priors_coverage(config) -> List[int]` returns the sorted list of configured grades with empty priors. `create_app` always calls it, stores the list on `app.state.priors_missing_for_grades`, and logs one WARN per missing grade. `/health` exposes the field. `create_app_from_env` reads the new `STRICT_PRIORS_REQUIRED` env var (default `false`); when `true` and the list is non-empty, startup raises `RuntimeError` before app construction. Verified against real `priors_table.csv` (G2 surfaces correctly). 11 new tests.

## Change 3 — QuestionPool interface, per-item calibration, and NO_QUESTION_FOR_SKILL

**Problem:** The pool interface (`pick_question_id(skill, session) -> str`) was thin and didn't accommodate spec section 6.2.1's optional per-item calibrated `slip_i` / `guess_i`. The spec section 7.8 failure mode (`NO_QUESTION_FOR_SKILL` when the candidate pool is empty) had no error code.

**Fix:** New `QuestionPick` frozen dataclass carries `question_id` + optional `slip_override` / `guess_override`. Method renamed `pick_question_for_skill(*, skill, session, grade, tenant_id)` with kwargs matching spec section 7.8. `NoQuestionForSkillError` added (HTTP 500). `record_response` accepts `slip_override` / `guess_override` kwargs; uses them in the Bayes update when non-None, falls back to `params.slip` / `params.guess` otherwise.

Threading: the route handler picks the next question, gets back a `QuestionPick`, and stashes its overrides on the session in three new optional fields (`pending_question_id`, `pending_question_slip_override`, `pending_question_guess_override`). When the matching `/response` arrives, the handler reads them, passes them to `record_response`, and `record_response` clears them after applying. Idempotent replays don't clear; they short-circuit before the clear step. The `pending_question` sub-object is also persisted in MongoDB so calibration survives pod restarts (a minor extension of the spec section 6.1 schema, flagged for awareness).

15 new tests across session-level Bayes math (hand-computed `0.857` default → `0.951` with both overrides), end-to-end API plumbing, and storage round-trip. Stub pool documented as always returning None overrides; real implementations must raise `NoQuestionForSkillError` on empty pools.

## Change 4 — request_id middleware

**Problem:** `structlog` was configured with `merge_contextvars` and `request_id` in the PII allow-list, but no middleware ever bound `request_id` to contextvars. Logs were missing the field; clients couldn't correlate request lifecycles.

**Fix:** New `engine/api/middleware.py:RequestIdMiddleware` (Starlette `BaseHTTPMiddleware`). Reads `X-Request-Id` from the request or generates a UUID4. Binds to structlog contextvars via `bind_contextvars`; unbinds in `finally` so cleanup runs on exception paths. Echoes the id back on the response. 5 new tests including a route-handler inspection that confirms the contextvar is set during request handling. Verified end-to-end on the real app (both passthrough and UUID-generation paths).

## Change 5 — Cleanup CLI subcommand and CronJob documentation

**Problem:** The storage layer had `find_complete_sessions_without_verdicts` and the metrics layer had `cleanup_job_*` counters, but no actual cleanup function existed. Partial-write recovery (session marked complete, verdict insert crashed) was specified but unimplemented.

**Fix:** New `engine/cleanup.py` module with `run_cleanup()` function and `CleanupResult` dataclass. Query → per-session `compute_verdicts` → `save_verdicts`. Per-session failures logged at ERROR and counted; one bad session does not abort the run. New `python -m engine.cli cleanup --config FILE [--lattice FILE] [--storage BACKEND] [--limit N]` subcommand. Exit codes 0 / 1 / 2 documented. Idempotent on re-run. The cleanup CLI does NOT push Prometheus metrics (the counters live on `app.state.metrics` which is per-FastAPI-app; a standalone CronJob can't reach them); structured JSON logs are the summary instead. Future option: push to Prometheus Pushgateway.

README §7 gains a "Cleanup CronJob" subsection with Kubernetes YAML (`*/5 * * * *`, `concurrencyPolicy: Forbid`, shared ConfigMap for engine_config.yaml), manual-run example, exit codes, and operational notes. 15 new tests across the cleanup module and the CLI.

**Latent bug fixed:** `cmd_seed_lattice` had been calling `get_storage_backend(args.storage)` positionally since change #1 made `backend` keyword-only. Existing tests passed because they don't exercise `--storage`. Both `cmd_seed_lattice` and `cmd_cleanup` now use `get_storage_backend(backend=args.storage)` correctly.

## Change 6 — Verdict refinement (spec section 7.6 eight-rule table)

**Problem:** Old verdict logic downgraded EVERY skill with `direct_observations == 0` to `uncertain`, regardless of whether the skill was untouched (priors-only) or moved by lattice propagation (propagation-only). Spec section 7.6 separates these: priors-only skills earn `confident_mastered` / `confident_not_mastered` (Rules 2 and 7); propagation-only skills are still downgraded (Rules 3 and 8). The testing-summary evidence backing this is in Testing Summary §§4 and 9: priors are calibrated well enough to trust without verification, but lattice propagation is not.

**Fix:** `Session.propagation_updates_count: Dict[str, int]` field added; incremented in `record_response` for every skill in the `propagate()` return dict. `Verdict.propagation_updates` and `SkillVerdict.propagation_updates` fields added. `assign_verdict(posterior, direct_observations, mastery_threshold, not_mastered_threshold, propagation_updates=0)` rewritten for the eight-rule table. `compute_verdicts` reads from `session.propagation_updates_count` and passes through. `VerdictPayload.propagation_updates` added; `_verdict_to_payload` propagates it. Storage: `verdict_to_doc` / `doc_to_verdict` include the field; the per-skill posteriors sub-document includes `propagation_updates` per spec section 6.1.

**Headline behavioural shift** in the G3 smoke (all-correct policy): pre-change `7 mastered + 14 uncertain` → post-change `21 confident_mastered`. All 14 previously-downgraded skills are priors-only with priors already ≥ 0.95 (the no-overshoot rule in `_push_up` prevents propagation from moving them, so they stay priors-only). G2 retains a mixed distribution (`7 + 5`) because G2 priors are the default-0.5 fallback. README §8 verdict table rewritten with all 8 rules + the mechanism explanation citing Testing Summary §§4 and 9. 37 new and rewritten tests.

## Change 7 — Grade schema tightened to 2-8

**Problem:** `SessionStartRequest.grade` accepted `1-12`, beyond spec section 2's supported range of 2-8 (2-5 explicitly configured, 6-8 fall back to G5).

**Fix:** `ge=1, le=12` → `ge=2, le=8`. The existing Pydantic-to-`INVALID_GRADE` exception handler keeps the API envelope (400 + `INVALID_GRADE`) identical regardless of whether rejection happens at Pydantic or engine layer. No client-visible behaviour change beyond the error message text. Single `grade=99` test replaced with 12 parametrized cases covering both boundaries.

## Change 8 — Duplicate /health route removed

**Problem:** `/health` was registered on both the prefixed router (`/api/v1/diagnostic/health`) and the flat router (bare `/health`). The flat one delegated to the prefixed one.

**Fix:** Prefixed registration removed. Implementation moved directly onto the flat router. The bare `/health` is now the single source for Kubernetes probes and operational tooling. README already referenced bare `/health` only; one test inverted (`test_health_on_prefixed_path_also_works` → `test_health_not_exposed_on_prefixed_path`, asserts 404).

## Change 9 — README §8 verdict table

Done as part of change #6. The README's verdict section was rewritten with the full 8-rule table and a mechanism explanation citing Testing Summary §§4 and 9.

## Change 10 (optional) — last_updated_at walks question_history

**Problem:** `session_to_doc` used `session.started_at` as the `last_updated_at` for every skill, regardless of when the skill was actually asked.

**Fix:** Single pass over `session.question_history` builds a `{skill_id: most_recent_asked_at}` lookup. `posteriors_nested` uses it, falling back to `session.started_at` for skills never directly asked (their posterior is either still at the cohort prior or was moved by lattice propagation; propagation events do not have timestamps in the session state, documented as a known limitation in the code comment). 6 new tests (3 cases × 2 storage backends).

## Change 11 (optional) — $lookup aggregation — SKIPPED

The fix pack flagged this as "skip if mongomock breaks". The N+1 query pattern in `find_complete_sessions_without_verdicts` is acceptable because the cleanup CronJob runs every 5 minutes against a typically-small backlog. The optimisation can land in a follow-on change if production traffic indicates it matters. Tracked as a known limitation in README §9.

## Change 12 — Spec section 16 surfaced in README

**Problem:** Spec section 16 enumerates 19 pending engineering decisions where the spec has assumed defaults. These need triage before the pilot promotes to GA but were not visible in the prototype README.

**Fix:** New "Pending engineering decisions (spec section 16)" subsection in README §6, grouped by category (Operational / Performance / Naming / Question pool & content team) for actionability. Spec item numbers preserved as the table's first column for traceability. Items 16-19 (content team coordination) are flagged as interacting with the per-item-overrides plumbing now in place from change #3 — the engine is ready to consume calibrated `slip_i` / `guess_i` the moment the content team or calibration pipeline starts populating them.

Existing §6 deployment checklist refreshed: items #5 (request_id middleware) and #6 (cleanup job scheduler) removed (changes #4 and #5 resolved them). New item #7 added: set `STRICT_PRIORS_REQUIRED=true` in production. §9 Known limitations list pruned (`last_updated_at` placeholder and cleanup-scheduler entries removed).

## Tests passing

```
$ python -m pytest tests/
494 passed
```

## Smoke test output (all 4 grades, Delhi-only priors + CsvQuestionPool)

The smoke uses the `all-correct` policy and the real `CsvQuestionPool`. Selection is random, so an unseeded run (the default, matching production) varies by a skill or two between runs. The numbers below are the reproducible reference run, `scripts/smoke.py --seed 42`:

```
G2:  8 confident_mastered + 4 uncertain
G3: 15 confident_mastered + 6 uncertain
G4: 23 confident_mastered + 1 confident_not_mastered + 6 uncertain
G5: 29 confident_mastered + 1 confident_not_mastered + 9 uncertain
```

The mix reflects three distinct paths through the spec section 7.6 rules: skills directly tested and answered correctly land in `confident_mastered` via Rule 1; untested skills whose Delhi prior is already high enough pick up Rule 2; untested skills whose Delhi prior is at or below the 0.10 threshold (the G4/G5 `1`s are `4D by 1D ... Division` and `2D/3D/4D/5D by 2D ... Division`, p_mastered ≈ 0.085) pick up Rule 7 confident_not_mastered; untested skills with no Delhi data fall back to the engine's 0.5 default and land in Rule 4 uncertain + take_maind_confirmation. Counts are higher than an earlier stub-pool run because real calibrated slip/guess are often sharper than the uniform 0.10/0.15 defaults.

## Storage document schema changes worth knowing

`learner_diagnostic_sessions` documents gained two extensions beyond what the original spec section 6.1 listed:

- `pending_question` sub-object (change #3): engine-internal turn-state for per-item calibration overrides. Cleared after the matching response is applied.
- `propagation_updates` per skill in the `posteriors` sub-document (change #6, required by the updated spec section 6.1).

`learner_skill_verdicts` documents gained:

- `propagation_updates` field (change #6, required by the updated spec section 6.1).

Existing readers of these documents that follow only the original spec will simply not see the new fields; reads via `doc_to_session` / `doc_to_verdict` are backwards compatible (missing fields map to defaults).

## Misconception-coverage layer — Checkpoint 1: session ledger + applicability

First of four checkpoints implementing the misconception-coverage selection spec. This checkpoint adds the state and the applicability computation only; the ledger is populated but not yet acted on (no opportunistic pick, no backfill), so selection behaviour is unchanged — the prior test floor and the seeded tenant-aware smoke distribution are byte-identical.

- **`engine/misconception.py` (new):** the canonical 11-name `MISCONCEPTIONS` tuple, single source of truth for the ledger, the pool, and storage.
- **`Session` ledger (`engine/session.py`):** `misconception_asked` / `misconception_correct` (per-tag counts, initialised to zero for all 11 at session start) and `misconception_applicable` (the set the pool can serve, fixed at session start). A `pending_question_misconceptions` field carries the chosen question's tags alongside the existing pending slip/guess stash. `record_response` updates the counters at answer-time (asked for every tag the answered question carries; correct only when right), reached only on a real non-replay update so each question counts once. Legacy mode (no tags) leaves the ledger untouched.
- **`CsvQuestionPool.applicable_misconceptions(tenant_id, grade, skills_in_scope)`:** returns the misconceptions the pool can actually serve, using the *identical* eligibility as `pick_question_for_skill` (in-scope skill, tenant-available, not retired, grade-resolvable by grade-row-else-`all`), so applicability equals coverability. Empty in legacy mode. Verified against real data: G2=7, G3=8, G4=11, G5=11, with G2 tenant-invariant — matching the coverage audit.
- **Storage round-trip (`engine/storage/documents.py`):** the ledger and pending tags serialise/deserialise so they survive the per-request session reload; pre-feature documents deserialise to an empty (inert) ledger.
- **Route glue (`engine/api/routes.py`):** `session_start` computes the applicable set from the pool; `_pick_question_and_stash` stashes the picked question's tags.

Test count: 506 → 520 (14 new in `tests/test_misconception_ledger.py`): the canonical list, synthetic applicability (scope/tenant/grade/legacy), answer-time counting (asked/correct/wrong-answer/no-tags/replay), storage round-trip and backward compatibility, plus two real-data checks (the 7/8/11/11 audit match and an end-to-end Delhi G3 session populating the persisted ledger). Full suite green; tenant-aware smoke unchanged across G2-G5.

## Misconception-coverage layer — Checkpoint 2: opportunistic pick

Adds the opportunistic preference inside `CsvQuestionPool.pick_question_for_skill` (spec section 5.1): among the discrimination-window survivors, prefer the candidate that advances the most still-unmet applicable misconceptions (greedy multi-tag), narrow to the sharpest among those, then let the existing mode make the final choice (random spreads exposure in production; deterministic is lexicographic for the offline tree).

Engagement is gated on `max_advance > 0` — the logic fires only when an in-window candidate actually advances an unmet applicable misconception. When nothing can be advanced (no applicable misconceptions, all at target, or no in-window carrier), `candidates` stays the full window and the pick is byte-identical to before. `misconception_target` is a new pool constructor parameter (default 2); `<= 0` disables the preference.

Behaviour note: from this checkpoint selection genuinely changes when applicable misconceptions exist, so the seeded tenant-aware smoke distribution (and question count) differs from checkpoint 1 by design; it still completes for G2-G5. The pick never leaves the discrimination window, so mastery-measurement quality is unchanged. Measured opportunistic gain on a seeded Delhi G3 session: applicable misconceptions reaching the floor for free rose from 3/8 to 6/8.

Test count: 520 -> 528 (8 new in `tests/test_opportunistic_pick.py`): tagged-preferred in both modes, inert when met / when no applicable (exposure preserved), out-of-window carrier never chosen, greedy multi-tag, production exposure spread vs deterministic collapse (test case 12), and deterministic reproducibility. Full suite green.

## Misconception-coverage layer — Checkpoint 3a: backfill selection primitive

Adds `CsvQuestionPool.backfill_pick(tenant_id, grade, skills_in_scope, session, needed)`: a skill-agnostic primitive that returns the not-yet-asked, eligible question across the in-scope skills advancing the most of the supplied `needed` misconception set (greedy multi-tag), tiebroken by sharpest then the mode-appropriate final pick, or None when nothing eligible carries a needed tag (shortfall). Pure selection only; the pass-A/pass-B orchestration and reserve accounting come in checkpoint 3b and call this same primitive.

Unlike the opportunistic pick, backfill ignores the discrimination window and floor (its job is coverage from a separate reserve; the sharpest tiebreak still favours the better question, and a sub-floor carrier is served only when it is the sole carrier of a needed misconception). Eligibility otherwise matches selection exactly (tenant-available, not retired, grade-resolvable, session-wide no-repeat).

Refactor: extracted three shared helpers (`_final_pick`, `_narrow_to_sharpest`, `_build_pick`) now used by both the window pick and backfill so their mode-pick / sharpest / resolution logic cannot diverge; verified byte-identical (window pick and seeded smoke unchanged).

Test count: 528 -> 536 (8 new in `tests/test_backfill_pick.py`): greedy multi-tag, skill-agnostic selection, session-wide no-repeat, None-on-shortfall, floor-ignored-for-coverage, sharpest tiebreak, exposure spread vs deterministic collapse, and tag/override carrying. Full suite green.

## Misconception-coverage layer — Checkpoint 3b-i: budget plumbing + Phase-3 helper

Plumbing for the phase controller (the controller and route wiring follow in 3b-ii/3b-iii):
- `GradeBudget.reserve_size` (default 0) and `EngineParams.reserve_size` / `.adaptive_budget` (= total - reserve). Reserve 0 keeps the layer inert (Phase 1 = full budget), so existing configs are unchanged.
- `EngineParams.misconception_conditional_extra` (default 1).
- `CsvQuestionPool.misconception_target` property (read by the controller for the pass-A floor).
- `routing.select_leftover_skill(state, config, lattice, candidate_skills)`: additive Phase-3 selector returning the highest info-gain skill among the supplied still-unsure candidates, per-operation caps and walk order ignored. `pick_next_question` never calls it, so the online walk and offline tree are byte-identical.

Test count: 536 -> 542 (6 new in `tests/test_coverage_phases.py`): adaptive_budget plumbing and the leftover selector (picks an unsure skill, None when all resolved, ignores per-op caps, restricts to the candidate set). Full suite green.

## Misconception-coverage layer — Checkpoint 3b-ii: phase controller

Adds `engine/coverage.py: select_next_coverage(session, params, pool)` - the orchestration sequencing Phase 1 (adaptive under the lowered total stop), Phase 2 (backfill pass A floor + pass B conditional extra), and Phase 3 (leftover-to-mastery, info-gain among unsure skills with caps lifted). Returns a uniform `(skill, QuestionPick)` across phases, or None when complete. Pure function of session state except it sets `Session.reserve_phase_started_at` once when Phase 1 ends (the reserve baseline / forfeit marker, persisted via storage).

Key behaviours: reserve accounting forfeits unspent adaptive budget and caps reserve spend at `reserve_size`; the Phase-1 config clamps per-op to the lowered total; pass B fires only on a genuine tie (`correct == wrong`) within `[target, target+extra)`; reserve exhaustion ends the session (remaining unmet -> shortfall); skill exhaustion is caught (Phase 1 ends, Phase 3 skips to the next info-gain skill). `reserve_size == 0` makes the whole controller inert. `backfill_pick` now returns `(skill, pick)`.

NOT yet wired into the request path - that is checkpoint 3b-iii (the route integration with end-to-end tests). The controller is exercised directly here.

Test count: 542 -> 550 (8 new controller tests in `tests/test_coverage_phases.py`): Phase 1 pick, Phase-1-end marker, reserve-0 inert, pass A to floor, pass B tie-only, reserve exhaustion, Phase 3 leftover, all-resolved completion. Full suite green.

## Misconception-coverage layer — Checkpoint 3b-iii: route wiring

Wires the phase controller into the live request path. `record_response` gains an opt-in `defer_next` (mutate-only; no next/finalize) used by the route; `finalize_session` is extracted as a shared finalizer; `Session.pending_question_skill_id` is added (persisted) so replay can re-serve the pending question and so skill-agnostic backfill picks carry their skill. The route now: applies the answer (defer_next=True), then on replay re-serves the stashed pending question (idempotent, controller not re-run), else runs `select_next_coverage` -> stashes the resolved `(skill, pick)` directly (via the new `_stash_resolved`, not a re-pick) or finalizes when the controller returns None.

reserve_size=0 (default) keeps the whole path byte-identical to the pre-coverage engine. With the reserve enabled, the controller drives Phase 1 (lowered stop) -> Phase 2 backfill -> Phase 3 leftover end-to-end.

Tests: 550 -> 553. New `tests/test_coverage_e2e.py` (3 tests, skipped without /mnt/project + the tenant lookup) drives full HTTP sessions on real Delhi G3 data: (1) reserve=7 all-correct fires backfill (reserve_consumed>0) and brings all 8 applicable misconceptions to the floor within the 42 budget; (2) reserve=0 is inert end-to-end; (3) replay is idempotent. Smoke G2-G5 complete at 15/30/45/60 (unchanged). The output `misconception_signals` field is still pending (checkpoint 4).

## Misconception-coverage layer — Checkpoint 4: the misconception_signals output (LAYER COMPLETE)

Adds the per-misconception three-state triage signal (spec section 7) as a sibling to the verdicts array. `engine/misconception.py` gains the signal-state constants, a `MisconceptionSignal` dataclass, and the pure `derive_misconception_signals(session, *, misconception_target)`. `engine/api/schemas.py` gains `MisconceptionSignalPayload` and an optional `misconception_signals` field on `SessionResponseResult`, `SessionEndResult`, and `VerdictsResult`. The route emits it on session completion, on `/end`, and on `/verdicts` (the last derives it from the persisted session - no new storage).

State rule: applicable + wrong>correct -> likely_present; applicable + correct>wrong -> likely_absent; applicable + (tie or zero asks) -> unsure; otherwise not_applicable. Plus raw counts (asked/correct/wrong) and a derived shortfall flag (applicable but asked<target). The signal is a prior for MainD and never alters the mastery verdict. The field is None while a session continues; always 11 entries when present.

Tests: 553 -> 564. New `tests/test_misconception_signals.py` (10 pure-derivation tests: all four states, tie, zero-asks, shortfall derivation, the wrong=asked-correct invariant, target-0 no-shortfall, canonical 11-entry order). One new e2e test asserts the signal rides on the complete response and on `/verdicts`, with applicable/not_applicable consistency. Verified on real Delhi G3: 8 applicable misconceptions carry real states, the 3 division-deep ones report not_applicable.

This completes the misconception-coverage selection layer (opportunistic pick + backfill + phase controller + route wiring + signal output). Deferred follow-ups: the reserve_size trade-off simulation (spec section 8), Phase 3 proportional ordering validation, and the Option 1 offline decision tree (which must encode the misconception counters + conditional-extra branching).

## v6 -> v7: misconception verdict rule (accuracy-banded backfill)

Replaces the misconception verdict semantics. `derive_misconception_signals` now uses an accuracy band on correct/asked over all tagged asks (>=0.75 likely_absent, <0.50 likely_present, else unsure; below-target forces unsure). The backfill "pass B" tie-trigger is replaced by a reachability gate: at/above the floor, ask one more iff not yet cleared (acc<0.75) and 0.75 still reachable within cap=target+x. Both are shared pure functions (`misconception_verdict`, `wants_misconception_extra`) so controller and verdict cannot drift; thresholds are named constants (0.75 clear, 0.50 present). Default `misconception_conditional_extra` 1->2. The `shortfall` field is removed from the signal dataclass and the API payload (shortfall == unsure now). Engine version 0.1.0 -> 0.7.0.

Tests: 564 -> 576 (new test_verdict_rule_v7.py with the spec's 12 cases; test_misconception_signals rewritten for bands; pass-B controller test rewritten for the gate). Unit-level Monte Carlo reproduces the spec Section 7 (false-clear ~halved). System harness at production reserves confirms budget never exceeded. NOTE: the v6 reserve-size recommendations are stale for misconception coverage under v7 and need re-deriving.

## v7 follow-up: misconception parameters config-plumbed
Added a `misconception` config block (target 2, conditional_extra 2, clear_threshold 0.75, present_threshold 0.50) so all four are deployment-tunable via engine_config.yaml + get_engine_params, replacing the EngineParams/pool defaults and module-constant-only path. The shared verdict/gate functions take threshold args defaulting to the constants (direct calls unchanged). reserve_size set to 25% (7/11/15/19) in config. Tests 576 -> 583 (target=3 switch + threshold-tunability). Engine behaviour at defaults is byte-identical.

## v9 integration branch: version bump, wire field rename, portable test paths

Four changes on the v9 integration branch: three code-and-test changes (version, wire field, test paths) plus the entry-preferring lookup regeneration. Tests: 596 -> 597 (one new end-to-end version-stamp test; the rest are expectation updates, not new coverage).

**Engine version 0.9.0 (P0-1).** Three sources previously disagreed and none read 0.9.0, so a verdict with no `ENGINE_VERSION` override was stamped 0.8.0 (from `engine/__init__.py`) while the docs and Appendix E expected 0.9.0. All three are now 0.9.0: `pyproject.toml` `version` (was 0.1.0), `engine/__init__.py` `__version__` (was 0.8.0), and `config/engine_config.yaml` `version` (was 0.1.0). `ENGINE_VERSION` still defaults to `engine.__version__`, so a session started with no override now stamps 0.9.0. New test `test_verdict_end_to_end_carries_default_engine_version` builds the app with the default version, drives a session to completion, and asserts the stored session (which produces the verdicts) carries `engine_version == "0.9.0"`.

**Wire field rename `question_id` -> `question_x_id` (P0-2/P0-4).** The two integrator-facing schema fields carried a `question_x_id` value under the name `question_id` (set from `QuestionPick(question_id=q_x_id, ...)`; `QuestionRef` documents "x_id plus the canonical skill"). Renamed to make the wire contract honest, match the spec, and disambiguate from AML's own `question_id` in `learner_proficiency_question_level_data`. Changed only the wire schemas and their direct references: `SessionResponseRequest.question_id` and `QuestionRef.question_id` in `engine/api/schemas.py`, and the `body.question_id` reads plus the `QuestionRef(question_id=...)` constructions in `engine/api/routes.py`. Internal names are unchanged (`Session.pending_question_id`, `QuestionPick.question_id`, `record_response(question_id=...)`, `question_pool` internals, and stored-document fields), and no stored `question_id` is echoed onto a wire response, so nothing there needed renaming. This is a wire-contract rename, not a semantic change. The OpenAPI schema now shows `question_x_id` in both the `SessionResponse` request and the question-reference response; test payloads and response assertions were updated accordingly.

**Portable real-data test paths (P2-4).** The real-data tests hardcoded absolute paths (`/mnt/project/...`, `/mnt/user-data/outputs/...`), so a clean checkout needed a manual diff to pass. `tests/__init__.py` now exposes `DATA_DIR`, resolved from the `AML_TEST_DATA_DIR` environment variable with a repo-relative default of `data/`; `tests/conftest.py` adds a matching `data_dir` fixture. The affected tests (`test_cli.py`, `test_cli_io.py`, `test_question_pool.py`, `test_misconception_ledger.py`, `test_coverage_e2e.py`, `test_stage_b_integration.py`) read `DATA_DIR` instead of `/mnt`; `grep -rn "/mnt/" tests/` now returns nothing. The lookup-repoint diff was already folded into the source tree (the ledger and coverage-e2e tests read the engine's own `inputs/tenant_question_lookup_v2.csv` via `Path(__file__).resolve().parents[1]`), so there was no separate `.diff` file left to apply or delete. The full suite now runs green from a clean checkout with no manual step.

**Entry-preferring lookup tiebreak.** `inputs/tenant_question_lookup_v2.csv` was regenerated with a new variant tiebreak in the offline builder's `resolve_question_x_id`: from prefer-`_b`-then-lexicographic to variant precedence entry > dlg > `_b` > lexicographic. This is rendering-only: calibration is item-keyed (all display variants of an item share identical slip/guess), so verdicts, coverage, false-skip, and MainD savings are unchanged; only the concrete `question_x_id` served changes. Coverage is unchanged at 2,536 rows / 650 items, with zero dangling ids and zero content moved (every resolved id still maps to the same `item`). 47 rows changed resolution: Delhi `36|3` -> `q_dlg3_div_00611_b` (dlg tier), Karnataka `36|3` -> `q_entry_div_00611_b` (entry tier). Due-diligence flag recorded: of the 47 changed rows, 40 now resolve to questions whose Final QSet Purpose is "Entry Diagnostic" (a possible entry-test / main-diagnostic overlap); surfaced to the bank owner and retained. The suite stays green (no test asserts a specific `question_x_id`).
