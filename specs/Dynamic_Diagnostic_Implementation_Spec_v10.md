# Dynamic Diagnostic Engine

### Implementation specification (for the AML engineering team)

**Version 10 (matches diagnostic engine 0.10.0)  |  July 2026**

---

## 1. What this document is

This is the build guide for integrating the dynamic diagnostic engine into the live AML product. It is the action-oriented subset of the engineering specification (the v10 engine spec), which remains the reference for the data model and algorithm. Where this guide says "see spec," it means that document. For convenience this guide is self-contained on the two things the AML and app teams need most: the full engine **API reference** - every endpoint, all parameters, and sample requests and responses - is reproduced as **Appendix A**, and the step-by-step **offline-walk handover pack** for the app team as **Appendix B**.

Every step below is anchored to the actual AML codebase, based on a direct review of the `aml-api-service` and `aml-portal` repositories. File and endpoint names are the real ones found in those repos.

**How to read it:** Section 3 is the recommended sequence. Section 4 is the online integration (do this first). Section 5 is the offline integration (do this second). Section 6 is the one-time build-time checklist. Sections 7 and 8 are risks and open confirmations. Appendix A is the engine API reference; Appendix B is the offline-walk handover pack.

---

## 2. Starting point (what exists today)

From the repository review:

- **The live diagnostic is the old static one, server-side.** `evaluateLearner.ts` calls `handleEntryDiagnostic` for learners in `NOT_STARTED` or `IN_PROGRESS` state, then falls through to practice. The entry diagnostic itself (`entryDiagnostic.helper.ts`) is a static chain-walk over (class, L1-skill) question sets with a threshold pass/fail and a two-consecutive-fails skip rule, writing a `tailored_sequence`. The route is `POST /learner/evaluate/:learner_id` (`learnerRouter.ts`). The client wrapper `logicEngineEvalutionService.fetchLogicEngineEvaluation` hits `/api/v1/portal/learner/evaluate/{id}`. There is no adaptive, Bayesian, or tree-based engine in the codebase today, and no client-side question sequencing.
- **Per-question attempt history already exists.** `aml-api-service` writes `learner_proficiency_question_level_data` with `question_id`, full taxonomy to `l2_5_skill`, per-question score, attempt number, and session id. This is what the offline history scorer needs, with one required translation (C-1): `question_id` is finer-grained than the engine's `question_x_id` - many `question_id`s map to one `question_x_id` - so the scorer must map `question_id` -> `question_x_id` before replaying (see Section 7).
- **The portal already has an offline-first response pipeline.** `aml-portal` records responses in IndexedDB with a sync lifecycle and reconciliation sagas (`logicEngineEvaluation.saga.ts`, `SyncLearnerResponse.saga.ts`). Question content is not cached offline today (the service worker precaches the app shell only).

The engine is a built, tested Python service (engine **0.10.0, 668 tests passing**) with a FastAPI HTTP interface and MongoDB storage. Since the initial integration it has added **mixed-mode online/offline switching** and the **deactivation failsafe** - the MINOR change that took it to 0.10.0, both **verdict-neutral** (they change how and when questions are delivered, never how an answer is scored) - plus a storage-layer datetime fix. It is integration-ready as a service; the work below is AML-side glue plus, for offline, a small client port.

---

## 3. Recommended sequence

![Engine architecture (target state)](img/architecture.png)

Do the online integration first, then the offline integration. The online path is lower-risk (server-to-server, no client changes) and delivers the accuracy and MainD-saving benefits on connected devices. The offline path adds the on-device walk and depends on the online path's server pieces (the same engine, the same history scorer) already being in place.

Do **not** port the engine into the Node service. It integrates as a sibling Python service the Node backend calls over HTTP. Porting 668 tests of numerical Bayesian code to TypeScript is high-risk and unnecessary; the engine already shares AML's datastore family and Kubernetes deployment model.

---

## 4. Phase 1: online integration

![Where the new calls slot into the existing AML flow](img/online_integration_flow.png)

### 4.1 Deploy the engine service

1. Deploy the engine container (see spec Section 10.2). It needs its own MongoDB database (default `aml_engine`); it does not write to AML's collections.
2. Set environment variables (spec Section 10.3): config path, calibration file path, per-tenant question lookup path, tenant tokens. Load the canonical data files (priors, lattice, anchors, skill list, calibration) at startup.
3. Generate and register one shared-secret token per AML instance (Delhi, Telangana, future states) in both the instance's `aml-api-service` config and the engine's `TENANT_TOKENS_JSON`.
4. Verify `/health` returns 200 and Prometheus can scrape `/metrics`.

### 4.2 Wire `aml-api-service` to call the engine

The integration point is `evaluateLearner.ts`, where `handleEntryDiagnostic` is invoked today.

1. Behind a per-tenant feature flag, replace the static `handleEntryDiagnostic` path with calls to the engine:
   - On diagnostic start: call `POST /api/v1/diagnostic/session/start`; the engine returns the first `question_x_id` and `skill_id`.
   - On each scored response: call `POST /api/v1/diagnostic/session/:sub_session_id/response` with `{skill_id, question_x_id, is_correct}`; the engine returns the next `question_x_id`, or session-end plus the three-band verdicts.
2. Keep scoring where it is. `aml-api-service` already scores responses and writes `learner_proficiency_question_level_data`; the engine consumes the `is_correct` result, it does not score.
3. Server-to-server auth uses the shared secret (spec Section 5.1), not the learner JWT.
4. **Deactivation failsafe (optional, recommended).** If a question is pulled from the app faster than the engine's data updates, pass the current switched-off-question list on the start and response calls so the engine never offers them, and use `POST .../session/:sub_session_id/replace-question` to swap out a single question the app cannot show. Both are optional and change coverage, not scoring (Appendix A.3, A.11, A.12).

![The deactivation failsafe](img/deactivation_failsafe.png)

Every endpoint, its parameters (including the optional switched-off list), and sample requests and responses are in **Appendix A**.

### 4.3 Identifier mapping

The engine works in its own skill and question identifiers; AML works in its taxonomy. Build a mapping layer, mostly at build time:

1. **Skills.** The engine's canonical L2.5 skill names (40; 39 in the Delhi scope) map to AML's `skill_master` entries. The L2.5 skill layer is shared between the engine and AML, so this is a name-to-id lookup per tenant (confirm each canonical name matches a `skill_master.name.en`, or document the translation; see Section 6). This is the tractable side.
2. **Questions.** The engine selects in content (`item`) space and resolves to a single `question_x_id` per tenant via the per-tenant lookup (spec Section 7.8). `aml-api-service` already fetches question content by `question_x_id`, so the engine's returned id is directly usable.

### 4.4 Set-versus-question bridge

The old static diagnostic is question-set based (it walks sets per (class, L1-skill)); the engine is per-question. The bridge is: the engine returns one `question_x_id` at a time, and `aml-api-service` serves that single question rather than a set. The existing single-question serving path (used within sets today) is reused; the set-walk logic is what the engine replaces.

### 4.5 Verdict re-entry into the learner journey

On session end the engine returns a verdict per in-scope skill (`confident_mastered` / `uncertain` / `confident_not_mastered`) with a recommendation (`skip_maind` / `take_maind_*`). Translate these into the learner's `tailored_sequence`:

1. For `confident_mastered` + `skip_maind`: mark that skill's MainD as skippable in the tailored sequence.
2. For `uncertain` and `confident_not_mastered`: route to the full MainD as the existing flow does.
3. Preserve the misconception tag (spec Section 7.9) where present, so practice can target the specific mistake. The merged learning-state shape that carries the tag alongside each skill's verdict is in spec Appendix E.

After this step, the learner continues into practice exactly as today.

Please note that the Numbers operation has been dropped from the Dynamic Diagnostic, since place-value misconceptions (the main thing Numbers questions assess) can still be identified after the diagnostic, from learners' answers on other operations.

To enable this change, the following content logic / rules need to be implemented:
- if the verdict for the ‘2-digit addition without carry’ skills is either uncertain or confident_not_mastered in the Dynamic Diagnostic (i.e., the recommendation for ‘2-digit addition without carry’ is either take_maind_diagnostic or take_maind_confirmation), then the learner needs to take the MainD for both ‘Numbers’ and ‘2-digit addition without carry’.
- if the verdict for ‘2-digit addition without carry’ is confident_mastered in the Dynamic Diagnostic (i.e., recommendation for ‘2-digit addition without carry’ is skip_maind), then the learner needs to take the MainD for both ‘Numbers’ and ‘2-digit addition without carry’.

### 4.6 Phase 1 acceptance criteria

- A connected learner completes a diagnostic driven end-to-end by the engine, under the feature flag, for one tenant.
- Verdicts are written and correctly translate to skip-vs-take MainD in `tailored_sequence`.
- Question budgets are respected (no session exceeds the grade cap).
- Per-question attempt history is written as today (`learner_proficiency_question_level_data`).
- Run as a monitored pilot on one tenant before wider rollout.

---

## 5. Phase 2: offline integration

The offline path reuses most of the online server pieces. Only the on-device walk and client glue are new.

### 5.1 Reuse: tree generation (server, no change)

The four per-operation trees per (tenant, grade) are produced by the tree-generation batch job (spec Section 10.5), deployed as a Kubernetes CronJob, triggered on input change. The job writes each bundle as a gzipped file artifact under `OFFLINE_ARTIFACT_DIR`; the engine loads them at startup and serves them through the offline-tree fetch endpoint (spec Section 5.9) - they are not a MongoDB collection. No new logic is needed here; it is built.

### 5.2 Reuse: history scoring (server, no change)

Offline sessions are scored on the server when the device syncs, by the history scorer (spec Section 7.10), which replays the recorded attempt history through the engine's own functions. The device sends the offline stretch via the offline-batch endpoint (Appendix A.11), which folds it into the single unified session and re-scores the whole history in order, so a session split across online and offline scores identically to a fully-online one (verdict-neutral). This is built and verified. It needs the same per-question records the online path already produces.

![Mixed-mode: one session across online and offline](img/mixed_mode_handoff.png)

### 5.3 New: port the follow loop to the client

The on-device walk (the three-pass base-first follow, spec Section 4.3) must run in the portal's language (TypeScript). It is small and engine-free by design: it walks the per-operation trees, applies the base caps, the always-on misconception backfill, and the skill harvest, all under the hard grade budget. It computes no posteriors and no verdicts; it only decides which `question_x_id` to show next based on the tree and the answers so far.

Port the reference `follow_capped` routine. Acceptance is that, given the same trees and answer sequence, the TypeScript walk visits the same nodes as the Python reference (deterministic). **The full step-by-step build guide for this - the artifacts the app team receives, the seven-step walk, the skip-and-do-not-record rule, and the vector-based acceptance bar - is Appendix B.**

### 5.4 New: client glue

1. At session start (while connected), `session/start` returns a small `offline_tree` reference (`fetch_path`, `sha256`, `size_bytes`); fetch the grade's bundle from that path (the offline-tree endpoint, spec Section 5.9) and cache it in IndexedDB by `sha256`. The portal already uses IndexedDB; the G5 bundle is about 5.4 MB compressed and about 24.8 MB as served canonical JSON (the size the reference advertises in `size_bytes`), smaller below. Grades above 5 resolve to the G5 tree; a grade with no tree returns `offline_tree: null`. Also keep the latest `resumption_token` (returned by `session/start` and every online response), so the walk can resume from where the session already is.
2. During an offline segment, walk the trees and record each attempt (`question_x_id`, `skill_id`, correctness, the raw answer, and a timestamp). If a node's question cannot be shown, skip it, follow the on-incorrect branch, and record nothing (the failsafe skip rule, Appendix B.4). The response-recording pipeline largely exists (`SyncLearnerResponse.saga.ts`); confirm it persists `question_id` per attempt (the repo shows it does).
3. On reconnect, send the offline attempts to `aml-api-service`, which forwards them to the engine's **offline-batch** endpoint (Appendix A.11); the engine re-scores the unified history and returns verdicts (or the next question, if the learner continues). The session can switch between online and offline any number of times.
4. Ensure question content for any `question_x_id` a tree can reach is available offline. Today the service worker caches only the app shell; caching the reachable question content for the session is an `aml-portal` task (spec Section 4.3 lists this as the client's responsibility).

### 5.5 Phase 2 acceptance criteria

- A learner completes a session offline, the device records attempts, and on sync the server produces verdicts identical to what an online session on the same answers would produce.
- A session split across online and offline segments scores identically to a fully-online session on the same answers (source-agnostic, spec Section 7.10).
- Offline question budgets respected (hard cap holds).
- The TypeScript walk reproduces every shared test vector's question sequence and count exactly (Appendix B.5).
- An unavailable (switched-off) question offline is skipped and not recorded, and the walk still completes correctly (Appendix B.4).

---

## 6. Build-time checklist (one-time)

From spec Section 10.6, the tasks that must be done before the first production session:

1. **Skill-name-to-id mapping per tenant:** confirm each of the canonical L2.5 skill names (40; 39 in the Delhi scope) matches a `skill_master.name.en`, or document the translation `aml-api-service` applies.
2. **Lattice seeding:** import the 12 lattice edges.
3. **Calibration file deployment:** place the per-item calibration file where the engine loads it.
4. **Per-tenant question lookup build:** for each tenant, build the `(tenant, item) -> question_x_id` lookup from that tenant's active-question list.
5. **Initial tree generation:** run the batch job per (tenant, grade), validate, promote to active.
6. **Per-tenant secrets:** create and distribute one shared secret per instance.
7. **Deploy and verify:** set env vars, deploy, confirm `/health` and metrics.
8. **Smoke test:** one end-to-end session per tenant; verify verdicts are written correctly.

---

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Skill-name mismatch between engine and a tenant's `skill_master` | Resolve at build time (checklist item 1); fail loudly at startup if a canonical skill has no mapping rather than silently mis-routing. |
| Question content not available offline for a reachable `question_x_id` | Cache the session's reachable question content at session start (Section 5.4 step 4); the tree fails closed if content is missing. |
| Offline trees built on Delhi priors for non-Delhi tenants | Known limitation (spec Section 10.5). The item set is tenant-specific now; regenerate when per-tenant priors (especially Telangana) arrive. Treat early non-Delhi offline as pilot. |
| Concurrency on the same session across instances | Per-session lock (spec Section 8.6); single instance is fine for pilot-scale concurrency. |
| The TS follow-loop port diverges from the Python reference | Deterministic equivalence test (Section 5.3) as an acceptance gate; the shared vectors in Appendix B.5 are the gate. |
| A question is switched off on the app but still in the engine's data | The deactivation failsafe: pass the switched-off list on the calls, use `replace-question` online, and the skip-and-do-not-record rule offline (Appendix A.11-A.12, Appendix B.4). Coverage changes; scoring does not. |
| A false skip is committed before it is detected (a learner got `skip_maind` on a skill later found not-mastered, e.g. the G2 Subtraction weakness surfacing live) | The feature flag only affects new sessions; a written verdict is not changed retroactively. Define a remediation path to re-open the affected skill's MainD for already-scored learners (spec Section 14). This is a required safety procedure before wide rollout, not just an alert. |
| Offline history scorer join key (C-1) | The scorer replays from `learner_proficiency_question_level_data`, keyed on `question_id`, while the trees and engine use `question_x_id`. These are **not** the same value: many `question_id`s map to one `question_x_id`. Provide the `question_id` -> `question_x_id` mapping where the scorer runs (a many-to-one lookup) before the offline pilot, or the replay will not resolve. |

---

## 8. Open confirmations (not blocking the build)

- **Telemetry join for `conditional_extra = 0`.** The durable-sink export plus the MainD join is a data-platform confirmation, not verifiable from the engine repo. It is the load-bearing check for keeping the misconception-repeat target at 0 (spec Section 7.9); confirm it is in place before relying on the shipped value in production analysis.
- **Per-tenant priors.** Telangana response data is pending; regenerate offline trees when it arrives (spec Section 10.5).
- **Raw response persistence for misconception classification - Stage-B go-live blocker (not a build blocker).** The mastery engine consumes only `is_correct` per response, but the misconception classifier (spec Section 7.9, Appendix E) needs the learner's raw typed answer per `Fib` question. The engine side of this is now built in 0.9.0: the response call accepts an optional `raw_response` (spec Section 5.4), the session stores it, and a responses endpoint (spec Section 5.10) returns it for the session-end classification step (the earlier `raw_response_of` stand-in now reads real persisted data). The remaining blocker is AML-side: `aml-api-service` must send `raw_response` on the response call and the classification step must read it back via Section 5.10. Until that AML wiring lands, misconception classification cannot run end-to-end in production. This blocks Stage-B (misconception) go-live; it does not block the core mastery-verdict pilot, which needs only `is_correct`.
- **Offline question-content delivery mechanism and size.** Whether reachable question content is bundled at install, downloaded at session start, or fetched on demand is an `aml-portal` decision (spec Section 4.3). Note the tree bundle (about 24.8 MB of served JSON at G5, ~5.4 MB compressed) is the tree structure only; the question content the client must also cache (text and any media for every `question_x_id` a tree can reach) has not been sized. For the low-connectivity learners offline exists to serve, an unsized session-start download is the single most likely field failure. Size this payload and confirm the mechanism before the offline pilot; treat it as the top offline risk.

---

## Appendix A: Engine API reference

> **How to read this appendix.** This reproduces the engine spec's API contract so the build guide is self-contained; it is identical in substance to the engine spec Section 5.
>
> **How to read the endpoints.** Every endpoint below has the same four parts: **When to use it** (in plain terms), a **Parameters** table (every field, whether it is required or optional, and what it means in simple language), a **Sample request**, and a **Sample response**. The sample values are taken from a real Delhi grade-3 session, so the `question_x_id`s and skills are genuine. There are ten endpoints: eight functional ones (documented in full) and two operational probes, `GET /metrics` and `GET /health` (documented briefly, since they take no parameters).

### A.1 Base, auth, and conventions

**Base URL:** `http(s)://<engine-host>:<port>/api/v1/diagnostic`. All engine routes live under this prefix.

**Method convention:** Following AML's existing pattern, routes use POST for actions (including idempotent ones) and GET only for resource reads. The engine has **five POST** endpoints (start, response, end, offline-batch, replace-question) and **five GET** endpoints (verdicts, responses, offline-tree, metrics, health) - ten in total.

**Content type:** Request and response bodies are JSON. The engine accepts and returns `application/json`.

**Authentication.** Every engine endpoint that touches session data requires a shared-secret header:

```
X-Internal-Service-Token: <per-tenant secret>
```

The engine maintains a server-side allow-list mapping `tenant_id` -> expected token. A request is accepted if the header value matches the token registered for the `tenant_id` in the request body (or in the path, for the offline-tree endpoint). A mismatch returns `401 INVALID_TENANT_TOKEN`. Tokens are configured per state-instance of `aml-api-service` and are loaded at engine startup from environment variables (see the engine spec Section 10).

`GET /metrics` and `GET /health` have no auth, consistent with `aml-api-service`'s `/metrics` route.

**Unknown fields are rejected.** All request bodies are strict: a field the engine does not expect (for example a stray `username` or `name`) is refused rather than ignored, which is also a PII guard (the engine spec Section 6.3).

**Response envelope.** The engine uses the same envelope shape as `aml-api-service` so logs, traces, and downstream parsing stay consistent across services.

Success:
```json
{
  "id": "api.diagnostic.session.start",
  "ver": "1.0",
  "ts": "2026-05-26T12:34:56+00:00",
  "params": {
    "status": "SUCCESS",
    "msgid": "<client-provided message id, if any>",
    "resmsgid": "<engine-generated trace id>"
  },
  "responseCode": "OK",
  "result": { /* endpoint-specific payload */ }
}
```

Error:
```json
{
  "id": "api.diagnostic.session.start",
  "ver": "1.0",
  "ts": "2026-05-26T12:34:56+00:00",
  "params": {
    "status": "FAILED",
    "msgid": "...",
    "resmsgid": "..."
  },
  "responseCode": "BAD_REQUEST",
  "result": {},
  "error": {
    "code": "INVALID_SKILL_ID",
    "message": "skill_id 'XYZ' is not in the canonical skill list"
  }
}
```

In the per-endpoint samples below, only the `result` payload (or the request body) is shown; assume the full envelope wraps it.

### A.2 Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/diagnostic/session/start` | Create an engine session for a learner; return the first question and an offline-tree reference |
| POST | `/api/v1/diagnostic/session/:sub_session_id/response` | Submit a scored answer; get the next question or the session-end signal with verdicts |
| POST | `/api/v1/diagnostic/session/:sub_session_id/end` | Mark the session as ended explicitly (learner abandoned or timed out) |
| POST | `/api/v1/diagnostic/session/:sub_session_id/offline-batch` | Ingest a batch of answers collected offline into the one unified session, then return the next question (mixed-mode) |
| POST | `/api/v1/diagnostic/session/:sub_session_id/replace-question` | Decline the offered question and get a different one; records nothing, spends no budget (deactivation failsafe) |
| GET | `/api/v1/diagnostic/session/:sub_session_id/verdicts` | Re-fetch the final verdicts for a completed session |
| GET | `/api/v1/diagnostic/session/:sub_session_id/responses` | Fetch the stored raw answers for a session (for the misconception classifier) |
| GET | `/api/v1/diagnostic/offline-tree/:tenant_id/:grade` | Fetch the offline decision-tree bundle for a (tenant, grade) |
| GET | `/metrics` | Prometheus scrape endpoint (no auth) |
| GET | `/health` | Service health check (no auth) |

The three shaded topics that cut across several endpoints - the optional **switched-off list** (deactivation failsafe), the **resumption token** (mixed-mode), and **verdict neutrality** - are introduced where they first appear and cross-referenced from the engine spec Section 7 and Appendix B.

### A.3 `POST /api/v1/diagnostic/session/start`

**When to use it.** Once, at the very beginning of a learner's diagnostic, right after `aml-api-service` has created the `learner_sub_sessions` record. It creates the engine's session, hands back the first question, and (if a tree exists for the learner's tenant and grade) a reference the device can use to fetch an offline tree.

**Parameters (request body):**

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `learner_id` | string | yes | Who the learner is (`learner.identifier`). |
| `tenant_id` | string | yes | Which state/instance this is (`tenant.identifier`); also used to check the auth token. |
| `sub_session_id` | string | yes | The id of this one diagnostic sitting (`learner_sub_sessions.identifier`). Everything about the session hangs off this id. |
| `class_id` | string | yes | The learner's class (`class_master.identifier`). |
| `grade` | integer (2-8) | yes | The learner's grade (`class_master.sequence`). Grades above 5 are handled as grade 5. |
| `switched_off_question_x_ids` | list of strings | no | The questions that are currently switched off on the app (broken, pulled, being revised) and must never be offered. Optional; if you leave it out, nothing is treated as switched off. See the engine spec Section 7.8. |
| `switched_off_mode` | `"replace"` or `"append"` | no | How the switched-off list is applied. `replace` (the default) makes the list the complete set; `append` adds to whatever the session already had. Only meaningful if `switched_off_question_x_ids` is supplied. |

**Sample request:**

```http
POST /api/v1/diagnostic/session/start
X-Internal-Service-Token: <Delhi secret>
Content-Type: application/json
```
```json
{
  "learner_id": "lrn_9f2c",
  "tenant_id": "Delhi",
  "sub_session_id": "ss_g3_demo",
  "class_id": "cls_774",
  "grade": 3
}
```

**Sample response (200):**

```json
{
  "sub_session_id": "ss_g3_demo",
  "first_question": {
    "question_x_id": "q_dlg3_mul_00537_b",
    "skill_id": "2D x 2D"
  },
  "offline_tree": {
    "available": true,
    "grade": 3,
    "engine_version": "0.10.0",
    "tree_compat_version": 1,
    "size_bytes": 366910,
    "sha256": "3f2a9c...",
    "fetch_path": "/api/v1/diagnostic/offline-tree/Delhi/3"
  },
  "question_budget": 42,
  "resumption_token": {
    "resume_anchor": null,
    "budget_used": 0,
    "answers": []
  }
}
```

The `resumption_token` is the small snapshot the device caches so it can pick up an offline walk correctly (Appendix A.4 and the handover pack). At session start it is empty. If no tree exists for the tenant/grade, `offline_tree` is `null` and the session simply proceeds online - that is not an error here.

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `INVALID_TENANT_TOKEN` | 401 | `X-Internal-Service-Token` does not match the `tenant_id`'s registered token |
| `INVALID_GRADE` | 400 | Grade outside the supported range (2-8) |
| `SESSION_ALREADY_EXISTS` | 409 | An engine session already exists for this `sub_session_id` |
| `NO_USABLE_QUESTION` | 422 | A `switched_off_question_x_ids` list was supplied and it covers every question available for the grade, so the diagnostic cannot start. This is a client-input condition (the caller's list is exhaustive), not a server fault. With no switched-off list, an empty pool instead raises `NO_QUESTION_FOR_SKILL` (below). |
| `NO_QUESTION_FOR_SKILL` | 500 | The question pool has no active question for the chosen skill, with no switched-off list involved. A genuine content-pool gap. |
| `PII_FIELD_PRESENT` | 400 | Request body contains a disallowed field (for example `username`, `name`) |

_(A tenant or grade with no tree is not an error here: `offline_tree` is `null` and the session proceeds online. `NO_TREE_FOR_GRADE` (404) is raised only by the fetch endpoint, Appendix A.9.)_

### A.4 `POST /api/v1/diagnostic/session/:sub_session_id/response`

**When to use it.** Every time the learner answers a question while online. You send the answer (right or wrong); the engine updates its beliefs and hands back the next question, or - if the diagnostic is done - the final verdicts.

**Parameters (request body):**

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `learner_id` | string | yes | Must match the session's learner. |
| `tenant_id` | string | yes | Used to check the auth token. |
| `skill_id` | string | yes | The canonical skill name of the question that was asked. |
| `question_x_id` | string | yes | Which question was asked. |
| `is_correct` | boolean | yes | Whether the learner got it right. This is the **only** input the mastery algorithm uses from this call. |
| `response_time_ms` | integer (>= 0) | no | How long the learner took, in milliseconds. Telemetry only; the algorithm ignores it. |
| `raw_response` | string | no | The learner's actual typed answer. Used only by the misconception classifier (Appendix A.10), never by the mastery algorithm, and never logged. The core mastery pilot does not send it. |
| `switched_off_question_x_ids` | list of strings | no | An updated switched-off list, if it has changed since the last call. Optional; if omitted, the session keeps the list it already had. |
| `switched_off_mode` | `"replace"` or `"append"` | no | How to apply the list above (see Appendix A.3). |

**Sample request:**

```http
POST /api/v1/diagnostic/session/ss_g3_demo/response
X-Internal-Service-Token: <Delhi secret>
```
```json
{
  "learner_id": "lrn_9f2c",
  "tenant_id": "Delhi",
  "skill_id": "2D x 2D",
  "question_x_id": "q_dlg3_mul_00537_b",
  "is_correct": true
}
```

**Sample response (200) - session continuing:**

```json
{
  "session_complete": false,
  "next_question": {
    "question_x_id": "q_mul_00171_z",
    "skill_id": "Tables 1, 2 and 5"
  },
  "questions_asked_so_far": 1,
  "questions_remaining_budget": 41,
  "resumption_token": {
    "resume_anchor": "q_dlg3_mul_00537_b",
    "budget_used": 1,
    "answers": [
      {
        "question_x_id": "q_dlg3_mul_00537_b",
        "is_correct": true,
        "item": "Multiplication|2D x 2D|Fib||37|23",
        "skill_id": "2D x 2D",
        "operation": "Multiplication",
        "asked_at": "2026-07-27T08:44:28.641563+00:00"
      }
    ]
  }
}
```

The `resumption_token` refreshes on every online answer. It carries the last-answered `question_x_id` (`resume_anchor`), the budget used so far, and one entry per answer. The device caches the latest token so that, if the connection drops, its offline walk can resume from exactly where the session left off. It is empty at start and becomes `null` once the session is complete.

**Sample response (200) - session complete:**

```json
{
  "session_complete": true,
  "next_question": null,
  "verdicts": [
    {
      "skill_id": "2-digit Addition with carry",
      "posterior": 0.97,
      "direct_observations": 3,
      "confidence_label": "confident_mastered",
      "recommendation": "skip_maind"
    }
  ]
}
```

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No active engine session for this `sub_session_id` |
| `SESSION_ALREADY_ENDED` | 409 | Session is already complete; start a fresh session |
| `INVALID_SKILL_ID` | 400 | `skill_id` is not in the canonical skill list |
| `LEARNER_MISMATCH` | 400 | `learner_id` does not match the session's learner |
| `RESPONSE_CONFLICT` | 409 | The same `question_x_id` was submitted before with a different `is_correct` (the engine spec Section 8.3) |

**Idempotency.** The same `question_x_id` submitted twice with the same `is_correct` is treated as a duplicate: the engine returns the same next-question response as the first call, without applying the update twice (the engine spec Section 8.3).

### A.5 `POST /api/v1/diagnostic/session/:sub_session_id/end`

**When to use it.** When a session needs to be closed before it finishes on its own - the learner abandoned it, or `aml-api-service` decided to time out the sitting. The engine computes verdicts from whatever has been observed so far.

**Parameters (request body):**

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `learner_id` | string | yes | The session's learner. |
| `tenant_id` | string | yes | Used to check the auth token. |
| `reason` | `"abandoned"` / `"timeout"` / `"learner_quit"` | no | Why the session is being ended. Defaults to `abandoned`. Recorded for analytics; does not change how verdicts are computed. |

**Sample request:**

```http
POST /api/v1/diagnostic/session/ss_g3_demo/end
X-Internal-Service-Token: <Delhi secret>
```
```json
{
  "learner_id": "lrn_9f2c",
  "tenant_id": "Delhi",
  "reason": "timeout"
}
```

**Sample response (200):** the same shape as the session-complete payload in Appendix A.4. Any skill not yet resolved gets a verdict from the posterior-mean rule (the engine spec Section 7.6).

### A.6 `GET /api/v1/diagnostic/session/:sub_session_id/verdicts`

**When to use it.** After a session is complete, when a downstream system wants to read the verdicts again without replaying the session. GET requests carry no body; the session is identified by the path.

**Sample request:**

```http
GET /api/v1/diagnostic/session/ss_g3_demo/verdicts
X-Internal-Service-Token: <Delhi secret>
```

**Sample response (200):** the same verdicts payload shown in Appendix A.4 (session-complete).

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No engine session for this `sub_session_id` |
| `SESSION_NOT_COMPLETE` | 409 | Session is still in progress; verdicts are not final |

### A.7 `GET /metrics`

**When to use it.** Only by the monitoring system (Prometheus), on a schedule. No auth, no parameters. Returns the standard text/plain Prometheus exposition format - default process metrics plus the engine's business metrics (full list in the engine spec Section 9).

### A.8 `GET /health`

**When to use it.** Only by Kubernetes readiness and liveness probes. No auth, no parameters.

**Sample response (200):**
```json
{
  "status": "ok",
  "version": "0.10.0",
  "mongodb": "connected",
  "engine_config_loaded": true,
  "tree_versions": { "2": 7, "3": 7, "4": 7, "5": 7 }
}
```

**Response (failure, 503):** the same shape with `"status": "degraded"` and details on which checks failed.

**Probe semantics:**

| Condition | Status code | Used by |
|---|---|---|
| All checks passing | 200 | Readiness + liveness probes both succeed |
| Config still loading at startup (first 30s) | 503 | Readiness fails; container not yet receiving traffic. Set liveness `initialDelaySeconds >= 30`. |
| Config loaded, MongoDB unreachable | 503 | Readiness fails; existing pods stop receiving new traffic until MongoDB returns. Liveness should NOT fail on MongoDB (restarting will not fix a DB outage). |
| Active tree versions missing for any in-scope (tenant, grade) | 503 | Available but not switched on for the pilot: `/health` reports `tree_versions` and does not fail readiness on a missing tree, since the online path can serve without one. |
| Process unresponsive | (no response) | Liveness times out and kills the container |

**Recommended probe configuration:** readiness `GET /health` every 10s, fail after 3; liveness `GET /health` every 30s with `initialDelaySeconds: 60`, fail after 5 (engineering tunes to actual startup time).

### A.9 `GET /api/v1/diagnostic/offline-tree/:tenant_id/:grade`

**When to use it.** Once, when the device wants offline capability - it fetches the decision-tree bundle referenced by `offline_tree.fetch_path` in the `session/start` response, then caches it by `sha256`. No body; the tenant and grade are in the path.

**Auth:** `X-Internal-Service-Token`, validated against the path `:tenant_id`.

**Grade resolution:** grades 2-5 return their own tree; any grade above 5 returns the grade-5 tree (matching the online `min(grade, 5)` rule).

**Sample request:**

```http
GET /api/v1/diagnostic/offline-tree/Delhi/3
X-Internal-Service-Token: <Delhi secret>
```

**Sample response (200):** the canonical tree JSON for the (resolved-grade, tenant) bundle - the four per-operation trees, the shared per-grade parameters block, the parallel `items` array, `tree_compat_version`, and the `manifest` of every `question_x_id` the trees can reach. The bytes and `sha256` match the reference returned at `session/start`.

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `NO_TREE_FOR_GRADE` | 404 | No tree exists for this tenant/grade (for example a non-Delhi tenant, or a grade below 2). This is the only place `NO_TREE_FOR_GRADE` is raised. |
| `INVALID_TENANT_TOKEN` | 401 | `X-Internal-Service-Token` does not match the path `:tenant_id` |

### A.10 `GET /api/v1/diagnostic/session/:sub_session_id/responses`

**When to use it.** After a session, when the misconception classifier (Stage B) needs the learner's raw typed answers. The mastery algorithm does not use these; they exist only for answers where `aml-api-service` supplied `raw_response` (Appendix A.4). No body; the session is in the path.

**Auth:** `X-Internal-Service-Token`, validated against the session's tenant.

**Sample request:**

```http
GET /api/v1/diagnostic/session/ss_g3_demo/responses
X-Internal-Service-Token: <Delhi secret>
```

**Sample response (200):**

```json
{
  "sub_session_id": "ss_g3_demo",
  "learner_id": "lrn_9f2c",
  "grade": 3,
  "responses": [
    { "question_x_id": "q_dlg3_mul_00537_b", "raw_response": "851", "is_correct": true, "skill_id": "2D x 2D" }
  ]
}
```

Entries whose `raw_response` was not supplied come back with `raw_response: null`. The raw answer is never written to logs or metrics (the engine spec Section 6.3).

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No engine session for this `sub_session_id` |
| `INVALID_TENANT_TOKEN` | 401 | Token does not match the session's tenant |

### A.11 `POST /api/v1/diagnostic/session/:sub_session_id/offline-batch`

**When to use it.** When a device that was answering offline reconnects, to fold that offline stretch back into the one session. You send the batch of answers the learner gave offline; the engine merges them into the single unified history, re-scores, and returns the next question (or the verdicts, if the session is now done). This is the heart of mixed-mode - see the offline-walk handover pack for the full picture.

**Parameters (request body):**

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `learner_id` | string | yes | The session's learner. |
| `tenant_id` | string | yes | Used to check the auth token. |
| `resume_anchor` | string | no | The `question_x_id` of the last answer recorded before the device went offline (copied from the resumption token). It tells the engine where the offline stretch slots in. Optional; if absent, the batch is appended at the end and flagged. |
| `tree_id` | string | yes | Which offline tree the device walked. |
| `tree_version` | integer | yes | The version of that tree. |
| `tree_compat_version` | integer | yes | The compatibility marker of that tree. If it does not match the engine's current marker, the answers are still accepted and a "stale tree" flag is raised (the answers are valid; only the tree was old). |
| `answers` | list of answer objects | yes | The offline answers, in order. Each object is described below. |
| `switched_off_question_x_ids` | list of strings | no | An updated switched-off list, if it changed. Optional (see Appendix A.3). |
| `switched_off_mode` | `"replace"` or `"append"` | no | How to apply the list above. |

Each entry in `answers`:

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `question_x_id` | string | yes | Which question was answered offline. |
| `skill_id` | string | yes | The skill of that question. |
| `is_correct` | boolean | yes | Whether the learner got it right. |
| `raw_response` | string | yes | The learner's typed answer. **Required** for offline answers (unlike the online call), so the misconception classifier gets the same input it would have online. |
| `asked_at` | timestamp | yes | When the question was answered, so the engine can place the answers in the correct order. |

**Sample request:**

```http
POST /api/v1/diagnostic/session/ss_g3_demo/offline-batch
X-Internal-Service-Token: <Delhi secret>
```
```json
{
  "learner_id": "lrn_9f2c",
  "tenant_id": "Delhi",
  "resume_anchor": "q_dlg3_mul_00537_b",
  "tree_id": "Delhi-3",
  "tree_version": 7,
  "tree_compat_version": 1,
  "answers": [
    {
      "question_x_id": "q_mul_00902_z",
      "skill_id": "2D x 1D",
      "is_correct": true,
      "raw_response": "96",
      "asked_at": "2026-07-27T08:45:10.000000+00:00"
    },
    {
      "question_x_id": "q_mul_00192_z",
      "skill_id": "Repeated addition",
      "is_correct": false,
      "raw_response": "12",
      "asked_at": "2026-07-27T08:45:38.000000+00:00"
    }
  ]
}
```

**Sample response (200):** the same shape as a `/response` result. If the learner continues online, `session_complete` is `false` and a `next_question` and refreshed `resumption_token` are returned, now reflecting the offline answers; if the diagnostic is done, `session_complete` is `true` with the `verdicts`.

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No active engine session for this `sub_session_id` |
| `RESPONSE_CONFLICT` | 409 | An answer in the batch contradicts one already recorded for the same `question_x_id` (the engine spec Section 8.3) |
| `OFFLINE_BATCH_TOO_LARGE` | 400 | The batch is implausibly large (more than twice the grade budget) - a corruption guard. A correct device never sends this. |

**Notes.** The engine re-scores by replaying the whole unified history in order (not by adding the batch on top), so the verdicts are exactly what a fully-online session on the same answers would produce (verdict neutrality, the engine spec Section 7.10). Sending the same batch twice is a harmless no-op (idempotent). An answer to a question that has since been switched off is still accepted and scored - switched-off governs future offering, not the validity of an answer already given.

### A.12 `POST /api/v1/diagnostic/session/:sub_session_id/replace-question`

**When to use it.** When the engine offered a question the app cannot actually show right now - most often a broken media asset the engine could not have known about - and you need a different one for the same turn. The engine drops the declined question and returns a replacement, recording nothing and spending no budget. This is the deactivation failsafe's reactive path (the switched-off list is the proactive one; see the engine spec Section 7.8).

**Parameters (request body):**

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `learner_id` | string | yes | The session's learner. |
| `tenant_id` | string | yes | Used to check the auth token. |
| `question_x_id` | string | yes | The question being declined - the one the app cannot show. |

**Sample request:**

```http
POST /api/v1/diagnostic/session/ss_g3_demo/replace-question
X-Internal-Service-Token: <Delhi secret>
```
```json
{
  "learner_id": "lrn_9f2c",
  "tenant_id": "Delhi",
  "question_x_id": "q_mul_00171_z"
}
```

**Sample response (200):**

```json
{
  "session_complete": false,
  "next_question": {
    "question_x_id": "q_mul_00902_z",
    "skill_id": "2D x 1D"
  },
  "questions_asked_so_far": 1,
  "questions_remaining_budget": 41
}
```

The declined question is not recorded, does not count against the budget, and is not offered again for the rest of this session. It joins a separate transient set - it is **not** added to the switched-off list, because declining one question for a display glitch is different from a content-level deactivation. If no usable question remains, the response comes back with `session_complete: true` and the verdicts, exactly as when selection is otherwise exhausted.

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No active engine session for this `sub_session_id` |
| `SESSION_ALREADY_ENDED` | 409 | Session is already complete |
| `LEARNER_MISMATCH` | 400 | `learner_id` does not match the session's learner |

---

## Appendix B: Offline-walk handover pack for the AML app team

This section is a step-by-step guide for the AML app team building the offline walk in TypeScript inside `aml-portal`. It is written to stand on its own: read it top to bottom and you have everything needed to build, test, and scope the work. (The same pack appears in the engine spec, Section 17; the two are kept identical.)

### B.1 What you are building, and what you are not

You are building the part that **chooses and records questions while the device is offline**. You are **not** building anything that scores or judges mastery - that stays on the server. Keeping this line clear is the single most important thing in this pack.

| Job | Who does it |
|---|---|
| Show the learner a question and read their answer | `aml-portal` (you), online and offline |
| While online: ask the engine for the next question | `aml-api-service` -> engine (`/response`) |
| While offline: choose the next question by following the downloaded tree | `aml-portal` (you) - this is the offline walk |
| Mark each answer right or wrong | `aml-portal` (you) - a simple correctness check, the same one used online |
| Record each answer locally (id, skill, correctness, the typed answer, and when) | `aml-portal` (you), in IndexedDB |
| On reconnect: send the offline answers to the engine | `aml-portal` -> `aml-api-service` -> engine (`/offline-batch`, Appendix A.11) |
| Turn answers into mastery verdicts | the **engine**, server-side, when the batch is ingested |
| Produce the final learning state (verdict + misconception tag) | the **data team**, downstream |

So the device sequences, marks, records, and syncs. It does not compute posteriors or verdicts, and it does not need the calibration parameters for scoring - the tree already encodes every branch the walk needs.

### B.2 What you receive

Three artifacts travel with this pack. They are the contract: build against them, and the port is correct by construction.

| Artifact | What it is | How you use it |
|---|---|---|
| `offline_follow.py` (the walk reference) | The Python source of the exact walk: `follow_capped(...)`, the replay-to-first-unanswered entry point, and the skip-and-do-not-record rule. It is small and readable. | Port its logic to TypeScript, line-for-line in behaviour. It is the specification of "what to ask next," in runnable form. |
| `vectors/offline_walk_vectors.json` (the shared test vectors) | A set of recorded walks: for each case, the inputs (grade, the answers given) and the exact question sequence the walk must produce. Covers fresh starts, resumed walks (online-then-offline), all-correct / all-wrong / mixed answer patterns, and the unavailable-question skip. | Your TypeScript port must reproduce every vector's sequence and count exactly. This is your acceptance test (Appendix B.5). |
| `offline_followsim.py` (the harness) | The Python harness that runs the walk in bulk and checks it against the engine. | Reference only - it shows how the walk is exercised and how equivalence is checked; you do not port it. |

### B.3 The model: port, do not embed

Port the **walk logic** into TypeScript. Do not try to run or embed the Python engine on the device, and do not reimplement scoring. The division of material is:

- **The tree and its parameters** come from the engine, already built, via the offline-tree endpoint. You download and cache them; you do not compute them.
- **The walk** (which node to visit next, when to stop) is the logic you port from `offline_follow.py`.
- **Scoring** never happens on the device. You record answers and sync them; the engine scores.

The reason this is safe: the walk is pure "follow the tree by correctness," with no probability maths. All the hard maths (posteriors, the lattice, verdicts) lives on the server and runs on the synced history.

### B.4 The offline walk, step by step

**Step 1 - Get the tree and keep it.** When the learner starts (online), `session/start` returns an `offline_tree` reference (Appendix A.3). If you want offline capability, fetch the actual tree once from its `fetch_path` (the offline-tree endpoint, Appendix A.9) and cache it by `sha256` in IndexedDB. The bundle holds the four per-operation trees (Addition, Subtraction, Multiplication, Division), the shared per-grade parameter block, and a `manifest` of every `question_x_id` the trees can reach - pre-load the content for those ids so you can show any question offline.

**Step 2 - Keep the latest resumption token.** `session/start` and every online `/response` return a small `resumption_token` (Appendix A.4): the last-answered question (`resume_anchor`), the budget used, and one entry per answer so far. Overwrite your cached copy every time. This token is how the offline walk knows where the session already is.

**Step 3 - When the connection drops, find the entry point.** Do not start the tree from the top. Take the answers from the resumption token and "replay" them into the tree: for each operation, start at the root and follow the recorded correctness (correct -> the on-correct child, wrong -> the on-incorrect child) as long as the node's question has already been answered. The first node whose question has **not** been answered is your entry point - that is the first question to ask offline. Match answered questions by their **content** (the `item` a node resolves to), not by the raw `question_x_id`, because the online path and the tree can use different id variants of the same question.

![Offline resume: finding the entry point](img/mixed_mode_entry_point.png)

**Step 4 - Walk the tree (base-first, three passes, one budget).** Sweep the four operations in the fixed order **Addition, Subtraction, Multiplication, Division**, and make three passes over them, all under one hard question budget for the grade (25 / 42 / 59 / 76 for G2 / G3 / G4 / G5):

1. **Base pass** - walk each operation's tree up to that operation's base cap.
2. **Misconception backfill** - continue a little past the base cap to cover misconceptions not yet seen, up to the per-operation allowance.
3. **Skill harvest** - if budget remains, ask a few more to settle still-uncertain skills.

At each node you ask its question, read the answer, mark it right or wrong, and move to the on-correct or on-incorrect child. Never ask the same content twice (the no-repeat check is in `item` space, as in Step 3). Stop the moment the grade budget is reached - it is a hard cap and must never be exceeded.

**Step 5 - The skip-and-do-not-record rule.** If the walk lands on a node whose question you cannot actually show - most often because it was switched off on the app after the tree was built - do this: **skip the node, follow its on-incorrect branch, record nothing, and spend no budget.** Treat "cannot show" exactly as "not asked." Do not guess an answer, and do not count it. (This mirrors the engine's own handling of switched-off questions online, the engine spec Section 7.8.)

**Step 6 - Record every answer locally.** For each question actually answered, store in IndexedDB: `question_x_id`, `skill_id`, `is_correct`, the learner's typed answer (`raw_response`), and `asked_at` (a timestamp). You will need all five when you sync.

**Step 7 - On reconnect, sync the batch.** Send the recorded offline answers to the engine via `POST .../offline-batch` (Appendix A.11), including the `tree_id`, `tree_version`, and `tree_compat_version` of the tree you walked, and the `resume_anchor` from your token. The engine folds the batch into the one session, re-scores the whole history, and returns the next question (if the learner continues) or the final verdicts. Sending the same batch twice is harmless. If the learner keeps switching between online and offline, repeat these steps - the session is a single unified thing and can switch any number of times.

### B.5 How you know the port is correct (the acceptance bar)

The bar is exact reproduction of the shared vectors. For every case in `vectors/offline_walk_vectors.json`, feed your TypeScript walk the same inputs and confirm it produces the **same question sequence and the same count** - no more, no less, in the same order. Wire this as an automated test in the `aml-portal` build so a future change cannot silently drift from the engine. If every vector passes, the walk is correct; the vectors were generated from the engine's own walk, so matching them means matching the engine.

### B.6 Scope: what is in, and what is deferred

- **In scope:** a session that starts **online** and then goes offline (with the resumption token in hand), any number of switches, and syncing each offline stretch back through `offline-batch`. This is the pilot's mixed-mode.
- **Deferred:** a **never-connect cold start** - running the whole diagnostic on a device that has never been online and so never received a resumption token or a fresh tree. That is a later phase and is not part of this pack.
