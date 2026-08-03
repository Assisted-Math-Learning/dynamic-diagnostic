# AML Dynamic Diagnostic Engine

This is the production prototype for the AML (Adaptive Math Learning) dynamic diagnostic engine. The service maintains Bayesian posteriors over a learner's L2.5 math skills as they answer questions, picks the next question via lattice propagation and information-gain routing, and returns a three-band verdict (`confident_mastered` / `confident_not_mastered` / `uncertain`) per skill.

This README is written for the engineering team that will deploy and operate the service. Sections are ordered roughly by what you'll need first: install, run, configure, integrate, then deeper detail on internals.

---

## 1. What this delivers

| Component | Where |
|---|---|
| FastAPI service with 6 endpoints (3 POST + 3 GET) | `engine/api/` |
| Engine core: Bayesian update, lattice propagation, routing, verdict assignment | `engine/{bayes,lattice,routing,verdicts,session}.py` |
| Storage layer (pluggable in-memory + MongoDB backends) | `engine/storage/` |
| Configuration loader (Pydantic + YAML) | `engine/config.py` |
| Observability (structlog with PII filter + 12 Prometheus metrics) | `engine/observability/` |
| CLI for seeding the config, seeding the lattice, simulating sessions, and validating config | `engine/cli.py` |
| Dockerfile, smoke test, full test suite | `Dockerfile`, `scripts/smoke.py`, `tests/` |

**597 unit + integration tests pass.** Run `pytest` to confirm.

This delivers the dynamic diagnostic engine described in `dynamic_diagnostic_engine_spec.md`. The offline decision-tree path has shipped for Delhi G2-G5 (Section 11). The Numbers operation is intentionally excluded from scope (Section 9).

---

## 2. Quick start

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + tests + CLI loaders
```

Python 3.11 or higher.

### Run the test suite

```bash
pytest
# Expected: 597 passed
```

### Seed the engine configuration from canonical data

```bash
python -m engine.cli seed-config \
    --milestone-mapping /path/to/20260518_AML_Telangana_Milestone_and_Level_Mapping.csv \
    --priors            /path/to/priors_table_delhi_only.csv \
    --anchors           /path/to/anchor_recommendations_v3.xlsx \
    --output            config/engine_config.yaml
```

This produces a fully populated `engine_config.yaml` with the canonical Delhi-scope L2.5 skills (39; 40 across all tenants - the 40th, "1D - 1 to 4", is served in Karnataka/Private/Telangana, not Delhi), per-grade budgets, operation orders, anchors, and priors. The CLI prints warnings for any priors that reference skills not in the milestone mapping; these are informational and don't block the build.

The priors input must be the Delhi-only file (`priors_table_delhi_only.csv`). An earlier `priors_table.csv` derived from MainD response data is selection-biased (only learners who progressed past each skill contributed responses) and produces uniformly-high priors that make the engine declare almost every skill mastered without asking real questions. See CHANGES.md.

### Validate the configuration

```bash
python -m engine.cli validate-config --config config/engine_config.yaml
# /path/to/engine_config.yaml: valid
#   version          : 0.9.0
#   grades           : [2, 3, 4, 5]
#   skills           : 39          # Delhi scope; 40 across all tenants
#   ...
```

### Run the end-to-end smoke test

```bash
python scripts/smoke.py --data-dir /mnt/project --grade 3            # random run (default, legacy pool)
python scripts/smoke.py --data-dir /mnt/project --grade 3 --seed 42   # reproducible run
python scripts/smoke.py --data-dir /mnt/project --grade 3 --seed 42 \
    --lookup tenant_question_lookup.csv --tenant Delhi                # tenant-aware run
```

The `--lookup` form exercises the per-tenant pool: it resolves tenant-scoped `question_x_id`s and filters to items the tenant can serve. The Delhi seeded distribution matches the legacy seeded run (the served ids differ; the calibration that drives the verdicts is unchanged).

Drives a full session through the FastAPI app via `TestClient` (no uvicorn needed), prints a per-question trace and verdict summary, exits 0 on success.

The smoke uses the `all-correct` answer policy and the real `CsvQuestionPool` (so the question trace shows real `q_x_id`s and the Bayes update uses each question's calibrated slip/guess). Question selection is random, so an unseeded run (the default, matching production) varies by a skill or two between runs. Pass `--seed N` for a reproducible run. The reference distribution below is `scripts/smoke.py --seed 42`, with the Delhi-only priors in `priors_table_delhi_only.csv` and `question_parameters.csv`:

| Grade | confident_mastered | confident_not_mastered | uncertain |
|---|---:|---:|---:|
| G2 | 12 | 0 | 0 |
| G3 | 21 | 0 | 0 |
| G4 | 29 | 1 | 0 |
| G5 | 38 | 1 | 0 |

The mix reflects the all-correct policy at the seed-42 pick order: directly-tested skills answered correctly land in `confident_mastered` (Rule 1), and untested skills with high Delhi priors also land there (Rule 2, priors-only). The only exceptions are untested skills with a very low Delhi prior, which resolve to `confident_not_mastered` on priors alone (Rule 7): the single G4 and G5 `confident_not_mastered` are `4D by 1D with and without remainder` (Division, p_mastered ≈ 0.085) and `2D/3D/4D/5D by 2D with and without remainder` (Division, p_mastered ≈ 0.087). No skill lands in the `uncertain` band in this run. Because every answer is correct this is a best-case ceiling, not a typical learner; run with `--policy by-prior` for a more representative split.

These counts differ from earlier runs that used the placeholder `StubQuestionPool` (uniform slip 0.10 / guess 0.15). The real calibrated parameters are often sharper, so a correct answer moves the posterior faster and more skills reach `confident_mastered`. That is expected, not a regression.

### Run the service locally

```bash
export ENGINE_CONFIG_PATH=$PWD/config/engine_config.yaml
export TENANT_TOKENS_JSON='{"my-tenant": "dev-secret-please-change"}'
export STORAGE_BACKEND=memory
uvicorn engine.api.main:app --host 0.0.0.0 --port 4001
```

`curl http://localhost:4001/health` should return `{"status":"ok",...}`.

---

## 3. API reference

All endpoints accept and return JSON. The full spec is in `dynamic_diagnostic_engine_spec.md`; this section is a quick reference.

### Authentication

Every request requires the header `X-Internal-Service-Token`. The engine maintains a server-side allow-list mapping `tenant_id` to shared-secret token (loaded from the `TENANT_TOKENS_JSON` environment variable). The header value must match the registered token for the `tenant_id` in the request body. Mismatch returns `401 INVALID_TENANT_TOKEN`.

### Response envelope

Every API response is wrapped in this shape (spec section 5.1):

```json
{
  "id": "api.diagnostic.session.start",
  "ver": "1.0",
  "ts": "2026-05-26T12:34:56+00:00",
  "params": { "status": "SUCCESS", "msgid": null, "resmsgid": "..." },
  "responseCode": "OK",
  "result": { ... endpoint-specific payload ... },
  "error":  { "code": "...", "message": "..." }
}
```

`error` is present only on failure. `responseCode` mirrors the HTTP status name (`OK`, `BAD_REQUEST`, `UNAUTHORIZED`, `NOT_FOUND`, `CONFLICT`, `INTERNAL_SERVER_ERROR`, `SERVICE_UNAVAILABLE`).

`/health` returns a flat JSON object without the envelope — it's designed for Kubernetes probes.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/diagnostic/session/start` | Create a session, return the first question |
| POST | `/api/v1/diagnostic/session/{sub_session_id}/response` | Submit an answer, get the next question or verdicts if complete |
| POST | `/api/v1/diagnostic/session/{sub_session_id}/end` | End a session early; return verdicts based on current state |
| GET  | `/api/v1/diagnostic/session/{sub_session_id}/verdicts` | Re-fetch verdicts for a completed session |
| GET  | `/health` | Health probe |
| GET  | `/metrics` | Prometheus scrape endpoint |

**Misconception signals.** When a session completes (and on `/end` and `/verdicts`), the response carries a `misconception_signals` field alongside the `verdicts` array (a sibling; verdicts are untouched). It lists all 11 misconceptions, each with a three-state triage signal for the downstream detailed diagnostic (MainD): `likely_present` (wrong answers outnumber right), `likely_absent` (right outnumber wrong), `unsure` (a tie or no asks), or `not_applicable` (no question for this misconception at the learner's grade/tenant). Each entry also carries raw counts (`asked`, `correct`, `wrong`) and a `shortfall` flag (the misconception was applicable but could not reach its target number of asks). This is a prior, not a verdict; it never alters mastery. The field is absent while a session is still in progress.

### Error codes

| Code | HTTP | When |
|---|---|---|
| `INVALID_TENANT_TOKEN` | 401 | Missing or wrong `X-Internal-Service-Token` |
| `INVALID_GRADE` | 400 | Grade out of range or not configured |
| `INVALID_SKILL_ID` | 400 | `skill_id` not in the engine's scope |
| `LEARNER_MISMATCH` | 400 | `learner_id` doesn't match the session's learner |
| `PII_FIELD_PRESENT` | 400 | Request body contains a field not in the schema (PII guard) |
| `SESSION_ALREADY_EXISTS` | 409 | Duplicate `sub_session_id` on session/start |
| `SESSION_ALREADY_ENDED` | 409 | Action on a session that's no longer active |
| `SESSION_NOT_FOUND` | 404 | Unknown `sub_session_id` |
| `SESSION_NOT_COMPLETE` | 409 | GET /verdicts on an active session |
| `RESPONSE_CONFLICT` | 409 | Same `question_x_id` submitted with a different `is_correct` |
| `NO_TREE_FOR_GRADE` | 500 | Offline tree missing for the requested grade (Delhi G2-G5 ship; see Section 11) |
| `VERDICTS_NOT_WRITTEN` | 500 | Complete session has no verdicts (cleanup job recovers within 5 min) |
| `SESSION_LOCKED` | 503 | Reserved for v2 (concurrency control) |

---

## 4. Configuration

The engine is driven entirely by environment variables and a single YAML file. Spec section 10.3 lists these formally; this is the practical reference.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ENGINE_CONFIG_PATH` | Yes (prod) | `/etc/engine/config.yaml` | Path to `engine_config.yaml` |
| `QUESTION_PARAMETERS_PATH` | Yes (prod) | `/etc/engine/question_parameters.csv` | Path to the calibration CSV that `CsvQuestionPool` reads (question ids + calibrated slip/guess). Startup fails if absent. |
| `TENANT_QUESTION_LOOKUP_PATH` | No | (unset) | Optional path to `tenant_question_lookup.csv` (built offline). When set, the pool resolves tenant-scoped `question_x_id`s and filters to items the session tenant can serve. When unset, the pool uses the params `q_x_id` and ignores tenant (legacy mode). |
| `RETIRED_LIST_PATH` | No | (unset) | Optional path to `retired_questions_v2.csv` (the canonical 27-item retired list), applied at enumeration as defence-in-depth (the build step already drops retired rows from the lookup). |
| `TENANT_TOKENS_JSON` | Yes (prod) | `{}` | JSON object: `{"tenant_id": "shared_secret_token"}` |
| `STORAGE_BACKEND` | No | `memory` | `memory` or `mongodb`. Use `memory` only for local dev / smoke tests. |
| `MONGODB_URL` | If using MongoDB | — | MongoDB connection string |
| `MONGODB_DATABASE` | If using MongoDB | `aml_engine` | Database name |
| `ENGINE_VERSION` | No | `engine.__version__` | Version string stamped on every session document |
| `ENGINE_PORT` | No | `4001` | Port (uvicorn) |
| `LOG_LEVEL` | No | `info` | `debug` / `info` / `warn` / `error` |
| `LOG_FORMAT` | No | `json` | `json` or `text` |
| `STRICT_PRIORS_REQUIRED` | No | `false` | When `true`, the engine fails to start if any configured grade has no priors in `engine_config.yaml`. When `false` (default), the engine logs a WARN per missing grade and continues; `/health` reports the gap as `priors_missing_for_grades`. Set to `true` in production deployments where missing priors should block the rollout. |
| `PROMETHEUS_PUSHGATEWAY_URL` | No | — | When set, the `cleanup` CLI pushes its job metrics to this Pushgateway (a one-shot CronJob can't be scraped directly). When unset, cleanup counts are in the logs only. |

### `engine_config.yaml` shape

A skeleton lives at `config/engine_config.yaml`. The seed CLI populates it from canonical data sources. Structure:

```yaml
version: "0.9.0"

algorithm:
  slip: 0.10                           # P(correct | not_mastered)
  guess: 0.15                          # P(wrong | mastered)
  mastery_threshold: 0.95              # posterior >= this -> confident_mastered
  not_mastered_threshold: 0.10         # posterior <= this -> confident_not_mastered
  verification_trigger_high: 0.85      # posterior in (h, mastery) -> trigger verification
  verification_trigger_low: 0.15       # posterior in (not_mastered, l) -> trigger verification
  edge_propagation_value: 0.90         # value applied during lattice propagation
  info_gain_edge_bonus: 0.5            # routing score bonus per outgoing edge

budgets:
  2: { total: 25, per_operation: 6,  per_operation_cap_multiplier: 1.5, reserve_size: 7 }
  3: { total: 42, per_operation: 9,  per_operation_cap_multiplier: 1.5, reserve_size: 11 }
  4: { total: 59, per_operation: 13, per_operation_cap_multiplier: 1.5, reserve_size: 15 }
  5: { total: 76, per_operation: 16, per_operation_cap_multiplier: 1.5, reserve_size: 19 }

operation_order:
  2: [Multiplication, Addition, Subtraction, Division]
  3: [Multiplication, Addition, Subtraction, Division]
  4: [Multiplication, Addition, Subtraction, Division]
  5: [Division, Addition, Subtraction, Multiplication]

skills:
  - name: "1D+1D sum upto 9"
    operation: Addition
    sequence: 1
    content_grade: 1
  # ... 38 more

anchors:                # per-(grade, operation) starting skill
  3:
    Addition: "2-digit Addition with carry"
    ...

priors:                 # per-(grade, skill) cohort prior; missing skills default to 0.5
  3:
    "1D+1D sum upto 9": 0.95
    ...

misconception:          # misconception-coverage layer (spec section 7)
  target: 2                            # asks per applicable misconception
  conditional_extra: 0                 # extra asks allowed toward the clear/present band (ships at 0)
  clear_threshold: 0.75                # accuracy >= this -> likely_absent
  present_threshold: 0.50              # accuracy < this -> likely_present
```

Grades 6-8 fall back to the G5 configuration per spec section 2.

### Missing-priors handling

When a configured grade has no priors at all (an empty `priors[grade]` dict in the YAML), every skill at that grade silently falls back to a default prior of 0.5. This is fine for testing but easy to miss in production. The engine surfaces the gap in three ways:

1. A WARN log line at startup for each grade with no priors.
2. The `/health` endpoint includes `priors_missing_for_grades` (e.g. `[2]`).
3. Setting `STRICT_PRIORS_REQUIRED=true` makes startup fail with a clear error when any grade has no priors. Recommended for production rollouts.

With the canonical `priors_table_delhi_only.csv`, all four grades (G2-G5) have at least some Delhi priors, so the WARN does not fire for any grade. However, the Delhi diagnostic only tested about half of the in-scope skills at each grade (e.g. for G3, skills like "Repeated addition", "Tables 1 to 9", and "3-digit Addition without carry" have no Delhi data). Those untested skills silently fall back to the engine's 0.5 default prior. This is expected behaviour, not an error condition — the engine just lacks cohort-level evidence for those skills and will rely entirely on direct observation or lattice propagation during the session. The partial-coverage case is not surfaced by the existing WARN logic, which only catches grades with zero priors.

### The question pool (`CsvQuestionPool`)

When the engine picks a skill to test, it asks the question pool for a specific question to send the learner. The production pool is `CsvQuestionPool`, which reads `question_parameters.csv` (the calibration output) once at startup and returns a real question id (`q_x_id`) plus that question's calibrated `slip` and `guess`, so the Bayes update uses per-item values rather than the uniform config defaults.

Term definitions used below: an *item* is the canonical question key (a content string like `Addition|1D+1D sum upto 9|Fib||3|4`); a `q_x_id` is the concrete id the client loads content by; *discrimination* is how sharply a question separates learners who know a skill from those who don't, and equals `1 - slip - guess` (higher is sharper).

How a question is chosen for a skill:

1. Take all distinct items for that skill.
2. Drop any already asked this session (matched on item, so the same content is never repeated even if it later appears under more than one `q_x_id`).
3. Resolve each remaining item's parameters at the learner's grade: use the grade-specific row if there is one, else the item's `all` row. (Grade 2 has no grade-specific rows in the current file, so grade-2 learners always use the `all` row.)
4. Keep an item only if its discrimination is within `window_width` of the best discrimination among the candidates **and** at or above `discrimination_floor`.
5. Pick one at random (production), or the highest-discrimination item in `deterministic` mode (a hook reserved for the future offline-tree generator).

The window adapts to the data: in a skill whose questions were all calibrated with the same borrowed parameters, every question has identical discrimination and the window admits the whole bank; in a skill with directly estimated parameters it admits the sharp top cluster and drops the weak tail. On the current file this yields a median of about 17 candidates per skill.

Configuration:

- `QUESTION_PARAMETERS_PATH` (env var, default `/etc/engine/question_parameters.csv`): where `create_app_from_env` reads the CSV. The smoke test passes the real project path.
- `window_width` (default `0.10`) and `discrimination_floor` (default `0.50`): the two tunable numbers in step 4, set in the `CsvQuestionPool` constructor so they can be changed without code edits. On the current data the floor binds on only two items (both `Fib` questions that fall just below 0.50 at grade 5) and no skill is ever left with zero candidates.
- `seed` (default unset): when set, the random pick is reproducible, which is how tests pin behaviour. Production leaves it unset for variety. The smoke test exposes this as `--seed N`; the documented reference distribution above is `--seed 42`.

At startup the pool is given the engine's configured scope skills and logs a loud WARNING for any scope skill that has zero questions in the CSV (the same pattern as the missing-priors warning). On the current file all 39 scope skills have questions (10 to 26 each), so the warning does not fire.

`CsvQuestionPool` is the interim production pool. The eventual target is a pool backed by a live `questions` collection; until that exists, the CSV is the source of question ids and calibrated parameters. `StubQuestionPool` (placeholder ids, no calibration) remains available and is used by unit tests that do not need real content.

---

## 5. Deployment with Docker

### Build the image

```bash
docker build -t aml-diagnostic-engine:0.9.0 .
```

The image:
- Base: `python:3.11-slim` (multi-stage build keeps the runtime image small).
- Runs as non-root user `engine` (UID/GID 1000).
- Exposes port 4001.
- Default config path: `/etc/engine/config.yaml` (mount your seeded YAML here).
- Healthcheck hits `/health` every 30s.

### Run the container

```bash
docker run --rm \
    -e TENANT_TOKENS_JSON='{"prod-tenant": "REDACTED"}' \
    -e STORAGE_BACKEND=mongodb \
    -e MONGODB_URL=mongodb://mongo:27017 \
    -e MONGODB_DATABASE=aml \
    -v $(pwd)/config/engine_config.yaml:/etc/engine/config.yaml:ro \
    -p 4001:4001 \
    aml-diagnostic-engine:0.9.0
```

For Kubernetes: mount `engine_config.yaml` via a ConfigMap, put `TENANT_TOKENS_JSON` in a Secret, and set `STORAGE_BACKEND=mongodb` with MongoDB connection details from a Secret as well.

---

## 6. Deployment checklist for engineering

Before promoting this prototype to production, the engineering team must address:

| # | Item | Why |
|---|---|---|
| 1 | **Provide `question_parameters.csv` and set `QUESTION_PARAMETERS_PATH`.** | `create_app_from_env` builds `CsvQuestionPool` from this file (default path `/etc/engine/question_parameters.csv`); it returns real `q_x_id`s plus calibrated slip/guess. Mount the calibration output at that path. `CsvQuestionPool` is the interim production pool; a live `questions`-collection-backed pool is the eventual replacement (a one-class swap behind the same `QuestionPool` interface). |
| 2 | **Seed `tenant_tokens` per environment.** | The `TENANT_TOKENS_JSON` env var must contain the production tenant-to-token map. Rotate these secrets per your secrets policy. |
| 3 | **Configure MongoDB.** | Set `STORAGE_BACKEND=mongodb`, `MONGODB_URL`, and `MONGODB_DATABASE`. The engine creates required collections and indexes on startup; spec section 6.1 lists them. |
| 4 | **Set up Prometheus scraping.** | Point Prometheus at `:4001/metrics`. 12 business metrics are exposed; see spec section 9.1. |
| 5 | **Schedule the cleanup CronJob.** | See Section 7 "Cleanup CronJob" for the YAML. Recommended cadence: every 5 minutes. |
| 6 | **Validate the seeded config in CI.** | Add `python -m engine.cli validate-config --config config/engine_config.yaml` as a CI step so config changes can't ship broken. |
| 7 | **Decide on `STRICT_PRIORS_REQUIRED`.** | Default is false (warn on grades with no priors at all). With the canonical `priors_table_delhi_only.csv`, all four configured grades have some Delhi data, so the WARN does not fire for any grade. Strict mode is therefore safe to enable today and recommended for production — it prevents an accidental config swap from silently producing a grade with zero priors. Note: partial coverage (skills with no Delhi data falling back to 0.5) is NOT caught by this check; that's a content-team coverage question, not a deployment blocker. |

### Pending engineering decisions (spec section 16)

Items 1-7 above are required for any production deployment. The 19 items below are spec-tracked decisions where the spec has assumed a default and engineering needs to either confirm, change, or defer. None block the prototype's correctness; all should be triaged before the pilot promotes to general availability.

**Operational / deployment**

| # | Item | Spec assumption |
|---|---|---|
| 1 | Cleanup job interval | Every 5 minutes (Section 8.4) |
| 5 | Server-to-server auth | Per-tenant shared secrets in `X-Internal-Service-Token` (Section 5.1) |
| 6 | Helm chart for the Python engine | Engineering owns the new chart (Section 10.2) |
| 7 | Image registry and build pipeline | Engineering's existing pipeline extended OR new pipeline (Section 10.2) |
| 8 | Secret management for `TENANT_TOKENS_JSON` | Kubernetes secret with pod-restart rotation (Section 10.3) |
| 11 | Service mesh / API gateway | Engine designed without one; direct HTTP + shared-secret auth (Section 5) |
| 12 | Alerting and dashboarding | Engine emits metrics; alerts/dashboards owned by engineering (Sections 9, 14) |
| 13 | Operational runbook | Spec defines engine behaviour; runbook procedures are open (Section 14) |
| 14 | Backup and data lifecycle | Defaults assumed (Section 15) |
| 15 | Offline tree CronJob schedule | Manual triggering by default (Section 10.5) |

**Performance / capacity (engineering to set)**

| # | Item | Spec assumption |
|---|---|---|
| 2 | Redlock timeout (v2 horizontal scaling) | 30 seconds (Section 8.6); v1 not needed |
| 9 | Per-question API latency target | Not set; spec aims for "well under a second" (Section 5) |
| 10 | Expected concurrency at peak | Not known; v1 is single-instance (Section 4) |

**Naming / conventions (low-risk confirmations)**

| # | Item | Spec assumption |
|---|---|---|
| 3 | Error code names | `INVALID_TENANT_TOKEN`, `SESSION_ALREADY_EXISTS`, `RESPONSE_CONFLICT`, etc. (Section 5) |
| 4 | Log format | Structured JSON to stdout (Section 9.3) |

**Question pool / content team coordination**

| # | Item | Spec assumption |
|---|---|---|
| 16 | Question pool ownership | The engine's `QuestionPool` queries the `questions` collection directly. Alternative: `aml-api-service` does the lookup and only the skill name is returned to the client (Section 7.8) |
| 17 | Question metadata fields | Standard AML fields plus optional `slip_i`, `guess_i`, `discrimination_i`, `last_calibrated_at`, `n_observations_used` (Section 6.2.1). Content team to confirm what's populated today. |
| 18 | Tenant-scoped question pools | Engine assumes the `questions` collection is queryable by tenant (Section 7.8). Confirm tenant-scoped vs shared. |
| 19 | Per-item calibration pipeline | Not implemented in v1. Engine reads `slip_i` / `guess_i` when present, falls back to defaults otherwise (Section 4.3). Engineering + data team to decide investment timeline. |

Items 16-19 in particular interact with the per-item-overrides plumbing this engine now supports: the engine is ready to consume calibrated `slip_i` / `guess_i` the moment the content team or calibration pipeline starts populating them.

---

## 7. CLI reference

Run `python -m engine.cli <command> --help` for full options. Commands:

| Command | Purpose |
|---|---|
| `seed-config` | Generate `engine_config.yaml` from milestone CSV + priors CSV + anchors XLSX |
| `seed-lattice` | Load lattice edges from `lattice_edges_final.xlsx` into the configured storage backend |
| `simulate-session` | Drive a session end-to-end through the engine functions (no HTTP) with a synthetic answer policy (`all-correct`, `all-incorrect`, `by-prior`) |
| `validate-config` | Load and validate `engine_config.yaml`; return non-zero on errors |
| `cleanup` | Back-fill verdicts for sessions that completed but whose verdict write crashed (spec section 8.4 partial-write recovery). Intended for a Kubernetes CronJob. |

### Cleanup CronJob

The engine writes session state and verdicts in two separate storage operations on session completion. If the second write crashes (pod restart, transient DB error), the session is marked `complete` but has no verdicts. Reads from `/api/v1/diagnostic/session/{id}/verdicts` return `VERDICTS_NOT_WRITTEN` (500) until the gap is back-filled.

The `cleanup` subcommand back-fills these. It finds sessions matching `status==complete AND verdicts==[]`, recomputes verdicts via the same `compute_verdicts` function the engine uses live, and writes them. The operation is idempotent (replace-by-`sub_session_id` semantics in `save_verdicts`), so a re-run after a partial cleanup is safe.

**Manual run:**
```bash
python -m engine.cli cleanup \
    --config /etc/engine/config.yaml \
    --storage mongodb \
    --limit 100
```

Exit codes: `0` all recovered (or none found), `1` one or more per-session recoveries failed (continues processing the rest; see logs for details), `2` configuration or storage connection error before any session was processed.

The `--lattice` flag is optional. `compute_verdicts` reads the session's already-propagated posteriors; it does not re-propagate. An empty lattice is therefore safe and is the default.

**Kubernetes CronJob example:**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: engine-cleanup
spec:
  schedule: "*/5 * * * *"   # every 5 minutes
  concurrencyPolicy: Forbid  # don't overlap runs
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: cleanup
              image: aml-diagnostic-engine:0.9.0   # same image as the engine
              command:
                - python
                - "-m"
                - engine.cli
                - cleanup
                - "--config"
                - /etc/engine/config.yaml
                - "--storage"
                - mongodb
                - "--limit"
                - "200"
              env:
                - name: MONGODB_URL
                  valueFrom:
                    secretKeyRef: {name: engine-secrets, key: mongodb-url}
                - name: MONGODB_DATABASE
                  value: aml_engine
                - name: LOG_FORMAT
                  value: json
                - name: PROMETHEUS_PUSHGATEWAY_URL
                  value: pushgateway.monitoring:9091   # omit to skip metric export
              volumeMounts:
                - name: engine-config
                  mountPath: /etc/engine
                  readOnly: true
          volumes:
            - name: engine-config
              configMap:
                name: engine-config
```

**Operational notes:**
- The CronJob is independent of the engine pods. Run it against the same MongoDB the engine writes to, using the same `engine_config.yaml` via a shared ConfigMap.
- The `--limit` flag caps work per run so a single CronJob invocation doesn't hold a long-running query. Tune based on cluster load and the typical partial-write backlog.
- Logs are JSON to stdout (one line per session recovered, one summary line per run). Aggregate via your cluster's log pipeline and alert on `failed` counts.
- The cleanup run increments the spec section 9.1 cleanup counters (`diagnostic_cleanup_job_runs_total{outcome}`, `diagnostic_cleanup_job_recovered_sessions_total`). Because a one-shot CronJob process can't be scraped by Prometheus directly, set `PROMETHEUS_PUSHGATEWAY_URL` (e.g. `pushgateway.monitoring:9091`) so the run pushes its metrics to a Pushgateway. When the env var is unset, the counts are still in the summary log line and a single note records that no Pushgateway was configured; push failures are logged at WARN and never change the cleanup exit code.

### Lattice edge values come from Delhi Entry→Entry columns only

The `lattice_edges_final.xlsx` file has columns for both Telangana Exit→Entry and Delhi Entry→Entry pooled values. The engine was calibrated on Delhi data, so the loader reads Delhi values exclusively. Telangana columns are present in the source file for reference but are not used by the engine.

Updating the engine with Telangana data is a separate, tracked workstream and is not part of this prototype.

---

## 8. Internals (brief tour for engineers reading the code)

### Module layout

```
engine/
├── bayes.py              # pure: Bayes update, P(correct|mastery)
├── lattice.py            # pure: LatticeEdge, LatticeIndex, propagate()
├── routing.py            # pure: RoutingConfig, info-gain score, pick_next_question
├── verdicts.py           # pure: assign_verdict (8-rule table from spec section 7.6)
├── session.py            # orchestrator: start/record/end, only place state mutates
├── config.py             # EngineConfig (Pydantic) + YAML loader + get_engine_params
├── question_pool.py      # QuestionPool ABC + StubQuestionPool + CsvQuestionPool
├── cli.py                # argparse-based subcommands
├── cli_io.py             # loaders for milestone CSV, priors CSV, anchors/lattice XLSX
├── api/
│   ├── envelope.py       # success/error envelope wrappers
│   ├── errors.py         # 13 error codes + HTTP mapping
│   ├── schemas.py        # Pydantic request/response models (extra='forbid' = PII guard)
│   ├── auth.py           # X-Internal-Service-Token verification, constant-time compare
│   ├── routes.py         # 6 endpoint handlers
│   └── main.py           # create_app(...) + create_app_from_env() + exception handlers
├── observability/
│   ├── logging.py        # structlog config + PII allow-list filter (spec section 9.3)
│   └── metrics.py        # 12 Prometheus metrics via register_metrics(registry) factory
└── storage/
    ├── interface.py      # StorageBackend ABC
    ├── memory.py         # InMemoryStorage (thread-safe, deep-copies)
    ├── mongodb.py        # MongoDbStorage (PyMongo)
    ├── documents.py      # Session / SkillVerdict / LatticeEdge <-> dict
    └── __init__.py       # get_storage_backend(...) factory
```

### Design principles

1. **Mutation lives in one module.** Only `session.py` mutates state. `bayes`, `lattice`, `routing`, `verdicts` are pure functions taking inputs and returning outputs. This makes them trivially testable and easy to reason about.
2. **Validation at construction.** `RoutingConfig`, `LatticeEdge`, and the Pydantic config models validate their inputs in `__init__` so bad values fail fast at startup, not on the 500th request.
3. **Per-app metric registries.** `register_metrics(registry)` creates fresh metrics per app instance, avoiding `prometheus_client` global-registry collisions in tests and supporting clean multi-app deployments.
4. **Idempotency is replay-aware, conflict-aware.** Submitting the same `(question_x_id, is_correct)` twice is a no-op (the engine returns the cached response). Submitting the same `question_x_id` with a different `is_correct` returns 409 `RESPONSE_CONFLICT`. Both behaviours are spec section 8.3.
5. **Storage is pluggable.** The same test suite runs against `InMemoryStorage` and a `mongomock`-backed `MongoDbStorage`. Swap backends via `STORAGE_BACKEND` env var with no engine code change.

### Verdict logic (spec section 7.6 - eight rules)

The engine assigns one verdict per in-scope skill at session end. The verdict depends on three per-skill counters: the final `posterior`, the count of `direct_observations`, and the count of `propagation_updates` (the times the skill's posterior was moved by lattice propagation from a different skill's observation).

| Rule | Posterior | Direct obs | Propagation updates | Verdict | Recommendation |
|:---:|---|:---:|:---:|---|---|
| 1 | `>= 0.95` | `>= 1` | any | `confident_mastered` | `skip_maind` |
| 2 | `>= 0.95` | `0` | `0` | `confident_mastered` | `skip_maind` |
| 3 | `>= 0.95` | `0` | `>= 1` | `uncertain` (downgrade) | `take_maind_diagnostic` |
| 4 | `0.5 <= p < 0.95` | any | any | `uncertain` | `take_maind_confirmation` |
| 5 | `0.10 < p < 0.5` | any | any | `uncertain` | `take_maind_diagnostic` |
| 6 | `<= 0.10` | `>= 1` | any | `confident_not_mastered` | `take_maind_diagnostic` |
| 7 | `<= 0.10` | `0` | `0` | `confident_not_mastered` | `take_maind_diagnostic` |
| 8 | `<= 0.10` | `0` | `>= 1` | `uncertain` (downgrade) | `take_maind_diagnostic` |

The priors-only vs propagation-only distinction (Rules 2/7 vs 3/8) is the key insight. The cohort priors come from the Delhi diagnostic response cohort (n_DL ≥ 130 per skill, ~1,300+ per skill for G3-G5) and are calibrated empirically; the simulation evidence in the Testing Summary section 4 (Minimum Direct Evidence) confirms forcing a direct observation on every skill did not improve pooled accuracy. So priors-only resolutions (the engine never touched the skill at all) are trusted as confident verdicts.

Lattice propagation is different. The 12 hand-curated edges are inferred relationships, not direct measurements. Testing Summary section 9 (Verification on/off) showed removing verification of propagation-resolved skills cost 0.3 pp pooled accuracy and 2.2 pp on G2 Division specifically. So propagation-only resolutions are downgraded to `uncertain` so MainD verifies them.

---

## 9. Known limitations and out-of-scope items

Tracked, intentional gaps. None of these block the prototype's primary purpose (verify the engine state machine + API contract are correct).

1. **`CsvQuestionPool` is an interim pool.** It reads questions and calibrated parameters from `question_parameters.csv` rather than a live `questions` collection. It is production-usable today; the eventual target is a collection-backed pool behind the same interface. `StubQuestionPool` (placeholder ids) remains for unit tests only.
2. **Offline decision-tree path (shipped for Delhi).** The per-operation sequencing trees are generated, serialized, and validated for Delhi G2-G5; see Section 11 for the modules, artifacts, and rebuild/validate commands. The session/start response carries an `offline_tree` field for the client contract; serving the serialized trees through that runtime field when the online engine is unavailable is the remaining engineering integration step, not a gap in the offline path itself.
3. **Numbers operation is excluded.** Per project decision, the engine covers four operations (Addition, Subtraction, Multiplication, Division). 39 L2.5 skills are in the Delhi scope; 40 across all tenants (the 40th, "1D - 1 to 4", is served in Karnataka/Private/Telangana, not Delhi).
4. **`find_complete_sessions_without_verdicts` is N+1 in MongoDB.** Could be a `$lookup` pipeline; left as-is because the cleanup job runs every 5 minutes and the volume should be small.
5. **No optimistic concurrency control.** Spec section 8.6 marks v1 as single-instance per session. v2 needs an `if-match` / `expectedVersion` field on `/response` calls.

---

## 10. Testing

| Suite | Count |
|---|---|
| Engine core (bayes, lattice, routing, verdicts, session) | 232 |
| Storage (parameterised across InMemoryStorage and MongoDbStorage via mongomock) | 61 |
| Config | 33 |
| API + observability | 86 |
| CLI + cli_io + cleanup | 56 |
| Question pool (CsvQuestionPool) | 39 |
| Misconception-coverage layer (ledger, phases, opportunistic + backfill pick, signals, v7 verdict rule, e2e) | 77 |
| Stage B in-process integration | 8 |
| Offline path | 5 |
| **Total** | **597** |

```bash
pytest                      # full suite
pytest tests/test_api.py    # just the API tests
pytest -k idempotent        # tests matching a name pattern
```

Tests are organised by module. Each test file documents what it covers at the top.

---

## 11. Offline decision-tree path (Delhi)

The engine ships an offline decision-tree path: precomputed per-operation sequencing trees that reproduce the online engine's routing without a live service, intended as a fallback when the online engine is unavailable. It is delivered for Delhi G2-G5 as serialized artifacts plus the modules to rebuild and validate them.

### Modules (repo root)

| Module | Role |
|---|---|
| `offline_tree_gen.py` | Engine loader + base-walk helpers |
| `offline_tree_perop.py` | Per-operation generator (phase-tagged nodes: base / backfill / harvest; always-on misconception backfill; skill-harvest allowance; 3-decimal keying) |
| `offline_follow.py` | Pure base-first three-pass capped follow (`follow_capped`), engine-free and unit-tested |
| `offline_followsim.py` | Residual-gap harness |
| `offline_scorer.py` | History-based scorer (`score_history`, `return_session=True`) |
| `offline_serialize.py` | Serialize to the `diagnostic_offline_trees` contract (reads `engine.__version__`, so the artifact carries 0.9.0) |
| `offline_validate_artifact.py` | Deserialize-and-follow validation of the shipped artifact |
| `measure_allowance.py`, `offline_efficiency_gap.py` | Measurement support |

### Artifacts

`artifact/Delhi/g{2..5}.json.gz` - the serialized offline trees: four per-operation trees per grade plus a shared params block and provenance. Locked skill-harvest allowances: G2 +3, G3 +4, G4 +4, G5 +3.

### Rebuild / validate

```bash
python offline_validate_artifact.py 2,3,4,5   # validate the shipped Delhi trees
python offline_serialize.py 2,3,4,5           # rebuild + re-serialize (Delhi)
```

Runtime paths are repo-relative and resolve against the bundled `data/` and `artifact/` with no `/mnt` dependency. The offline follow enforces the grade budget as a hard cap via a base-first three-pass walk (Pass 1 base caps, Pass 2 misconception backfill, Pass 3 skill harvest, fixed operation order) plus a global question counter. Validation on the serialized artifact confirms cap correctness (over-budget fraction 0.000 every grade, q_max = budget), below-target ~0 every grade, reproduced residual gaps (G2 0.55, G3 2.45, G4 2.68, G5 5.33), and exact scoring / connectivity / id-join. `tests/test_offline_path.py` (5 tests, part of the 597) covers the follow / cap / phase logic and a version-drift guard.

Per-tenant regeneration (Karnataka / Private / Telangana) waits on Telangana priors; Delhi is sized here, and because size is depth-driven the envelope is expected to hold across tenants.

---

## 12. License and provenance

Proprietary, EkStep. Built as a prototype refactor of the simulation code in `sim_engine.py` / `sim_routing.py` / `sim_run.py`, following the spec in `dynamic_diagnostic_engine_spec.md` and the design rationale in `Dynamic_Diagnostic_Design_v2.md`.
