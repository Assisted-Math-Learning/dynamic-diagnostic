# Dynamic Diagnostic Engine - Engineering Specification

**Version:** v10 document set; engine **0.10.0** (this revision folds in the mixed-mode online/offline switching and the deactivation failsafe, which took the engine from 0.9.0 to 0.10.0). The measured outcome numbers were taken on the verdict-neutral 0.9.0 baseline and are unchanged at 0.10.0.
**Date:** July 2026
**Audience:** AML engineering team
**Status:** Engine, routing, question selection, calibration, the offline path (served to the client as a downloadable reference plus a fetch endpoint, Sections 4 and 5.9), raw-response persistence for the misconception classifier (Sections 5.4, 5.10, and 6.3), the in-process misconception-classifier integration, the **mixed-mode online/offline switching** (Sections 4, 5.11, 7.10, and the handover pack in Section 17), and the **deactivation failsafe** (Sections 5.11, 5.12, and 7.8) are all built and verified against engine **0.10.0 (668 tests passing)**. Mixed-mode and the failsafe were the MINOR change that took the engine from 0.9.0 to 0.10.0; both are **verdict-neutral** (they change how and when questions are delivered, never how an answer is scored), so the measured outcome numbers in this document - taken on the 0.9.0 baseline (see Section 1 and the comparison report) - are unchanged at 0.10.0. Section 16 records the resolved engineering decisions; remaining build and operational items are noted there and in Sections 10, 14, and 15.

---

## 1. Overview

The dynamic diagnostic engine is a new service in the AML platform that decides which questions a learner sees during a diagnostic session, and produces a per-skill mastery verdict at the end. It replaces the static diagnostic that ran in Delhi from April-May 2026.

The current static diagnostic asks every learner the same set of questions, in the same order, regardless of how they are doing. The dynamic engine instead picks each next question based on what the learner has already got right or wrong. Strong learners answer fewer questions on skills they have clearly mastered; weak learners answer fewer questions on skills they clearly have not.

Measured against learners' real entry mastery records - with question responses simulated from a fixed 0.90/0.15 model - using engine 0.9.0 (500 learners per grade, G2-G5, three replicates, 42,693 scored skill-rows), the value of the engine is in three things, in order of importance:

1. **More accurate where it commits, through calibrated abstention.** When the engine commits to a confident verdict, it is right 93.3% online and 96.0% offline, versus 86.9% for the static diagnostic. This confident-only figure is not a like-for-like comparison: the engine only commits on the skills it is confident about (coverage 92.4% online, 80.1% offline) and routes the rest to MainD rather than guessing. (By contrast the static diagnostic has more than one question for only about 47% of individual L2.5 skills, so it can reliably assess only about half of them at that level - which is why it reports at grade + L1-skill level; see the comparison report Section 3.) Counting every skill (uncertain treated as not-mastered) the accuracy is 89.0% online and 87.4% offline versus 86.9% static - a smaller edge. The distinctive property is the abstention itself: the engine declines to commit on the hard cases instead of committing to a wrong answer.
2. **Safer skips.** The false-skip rate (flagging a not-yet-mastered skill as mastered, so the learner wrongly skips practice) is 3.4% online and 2.1% offline, versus 3.8% static.
3. **Fewer downstream MainD questions.** For each skill it confidently masters, a learner skips that skill's MainD questions: about 27.0 per learner online and 25.6 offline, 96-98% of them correct (a lower bound, measured only on skills with entry ground truth). Counting the diagnostic and MainD together, that is on the order of 30 fewer questions per learner overall online (roughly 4 from the diagnostic plus 27 from MainD), almost all of it the MainD saving.

The engine's value is **not** mainly in cutting diagnostic questions. Direct question savings are modest and shrink with grade (about 8% overall online, 15% at G2 down to 4% at G5) and are near zero offline, because the offline path deliberately spends its budget on coverage. The gains are accuracy, safety, and the downstream MainD savings above.

**Measured performance (engine 0.9.0).** The table below is the per-grade summary; the full method, calibration tables, and caveats are in the comparison report. Sample: 500 learners per grade, three replicates, the same learners across all three arms, scored against `entry_mastered` ground truth. Confident accuracy and coverage are over confident decisions only; false-skip is the share of `confident_mastered` skills that are actually not mastered.

| Grade | Static acc | Online conf acc | Online coverage | Offline conf acc | Offline coverage | Static false-skip | Online false-skip | Offline false-skip | MainD saved (online / offline) |
|---|---|---|---|---|---|---|---|---|---|
| G2 | 0.846 | 0.927 | 0.901 | 0.959 | 0.867 | 0.014 | 0.023 | 0.017 | 16.1 / 15.9 |
| G3 | 0.877 | 0.922 | 0.941 | 0.961 | 0.780 | 0.042 | 0.049 | 0.021 | 24.1 / 21.5 |
| G4 | 0.871 | 0.934 | 0.935 | 0.960 | 0.843 | 0.045 | 0.038 | 0.024 | 30.6 / 28.9 |
| G5 | 0.869 | 0.941 | 0.912 | 0.959 | 0.758 | 0.039 | 0.027 | 0.020 | 37.3 / 36.2 |
| **Overall** | **0.869** | **0.933** | **0.924** | **0.960** | **0.801** | **0.038** | **0.034** | **0.021** | **27.0 / 25.6** |

Direct in-diagnostic savings (not the headline): online 8.1% overall (15.2% at G2 to 4.2% at G5), offline 3.6% overall. Calibration at the confident-mastered end: a `confident_mastered` verdict is correct 96.6% of the time online and 97.9% offline (this is `1 - false-skip`).

This document specifies how the engine works at the system boundary: its API, its data model, the algorithm it runs, the way it integrates with `aml-api-service` and MongoDB, and what the engineering team needs to know to build, deploy, and operate it in production.

### Where the engine sits

The engine is a new HTTP service. It never talks to learners directly. It receives requests only from `aml-api-service`, which has already validated the learner's JWT and scored the learner's response.

![Where the engine sits: the online request/response path across aml-portal, aml-api-service, and the engine](img/online_api_flow.png)

### Current integration status (as of this version)

The diagram above is the target. As of this version the engine is **not yet integrated into the live AML product**. The findings below come from a direct review of the `aml-api-service` and `aml-portal` repositories and shape the implementation work (full detail is in the implementation specification):

- **The live diagnostic today is the old static one,** run server-side. The entry diagnostic is a static chain-walk over (class, L1-skill) question sets with a threshold pass/fail and a two-consecutive-fails skip rule (`entryDiagnostic.helper.ts`, reached from `POST /learner/evaluate/:learner_id`). There is no Bayesian, DINA, or adaptive engine in the codebase today, and no client-side sequencing. Integrating the dynamic engine is new wiring, not a swap of an existing adaptive component.
- **The per-question attempt-history schema already exists.** `aml-api-service` stores per-question attempt records (`learner_proficiency_question_level_data`) including `question_id`, the full taxonomy down to `l2_5_skill`, per-question score, attempt number, and session id. This is what the offline history scorer (§7.10) needs. One dependency remains (C-1): `question_id` here is finer-grained than the engine's `question_x_id` - many `question_id`s map to one `question_x_id`, and each `question_id` resolves to exactly one - so the scorer must translate `question_id` -> `question_x_id` before replaying, and that mapping must be available where the scorer runs. The schema itself is confirmed present; the mapping is the open item.
- **The portal already has an offline-first learner-response pipeline.** `aml-portal` records learner responses in IndexedDB with a sync lifecycle and reconciliation sagas. The device-side recording the offline path depends on is largely in place; what is missing for offline is the on-device tree-walk loop (the three-pass follow), which is small and engine-free by design and would be ported to the portal's language.
- **Shape of integration.** The online engine is already a deployable Python service over the same datastore family and deployment model as AML, so it integrates as a sibling service the Node backend calls over HTTP (it is not ported into the Node process). The real work is AML-side glue: identifier mapping between engine skill/question ids and the AML taxonomy (the L2.5 skill layer is shared, which makes the skill side tractable), the set-versus-question bridge, and routing verdicts back into the learner's tailored sequence.

---

## 2. Background and scope

### Why the engine exists

The static diagnostic asks a fixed number of questions per skill (between 1 and 4 each, depending on grade), in a fixed order. Because the order is fixed and the question count is the same for everyone, learners who clearly know a skill answer the same number of questions as learners who clearly do not.

Two consequences:

1. **Wasted questions.** Strong learners spend time on questions whose outcome is predictable. Weak learners spend time on skills they cannot possibly demonstrate yet.
2. **The diagnostic does not adapt.** Whether a learner has shown perfect mastery of Addition does not change how many Subtraction questions they get. Whether they have failed every Subtraction question does not stop the diagnostic from asking more.

The dynamic engine fixes both. It adapts question selection based on running estimates of mastery, stops asking questions on a skill once it is confident either way, and uses the relationship between skills to draw inferences without direct evidence.

### What is in scope

| Item | Scope |
|---|---|
| Arithmetic operations | Four: Addition, Subtraction, Multiplication, Division |
| L2.5 skills | 39 in the Delhi scope; 40 across all tenants (canonical list in Appendix C) |
| Learner grades | G2 through G5 are the primary scope. G6, G7, G8 learners use the G5 skill set and question budget. |
| Question pool | Any question tagged `purpose IN ('Main Diagnostic', 'Micro Diagnostic', 'Exit Main Diagnostic')`, plus questions from the legacy Delhi static diagnostic (`question_x_id` prefix `q_dlg`) |
| Deployment | One central engine service. All state-specific AML instances (Delhi, Karnataka, Telangana, etc.) call this same engine |

### What is out of scope

| Item | Out of scope because |
|---|---|
| Numbers operation | In the Delhi static diagnostic, learners answered only 4 questions on Numbers, all from a single skill. That left calibration data too thin to estimate priors reliably. The content team's call was to drop Numbers from the diagnostic on this basis. Place-value misconceptions (the main thing Numbers questions assess) can still be identified after the diagnostic, from learners' answers on other operations, using the misconception classifier.

To enable this change, the following content logic / rules need to be implemented:
- if the verdict for the ‘2-digit addition without carry’ skills is either uncertain or confident_not_mastered in the Dynamic Diagnostic (i.e., the recommendation for ‘2-digit addition without carry’ is either take_maind_diagnostic or take_maind_confirmation), then the learner needs to take the MainD for both ‘Numbers’ and ‘2-digit addition without carry’.
- if the verdict for ‘2-digit addition without carry’ is confident_mastered in the Dynamic Diagnostic (i.e., recommendation for ‘2-digit addition without carry’ is skip_maind), then the learner needs to take the MainD for both ‘Numbers’ and ‘2-digit addition without carry’. |
| Cold-start offline support | Learners must be online at session start. The PWA work to support a completely offline first launch is not yet ready and is a separate decision |
| Item authoring or content editing | The engine reads existing questions; it does not create or modify them |
| Question rendering | `aml-portal` renders questions. The engine never sees question content, only `question_x_id`s |
| Response scoring | `aml-api-service` scores responses using the existing `getScoreForTheQuestion` function. The engine receives a Boolean `is_correct`, not the raw response |
| Multi-engine horizontal scaling | V1 is single-instance. If concurrency demands grow, scaling is a v2 concern requiring shared session state via Redis or similar |

### What this replaces and what it does not

The engine replaces the Delhi static diagnostic specifically. It does NOT replace:

- The MainD question set (the regular learning content)
- The Micro Diagnostic and Exit Main Diagnostic question sets (these continue to exist; the engine just pulls questions from them as part of its pool)
- The authoring tool, the analytics layer, or any other AML subsystem

---

## 3. Glossary

These terms appear throughout the spec. Plain definitions; mathematical detail is in Section 7.

| Term | Definition |
|---|---|
| **L2.5 skill** | A unit of mathematical ability the engine tracks separately, like "2-digit Addition with carry" or "Tables of 7". The engine works with 39 in the Delhi scope, and 40 across all tenants. |
| **Mastery** | The hidden state of "the learner knows this skill". It cannot be observed directly; the engine estimates it from how the learner answers questions. |
| **Posterior** | The engine's running estimate of how likely it is that a learner has mastered a specific skill, expressed as a number from 0 to 1. For example, 0.9 means the engine is 90% sure the learner has mastered the skill. Updated every time the learner answers a related question. |
| **Prior** | The starting posterior - what the engine believes about a learner's mastery before they have answered any questions. Calculated from how other learners in the same grade have done on the same skill in past data. |
| **Slip** | The chance that a learner who actually knows a skill still gets a question on it wrong - maybe a careless mistake, a misread, or a typo. 10% is a fallback default; where a question has been calibrated, the engine uses that question's own measured slip instead (§7.7). |
| **Guess** | The chance that a learner who does NOT know a skill still gets a question on it right - a lucky guess, especially on multiple-choice questions. 15% is a fallback default; where a question has been calibrated, the engine uses that question's own measured guess instead (§7.7). |
| **Lattice** | A small graph of 12 connections between skills. Each connection captures a known relationship, like "a learner who can do 2-digit Multiplication can probably also do 1-digit Multiplication". This lets the engine use evidence about one skill to update what it believes about a related one, without asking a direct question on the related one. |
| **Propagation** | When the engine uses a lattice connection to update its belief about one skill after seeing the learner's answer on a related skill. Saves direct questions. |
| **Sub-session** | How AML already tracks a single learning activity - a diagnostic, a question set, a content piece - that a learner sits down to do. Stored in the `learner_sub_sessions` MongoDB collection. The engine's session is always one-to-one with a sub-session created by `aml-api-service`. |
| **Three-band verdict** | The engine's final output per skill at the end of a session: one of `confident_mastered`, `uncertain`, or `confident_not_mastered`. Plus a recommendation for downstream: `skip_maind`, `take_maind_diagnostic`, or `take_maind_confirmation`. |
| **Hybrid mode** | Running the engine in two ways at the same time. The default is a live online service that picks each next question on demand. When connectivity drops, the client falls back to a pre-built tree shipped to the device. Same algorithm runs either way. |
| **Option 1, Option 4** | The names for the two ways the engine picks questions. Option 4 is online: the engine picks each next question when the response comes in. Option 1 is offline: a pre-built tree, generated in advance, tells the client which question to ask next based on the learner's responses so far. Same algorithm; one runs live, the other is computed ahead of time. |
| **MainD** | The "Main Diagnostic" question set in AML - the post-diagnostic content that decides where in the curriculum a learner is placed. The engine's verdict decides whether the learner skips MainD, takes the full MainD, or takes a shorter confirmation version. |
| **CDM (Cognitive Diagnostic Model)** | A family of statistical models from education research that estimate which skills a learner has mastered, using their question responses. The engine borrows vocabulary from this family (slip, guess, mastery) but does not implement any specific named model from it. Section 7 explains what the engine actually does. |
| **`question_x_id`** | The content identifier for a question (`question_set_x_id` is the equivalent for a question set). Its base value is consistent across AML instances/tenants, sometimes with a tenant-specific suffix (for example `_c1`, `_z`); the base part is shared. The engine returns and stores `question_x_id` for question references. Two facts shape how it is used (see §7.8): a given `question_x_id` exists in only one tenant's `questions` collection, and within a tenant several distinct questions (each with its own `question_x_id`) can share the same content `item` key. |
| **`item`** | The content key the engine selects on, formed from `Q L1 Skill \| Q L2.5 Skill \| Q Type \| Q Text \| Q N1 \| Q N2`. Calibration is keyed on `item`. One `item` can map to several `question_x_id`s within a tenant; the per-tenant lookup resolves an `item` to one `question_x_id` (§7.8). |
| **`identifier`** | A per-instance UUID-style identifier on most AML collections. Different states have different `identifier` values for the same content. The engine uses `identifier` for learner-side references (learner, tenant, sub-session, class, skill) and `question_x_id` for content (questions, question sets). |

---

## 4. High-level architecture

### The hybrid pattern

The engine supports two routing modes. Both run the same algorithm and share the same engine state.

![Engine architecture: online request path, offline tree path, and tree generation](img/architecture.png)

| Mode | When used | How questions get picked |
|---|---|---|
| **Option 4 - server-side adaptive (primary)** | Online sessions. Default when the client has connectivity. | `aml-api-service` calls the engine after every learner response. Engine returns the next question's `question_x_id`. |
| **Option 1 - precomputed trees (offline fallback)** | When the learner's device loses connectivity mid-session. | The client falls back to decision trees returned by the engine at session start. The trees (four per-operation trees per grade) were pre-generated by a batch job; the client receives a small reference at `POST /diagnostic/session/start` and fetches the tree once from the fetch endpoint (Section 5.9), caching it for offline use. |

A session is **one unified thing** that can switch between online and offline any number of times (mixed-mode). While offline, the device follows the tree and records answers locally, holding a small **resumption token** (Section 5.4) so it always knows where the session already is. When connectivity returns, the client sends the offline stretch to the engine as a batch through `POST /session/:sub_session_id/offline-batch` (Section 5.11); the engine folds it into the single session history, re-scores by replaying the whole history in order, and returns the next question or the final verdicts. Section 17 is the step-by-step build guide for the device side of this.

![Mixed-mode: one session across online and offline](img/mixed_mode_handoff.png)

The architectural reason this works: the engine is a pure function of its inputs. Given the same starting prior and the same sequence of responses, it produces the same posteriors, the same next-question decisions, and the same verdicts, regardless of whether each response arrived live or was replayed from an offline batch. Mixed-mode is therefore **verdict-neutral**: splitting a session across online and offline does not change its verdicts (Section 7.10).

### The online path, end to end

The typical flow for a single question:

1. The learner taps an answer in `aml-portal`.
2. `aml-portal` POSTs the response to `aml-api-service` (authenticated by the learner's JWT).
3. `aml-api-service` validates the JWT, looks up the question, calls `getScoreForTheQuestion` to compute a Boolean `is_correct`.
4. `aml-api-service` POSTs to the engine: `POST /diagnostic/session/:sub_session_id/response` with `{learner_id, tenant_id, skill_id, question_x_id, is_correct}`. Auth is the shared-secret header (Section 5).
5. The engine updates posteriors, possibly propagates evidence over the lattice, and decides what to do next:
   - If session is not complete, it returns the next `question_x_id` (an `question_x_id`) and the corresponding `skill_id`.
   - If session is complete, it returns the three-band verdict per skill plus a session-end signal.
6. `aml-api-service` receives the next `question_x_id`, fetches the full question content from MongoDB by `question_x_id`, and returns it to `aml-portal`.
7. `aml-portal` renders the question.

The engine never sees question content, never sees the learner's raw response, never sees the JWT, and never sees any PII (no usernames, no names, no school, no human-readable tenant name).

### The offline path at the engine boundary

The engine produces decision trees for offline use. For each (tenant, grade) the artifact is a **set of four per-operation trees** (Addition, Subtraction, Multiplication, Division), not a single tree. The trees are NOT generated on demand. They are generated by a separate batch job and shipped as a file artifact - one gzipped bundle per (tenant, grade), which the engine serves through a dedicated fetch endpoint (Section 5.9); see Section 6.

**When trees are generated:** Whenever an input the trees depend on changes - the priors, the lattice, the anchors, the canonical skill list, the per-item calibration, or a tenant's active-question list (Section 10.5). The engine team runs the batch job and writes one bundle per (tenant, grade) into the artifact directory (`OFFLINE_ARTIFACT_DIR`).

**How the trees get to the client:** When `POST /diagnostic/session/start` is called, the engine resolves the bundle for the learner's tenant and grade and returns a small **reference** in the `offline_tree` field - `{available, grade, engine_version, size_bytes, sha256, fetch_path}` - not the tree itself. The client fetches the actual tree from that `fetch_path` (Section 5.9) once, when it wants offline capability, and caches it by `sha256`. The tree is not inlined because it is large: the largest grade (G5) is about 5.4 MB compressed on disk, and the client downloads about 24.8 MB of canonical JSON (the size the `offline_tree` reference advertises in `size_bytes`) - far too big to attach to every session-start response. **Grade fallback:** grades 2-5 resolve to their own tree; any grade above 5 resolves to the G5 tree (matching the online engine's `min(grade, 5)` rule); a tenant or grade with no tree returns `offline_tree: null` and never an error. Sizes per grade are in Section 10.5.

**How the client walks the trees (the three-pass base-first follow).** Each node is a routing step: "ask the question with `question_x_id` X; if correct go to child A, if incorrect go to child B." The node's `question_x_id` is the one resolved for this tenant (Section 7.8). The client runs three passes, each sweeping the four operations in the fixed order Addition, Subtraction, Multiplication, Division, all under one hard question budget for the grade:

1. **Base pass:** walk each operation's tree up to that operation's base cap (G2 6 / G3 9 / G4 13 / G5 16).
2. **Misconception backfill (always on):** continue past the base cap to ask questions that cover misconceptions not yet seen, up to the locked per-operation allowance.
3. **Skill harvest:** if budget remains within the allowance, ask additional questions to settle still-uncertain skills.

![The offline three-pass base-first follow](img/offline_three_pass.png)

The hard grade budget (25 / 42 / 59 / 76) is never exceeded; the verified over-budget fraction is 0.000 at every grade. The client makes no network call during the session. The trees reference questions only by `question_x_id`, so `aml-portal` must already have the content for any `question_x_id` a tree can reach.

**How an offline session is scored.** The device does not compute verdicts. It records each attempt (`question_x_id`, `skill_id`, correctness, and the raw answer for the classifier) during the walk, and on the next sync it sends the batch to the engine via `POST .../offline-batch` (Section 5.11). The server replays the full unified attempt history through the engine's own update and verdict functions (the "history scorer," Section 7.10) to produce verdicts identical to an online session on the same answers. This was verified to match the online engine exactly over 420 sampled sessions (8,820 skill comparisons), plus a several-hundred-session mixed-mode sweep with zero mastery-verdict mismatches, and is source-agnostic (a session that was partly online and partly offline scores the same as a fully-online one on the same history).

**What is out of scope for v1.** How the client delivers the question content matching the `question_x_id`s - whether bundled at app install time, downloaded at session start, or fetched on demand - is an `aml-portal` decision, not an engine decision. The current static diagnostic in `aml-portal` already downloads the full diagnostic at session start; the engine's offline bundle fits that pattern. PWA-specific cold-start offline support (running the diagnostic without ever connecting) is deferred to a later phase.

**The deactivation failsafe.** A question can be pulled from the app (a broken asset, a content fix) faster than the engine's own data updates. Three mechanisms handle this without ever changing how an answer is scored: an optional **switched-off list** the caller passes on the selecting endpoints so the engine never offers those questions (Section 7.8); a **replace-question** endpoint to swap out a single question the app cannot show right now (Section 5.12); and, offline, the device's **skip-and-do-not-record** rule for an unavailable node (Section 17.4). All three change coverage, never scoring.

### Horizontal scaling

V1 runs as a single instance. The engine is logically stateless (all session state lives in MongoDB), so multiple instances would work in principle. The catches that make scaling a step beyond v1:

- Two instances handling the same `sub_session_id` could write conflicting state if calls arrive concurrently. Resolving this needs the per-session lock described in Section 8.6 (AML already uses Redis with Redlock for this pattern elsewhere). The lock design is settled; only its expiry value is finalized after the pilot.
- The current code loads priors, lattice, calibration, the per-tenant lookup, and the canonical skill list at startup. Hot-reloading them across instances requires either a restart-on-change policy or a config-refresh mechanism.

If peak concurrency (Section 16, item 10) is below a few hundred concurrent sessions, a single instance is fine for v1.

### Multi-tenancy

All state-specific AML instances (Delhi, Karnataka, Telangana, future states) call the same engine. The engine identifies the calling instance via the per-tenant shared secret (Section 5) and stamps every session and verdict it writes with `tenant_id` for downstream filtering.

The engine does not segregate data by tenant beyond this stamping. Sessions and verdicts from different tenants live in the same MongoDB collections, distinguished by the `tenant_id` field. Per-tenant query patterns must include `tenant_id` in the filter (which is why `tenant_id` is on every secondary index - see Section 6).

Question selection is also tenant-aware, but in a specific way. The `question_x_id` base is consistent across tenants; what differs by tenant is the active set of questions, and within a tenant one content `item` can map to several `question_x_id`s. The engine selects in content (`item`) space and resolves the chosen `item` to a single `question_x_id` for the session's tenant through a per-tenant lookup (Section 7.8), without reading any tenant's live `questions` collection.

---

## 5. API contract

> **How to read this section.** Every endpoint below has the same four parts: **When to use it** (in plain terms), a **Parameters** table (every field, whether it is required or optional, and what it means in simple language), a **Sample request**, and a **Sample response**. The sample values are taken from a real Delhi grade-3 session, so the `question_x_id`s and skills are genuine. There are ten endpoints: eight functional ones (documented in full) and two operational probes, `GET /metrics` and `GET /health` (documented briefly, since they take no parameters).

### 5.1 Base, auth, and conventions

**Base URL:** `http(s)://<engine-host>:<port>/api/v1/diagnostic`. All engine routes live under this prefix.

**Method convention:** Following AML's existing pattern, routes use POST for actions (including idempotent ones) and GET only for resource reads. The engine has **five POST** endpoints (start, response, end, offline-batch, replace-question) and **five GET** endpoints (verdicts, responses, offline-tree, metrics, health) - ten in total.

**Content type:** Request and response bodies are JSON. The engine accepts and returns `application/json`.

**Authentication.** Every engine endpoint that touches session data requires a shared-secret header:

```
X-Internal-Service-Token: <per-tenant secret>
```

The engine maintains a server-side allow-list mapping `tenant_id` -> expected token. A request is accepted if the header value matches the token registered for the `tenant_id` in the request body (or in the path, for the offline-tree endpoint). A mismatch returns `401 INVALID_TENANT_TOKEN`. Tokens are configured per state-instance of `aml-api-service` and are loaded at engine startup from environment variables (see Section 10).

`GET /metrics` and `GET /health` have no auth, consistent with `aml-api-service`'s `/metrics` route.

**Unknown fields are rejected.** All request bodies are strict: a field the engine does not expect (for example a stray `username` or `name`) is refused rather than ignored, which is also a PII guard (Section 6.3).

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

### 5.2 Endpoint summary

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

The three shaded topics that cut across several endpoints - the optional **switched-off list** (deactivation failsafe), the **resumption token** (mixed-mode), and **verdict neutrality** - are introduced where they first appear and cross-referenced from Sections 7 and the offline-walk handover pack.

### 5.3 `POST /api/v1/diagnostic/session/start`

**When to use it.** Once, at the very beginning of a learner's diagnostic, right after `aml-api-service` has created the `learner_sub_sessions` record. It creates the engine's session, hands back the first question, and (if a tree exists for the learner's tenant and grade) a reference the device can use to fetch an offline tree.

**Parameters (request body):**

| Field | Type | Required | Plain-language meaning |
|---|---|---|---|
| `learner_id` | string | yes | Who the learner is (`learner.identifier`). |
| `tenant_id` | string | yes | Which state/instance this is (`tenant.identifier`); also used to check the auth token. |
| `sub_session_id` | string | yes | The id of this one diagnostic sitting (`learner_sub_sessions.identifier`). Everything about the session hangs off this id. |
| `class_id` | string | yes | The learner's class (`class_master.identifier`). |
| `grade` | integer (2-8) | yes | The learner's grade (`class_master.sequence`). Grades above 5 are handled as grade 5. |
| `switched_off_question_x_ids` | list of strings | no | The questions that are currently switched off on the app (broken, pulled, being revised) and must never be offered. Optional; if you leave it out, nothing is treated as switched off. See Section 7.8. |
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

The `resumption_token` is the small snapshot the device caches so it can pick up an offline walk correctly (Section 5.4 and the handover pack). At session start it is empty. If no tree exists for the tenant/grade, `offline_tree` is `null` and the session simply proceeds online - that is not an error here.

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `INVALID_TENANT_TOKEN` | 401 | `X-Internal-Service-Token` does not match the `tenant_id`'s registered token |
| `INVALID_GRADE` | 400 | Grade outside the supported range (2-8) |
| `SESSION_ALREADY_EXISTS` | 409 | An engine session already exists for this `sub_session_id` |
| `NO_USABLE_QUESTION` | 422 | A `switched_off_question_x_ids` list was supplied and it covers every question available for the grade, so the diagnostic cannot start. This is a client-input condition (the caller's list is exhaustive), not a server fault. With no switched-off list, an empty pool instead raises `NO_QUESTION_FOR_SKILL` (below). |
| `NO_QUESTION_FOR_SKILL` | 500 | The question pool has no active question for the chosen skill, with no switched-off list involved. A genuine content-pool gap. |
| `PII_FIELD_PRESENT` | 400 | Request body contains a disallowed field (for example `username`, `name`) |

_(A tenant or grade with no tree is not an error here: `offline_tree` is `null` and the session proceeds online. `NO_TREE_FOR_GRADE` (404) is raised only by the fetch endpoint, Section 5.9.)_

### 5.4 `POST /api/v1/diagnostic/session/:sub_session_id/response`

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
| `raw_response` | string | no | The learner's actual typed answer. Used only by the misconception classifier (Section 5.10), never by the mastery algorithm, and never logged. The core mastery pilot does not send it. |
| `switched_off_question_x_ids` | list of strings | no | An updated switched-off list, if it has changed since the last call. Optional; if omitted, the session keeps the list it already had. |
| `switched_off_mode` | `"replace"` or `"append"` | no | How to apply the list above (see Section 5.3). |

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
| `RESPONSE_CONFLICT` | 409 | The same `question_x_id` was submitted before with a different `is_correct` (Section 8.3) |

**Idempotency.** The same `question_x_id` submitted twice with the same `is_correct` is treated as a duplicate: the engine returns the same next-question response as the first call, without applying the update twice (Section 8.3).

### 5.5 `POST /api/v1/diagnostic/session/:sub_session_id/end`

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

**Sample response (200):** the same shape as the session-complete payload in Section 5.4. Any skill not yet resolved gets a verdict from the posterior-mean rule (Section 7.6).

### 5.6 `GET /api/v1/diagnostic/session/:sub_session_id/verdicts`

**When to use it.** After a session is complete, when a downstream system wants to read the verdicts again without replaying the session. GET requests carry no body; the session is identified by the path.

**Sample request:**

```http
GET /api/v1/diagnostic/session/ss_g3_demo/verdicts
X-Internal-Service-Token: <Delhi secret>
```

**Sample response (200):** the same verdicts payload shown in Section 5.4 (session-complete).

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No engine session for this `sub_session_id` |
| `SESSION_NOT_COMPLETE` | 409 | Session is still in progress; verdicts are not final |

### 5.7 `GET /metrics`

**When to use it.** Only by the monitoring system (Prometheus), on a schedule. No auth, no parameters. Returns the standard text/plain Prometheus exposition format - default process metrics plus the engine's business metrics (full list in Section 9).

### 5.8 `GET /health`

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

### 5.9 `GET /api/v1/diagnostic/offline-tree/:tenant_id/:grade`

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

### 5.10 `GET /api/v1/diagnostic/session/:sub_session_id/responses`

**When to use it.** After a session, when the misconception classifier (Stage B) needs the learner's raw typed answers. The mastery algorithm does not use these; they exist only for answers where `aml-api-service` supplied `raw_response` (Section 5.4). No body; the session is in the path.

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

Entries whose `raw_response` was not supplied come back with `raw_response: null`. The raw answer is never written to logs or metrics (Section 6.3).

**Errors:**

| Code | Status | Reason |
|---|---|---|
| `SESSION_NOT_FOUND` | 404 | No engine session for this `sub_session_id` |
| `INVALID_TENANT_TOKEN` | 401 | Token does not match the session's tenant |

### 5.11 `POST /api/v1/diagnostic/session/:sub_session_id/offline-batch`

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
| `switched_off_question_x_ids` | list of strings | no | An updated switched-off list, if it changed. Optional (see Section 5.3). |
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
| `RESPONSE_CONFLICT` | 409 | An answer in the batch contradicts one already recorded for the same `question_x_id` (Section 8.3) |
| `OFFLINE_BATCH_TOO_LARGE` | 400 | The batch is implausibly large (more than twice the grade budget) - a corruption guard. A correct device never sends this. |

**Notes.** The engine re-scores by replaying the whole unified history in order (not by adding the batch on top), so the verdicts are exactly what a fully-online session on the same answers would produce (verdict neutrality, Section 7.10). Sending the same batch twice is a harmless no-op (idempotent). An answer to a question that has since been switched off is still accepted and scored - switched-off governs future offering, not the validity of an answer already given.

### 5.12 `POST /api/v1/diagnostic/session/:sub_session_id/replace-question`

**When to use it.** When the engine offered a question the app cannot actually show right now - most often a broken media asset the engine could not have known about - and you need a different one for the same turn. The engine drops the declined question and returns a replacement, recording nothing and spending no budget. This is the deactivation failsafe's reactive path (the switched-off list is the proactive one; see Section 7.8).

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

## 6. Data model

### 6.1 Collections owned by the engine

The engine creates and writes three MongoDB collections (offline trees are shipped as file artifacts, not a collection - see below). Names follow AML's snake_case_plural pattern. All collections use the dual-ID pattern (`_id` BSON for Mongo, `identifier` Text UUID for cross-references), and include audit fields (`created_at`, `updated_at`, `created_by`, `updated_by`).

#### `learner_diagnostic_sessions`

One document per diagnostic session. Holds engine state during the session and the question history once complete.

| Field | Type | Notes |
|---|---|---|
| `_id` | MongoBSONID | Mongo PK |
| `identifier` | Text | Session UUID, equal to `sub_session_id` (engine session and AML sub-session are 1:1) |
| `learner_id` | Text | `learner.identifier` |
| `tenant_id` | Text | `tenant.identifier` |
| `class_id` | Text | `class_master.identifier` |
| `grade` | Integer | Denormalised from `class_master.sequence` for query convenience |
| `status` | Text enum | `active` / `complete` / `abandoned` |
| `started_at` | Instant | |
| `ended_at` | Instant | Set when status becomes `complete` or `abandoned` |
| `engine_version` | Text | Semantic version of the engine (e.g. `0.10.0`) - needed when interpreting verdicts later |
| `tree_id_used` | Text | Identifies the offline tree referenced at session start (its `sha256`); null if `offline_tree` was null |
| `tree_version_used` | Integer | The version of that tree |
| `posteriors` | Dictionary | Per-skill state: `{<canonical_skill_name>: {posterior: Float, direct_observations: Integer, propagation_updates: Integer, last_updated_at: Instant}}`. `propagation_updates` is the count of times this skill's posterior was moved by lattice propagation from a different skill's observation; used by the verdict rules in §7.6 to distinguish priors-only from propagation-only resolutions. |
| `question_history` | Array | Append-only log. Each entry: `{sequence: Integer, question_x_id: Text, skill_id: Text, is_correct: Boolean, asked_at: Instant, posterior_before: Float, posterior_after: Float, purpose: Text (anchor / info_gain / verification), routing_mode: Text (online / offline_replay)}` |
| `routing_mode_counts` | Dictionary | `{online: Integer, offline_replay: Integer}` for telemetry |
| `pending_question` | Sub-document or `null` | Engine-internal turn state. When a question has been picked and handed to the client but the matching response has not yet arrived, this holds `{question_x_id: Text, slip_override: Float or null, guess_override: Float or null}` so the per-item calibration parameters from §6.2.1 can be applied to the Bayes update when the response arrives. Cleared once the matching response is recorded. Persisted so that mid-session pod restarts do not lose the calibration parameters for the in-flight question. Not exposed to clients. |
| `created_at`, `updated_at`, `created_by`, `updated_by` | Audit fields | |

**Indexes:**
- `{identifier: 1}` unique
- `{learner_id: 1, started_at: -1}` for "most recent session for learner X"
- `{tenant_id: 1, status: 1}` for tenant-scoped operational queries
- `{tenant_id: 1, started_at: -1}` for tenant-scoped recency queries

#### `learner_skill_verdicts`

One document per (session, skill). Persisted at session end. Designed for fast lookups by downstream systems.

| Field | Type | Notes |
|---|---|---|
| `_id` | MongoBSONID | |
| `identifier` | Text | Verdict UUID |
| `learner_id` | Text | |
| `tenant_id` | Text | |
| `class_id` | Text | |
| `l1_skill_id` | Text | Operation name: Addition / Subtraction / Multiplication / Division. Matches AML's existing `learner_proficiency_aggregate_data` keying |
| `l2_5_skill_id` | Text | Canonical L2.5 skill name |
| `sub_session_id` | Text | Foreign reference to the session document |
| `posterior` | Float | Mastery probability at session end |
| `direct_observations` | Integer | How many direct questions were asked on this skill in this session |
| `propagation_updates` | Integer | How many times this skill's posterior was moved by lattice propagation. Used by the verdict rules in §7.6 |
| `confidence_label` | Text enum | `confident_mastered` / `uncertain` / `confident_not_mastered` |
| `recommendation` | Text enum | `skip_maind` / `take_maind_diagnostic` / `take_maind_confirmation` |
| `engine_version` | Text | |
| `created_at`, `updated_at`, `created_by`, `updated_by` | Audit fields | |

**Indexes:**
- `{identifier: 1}` unique
- `{learner_id: 1, l2_5_skill_id: 1, created_at: -1}` for "most recent verdict per (learner, skill)" - primary downstream read pattern
- `{tenant_id: 1, created_at: -1}` for tenant-scoped analytics
- `{sub_session_id: 1}` for fetching all verdicts of a session

#### Offline tree artifacts (files, not a MongoDB collection)

Offline trees are **not** stored in MongoDB. Each (tenant, grade) bundle is a gzipped JSON file on disk - `artifact/<tenant>/g<grade>.json.gz` - under the directory named by `OFFLINE_ARTIFACT_DIR` (repo-relative by default; Section 10). The engine loads these files once at startup into an in-memory registry and serves them through the fetch endpoint (Section 5.9); it never reads or writes a `diagnostic_offline_trees` collection.

Each bundle carries: the four per-operation trees (each node `{question_x_id, skill_id, on_correct, on_incorrect}`), a shared per-grade parameters block, the `engine_version` it was built against (used to reject a stale tree), a `manifest` of every `question_x_id` the trees can reach (for `aml-portal` to pre-load content), and the config versions used to generate it (`lattice_version`, `priors_version`, `anchors_version`, `calibration_version`). The batch job writes one bundle per (tenant, grade); Delhi G2-G5 ship today. Per-grade bundle sizes (Delhi, measured against the shipped artifacts):

| Grade | Compressed (gz on disk) | Served (canonical JSON, = `size_bytes`) |
|---|---|---|
| G2 | ~10 KB | ~59 KB |
| G3 | ~81 KB | ~0.37 MB |
| G4 | ~1.44 MB | ~6.3 MB |
| G5 | ~5.4 MB | ~24.8 MB |

The fetch endpoint serves the canonical JSON - the served figure above, which is what `size_bytes` advertises and what a device's storage budget depends on (the largest, G5, is about 24.8 MB). The raw decompressed size is larger but is never sent to the client.

#### `lattice_edges`

The skill-to-skill relationship graph used for propagation. Read-only at runtime; populated and updated by the engine team. AML team members can inspect.

| Field | Type | Notes |
|---|---|---|
| `_id` | MongoBSONID | |
| `identifier` | Text | Edge UUID |
| `skill_a` | Text | Canonical L2.5 skill name (source) |
| `skill_b` | Text | Canonical L2.5 skill name (target) |
| `operation_a` | Text | Operation `skill_a` belongs to |
| `operation_b` | Text | Operation `skill_b` belongs to |
| `edge_type` | Text enum | `within_operation` / `cross_operation` |
| `p_b_given_a` | Float | Probability `skill_b` is mastered given `skill_a` is mastered |
| `p_b_given_not_a` | Float | Probability `skill_b` is mastered given `skill_a` is NOT mastered |
| `weight` | Float | 1.0 for multi-view edges (more confident), 0.5 for single-view edges (less confident) |
| `is_active` | Boolean | Allows disabling an edge without deleting it |
| `created_at`, `updated_at`, `created_by`, `updated_by` | Audit fields | |

**Indexes:**
- `{identifier: 1}` unique
- `{skill_a: 1, is_active: 1}`
- `{skill_b: 1, is_active: 1}`

### 6.2 AML collections the engine reads (read-only)

| Collection | Used for |
|---|---|
| `tenant` | Validating `tenant_id` exists at startup; not read at request time (the shared-secret check covers per-request validation) |
| `class_master` | Looking up `sequence` from `class_id` if `aml-api-service` does not pre-translate. Optional - engine works without this if grade is passed directly |
| `skill_master` | Validating canonical skill names map to real skills in the calling instance. Used at startup |
| `questions`, `question_sets`, `question_set_question_mapping` | Not read by the engine at request time. The engine selects questions from the calibration file and the per-tenant lookup, both loaded at startup (see §6.2.1 and §7.8). These AML collections are the source from which the AML team produces each tenant's active-question list, which the build step turns into the per-tenant lookup. The engine itself never queries them live. |

#### 6.2.1 Inputs the QuestionPool reads (sidecar files, not the live collection)

The engine's `QuestionPool` does not read the live `questions` collection. Instead it loads two static files at startup, refreshed deliberately when their sources change (Section 10.5). This decoupling is deliberate: each tenant has its own `questions` collection (a given `question_x_id` lives in only one tenant's collection), and calibration is keyed on the content `item` rather than on `question_x_id` (see §7.8 for the rationale).

**1. The calibration file.** One row per (question, grade), keyed on the `item` content key. Fields the engine relies on:

| Field | Required | Purpose |
|---|---|---|
| `item` | yes | The content key (`Q L1 Skill \| Q L2.5 Skill \| Q Type \| Q Text \| Q N1 \| Q N2`); the join key to the per-tenant lookup |
| `l2_5_skill` | yes | Links the question to its canonical skill |
| `q_type` | yes | Question type (for example Fib, Mcq) |
| `grade` | yes | The grade this row's parameters apply to; a pooled `all` row is the fallback when no grade-specific row exists |
| `slip` | yes | Calibrated slip, used in the Bayes update; uniform default (§7.7) only when a question has no row |
| `guess` | yes | Calibrated guess, same rule |
| `discrimination` | yes | Used by the selection window (§7.8 step 4) |

**2. The per-tenant question lookup.** Maps `(tenant, item)` to a single `question_x_id`. Produced by the build step in §7.8 from each tenant's active-question list (the six raw fields plus the `question_x_id`). This is how the engine returns a `question_x_id` while selecting in `item` space.

The calibration is Delhi-derived: questions used only in other tenants, and questions with thin data, carry borrowed or default values (design document §4.3). When (and if) a single shared content service is built, the calibration values could move onto the question records themselves and the per-tenant lookup would collapse into that service; neither changes the engine's logic (design document §7).

### 6.3 PII boundary

The engine accepts and stores only opaque identifiers and numeric / categorical data:

| Accepted | Never accepted or stored |
|---|---|
| `learner_id` (opaque `identifier`) | Username, name, password, school name, human-readable tenant name |
| `tenant_id` (opaque `identifier`) | Region or geographic data beyond `tenant_id` |
| `class_id`, `grade` (integer 2-8) | Section, board, or any other learner attribute beyond grade |
| `sub_session_id` | Browser, device, IP, user agent |
| `skill_id` (canonical name), `question_x_id` | Question content, response media |
| `is_correct` (boolean), `response_time_ms` (optional integer) | |
| `raw_response` (optional; the learner's typed answer - see note) | |

Inbound requests carrying any forbidden field are rejected with `400 PII_FIELD_PRESENT`. The engine's logs and Prometheus metrics filter out unexpected fields by design - no wildcard ingestion.

**The one deliberate exception is `raw_response`** (Section 5.4): the learner's typed answer, accepted only so the misconception classifier can read it back (Section 5.10). It is explicitly allow-listed rather than rejected, is never used by the mastery algorithm, and is never written to logs or metrics. This is a scoped change from the earlier boundary, which accepted no learner response text; it is limited to this single field and this single purpose, and the pilot mastery flow does not send it.

---

## 7. Engine algorithm

This section describes what the engine actually computes. The audience is engineers, not psychometricians. Math is used where unavoidable, but every step has a plain-language explanation.

### 7.1 The big picture

On every learner response, the engine does two things:

1. **Update the posterior** for the skill the question tested, using Bayes' rule with fixed slip and guess parameters.
2. **Propagate the update** through the lattice to related skills.

After the update, it decides what to do next: ask another question on the same skill, jump to a related skill, switch operations, or end the session.

The engine's model is a **single-skill Bayesian posterior update with fixed slip and guess, plus Bayesian-network propagation over a curated skill-relationship lattice**. The vocabulary (slip, guess, posterior, mastery) is borrowed from Cognitive Diagnostic Modelling, but the engine does not implement any specific named model from that family.

### 7.2 The single-skill update

Let `p` be the engine's current posterior for a skill (the probability the learner has mastered it). Let `s = 0.10` be the slip parameter and `g = 0.15` be the guess parameter. After observing a correct response on a question for this skill:

```
p_new = ((1 - s) * p) / ((1 - s) * p + g * (1 - p))
```

After observing an incorrect response:

```
p_new = (s * p) / (s * p + (1 - g) * (1 - p))
```

In plain language:
- A correct answer pushes the posterior up. The size of the push is largest when the prior was middling (around 0.5) and smallest when the prior was already high.
- An incorrect answer pushes the posterior down, with the same shape.
- The size of the move depends on how surprising the response was given the engine's current belief.

These are standard Bayes-rule updates with the likelihood model "Pr(correct | mastered) = 1 − slip" and "Pr(correct | not mastered) = guess".

### 7.3 Lattice propagation

After the direct update on skill A, the engine checks each lattice edge involving A:

- **Forward propagation.** If the response was correct and the posterior on A is now above 0.5, push the posterior of any skill B where edge `A → B` exists toward 0.9 (the `EDGE_PROPAGATION_VALUE`), weighted by the edge weight.
- **Backward propagation (contrapositive).** If the response was incorrect and the posterior on A is now below 0.5, push the posterior of any skill W where edge `W → A` exists down toward 0.1.

Propagation only moves the target posterior toward the propagation value - it never overshoots a posterior that was already more extreme. If skill B already had posterior 0.95 (more confident than the 0.9 target), propagation does nothing to B.

### 7.4 Confidence thresholds

A skill is considered "resolved" when its posterior crosses either threshold:

- **Resolved as mastered:** posterior ≥ 0.95
- **Resolved as not mastered:** posterior ≤ 0.10

Once resolved, the engine stops asking direct questions on the skill.

### 7.5 Question selection (Option 4, online)

For each operation, in a per-grade order (Multiplication-first for G2-G4, Division-first for G5):

1. **Ask the operation's anchor question first.** The anchor for each (grade, operation) is a fixed skill from the anchor configuration. This grounds the operation block with an early direct observation.
2. **Loop:** within the operation, pick the next question by either:
   - **Verification:** If a skill has reached an extreme posterior (≥ 0.85 or ≤ 0.15) through propagation alone, without any direct observation, ask one direct question to confirm.
   - **Information gain:** Otherwise, pick the unresolved skill with the highest expected information gain - entropy of the current posterior plus a small bonus for skills with more lattice edges (because direct evidence on such skills informs more downstream skills).
3. **Stop conditions for the operation block:**
   - All skills in the operation are resolved, OR
   - The per-operation budget cap is reached, OR
   - The total question budget for the grade is reached.

After all operations are processed (or the global budget runs out), the engine assigns verdicts to every skill (Section 7.6).

### 7.6 Verdict assignment

The engine assigns one verdict per in-scope skill at session end. The verdict depends on three pieces of state for that skill:

![Verdict assignment logic](img/verdict_decision.png)

| State | Definition |
|---|---|
| `posterior` | Final posterior probability (between 0 and 1) |
| `direct_observations` | Count of questions asked directly on this skill |
| `propagation_updates` | Count of times this skill's posterior was moved by lattice propagation from a different skill's observation |

#### Rules

| Rule | Posterior | Direct observations | Propagation updates | Verdict | Recommendation |
|---|---|---|---|---|---|
| 1 | ≥ 0.95 | ≥ 1 | any | `confident_mastered` | `skip_maind` |
| 2 | ≥ 0.95 | 0 | 0 | `confident_mastered` | `skip_maind` |
| 3 | ≥ 0.95 | 0 | ≥ 1 | `uncertain` (downgraded) | `take_maind_diagnostic` |
| 4 | ≥ 0.5 and < 0.95 | any | any | `uncertain` | `take_maind_confirmation` |
| 5 | < 0.5 and > 0.10 | any | any | `uncertain` | `take_maind_diagnostic` |
| 6 | ≤ 0.10 | ≥ 1 | any | `confident_not_mastered` | `take_maind_diagnostic` |
| 7 | ≤ 0.10 | 0 | 0 | `confident_not_mastered` | `take_maind_diagnostic` |
| 8 | ≤ 0.10 | 0 | ≥ 1 | `uncertain` (downgraded) | `take_maind_diagnostic` |

#### What changed from earlier versions of this spec

Earlier drafts of this section had a simpler downgrade rule: any high-posterior skill with zero direct observations was treated as `uncertain (downgraded)`. The current rules separate two cases that look similar but behave differently in practice:

- **Resolved by priors alone** (direct_obs = 0 AND propagation_updates = 0): the skill's posterior is at its initial value from the cohort prior. The engine never tested it and lattice propagation never touched it. The cohort prior is an empirical distribution from real learner data; trusting it produces a confident verdict (Rules 2 and 7).
- **Resolved by lattice propagation alone** (direct_obs = 0 AND propagation_updates ≥ 1): the skill's posterior was moved by inferring from related skills' observations. Lattice edges are approximate (12 hand-curated edges with content-team validation, but still inferred); the engine downgrades to `uncertain` so downstream picks up the skill via MainD (Rules 3 and 8).

The simulation evidence supporting this distinction is in the Testing Summary §4 (the Minimum Direct Evidence experiment): forcing a direct observation on every skill did not improve pooled accuracy, indicating that priors are calibrated well enough that priors-only resolutions can be trusted. The Testing Summary §9 (Verification on/off) shows the opposite for propagation: removing verification of propagation-resolved skills cost 0.3 pp pooled accuracy and 2.2 pp on G2 Division specifically, confirming that propagation-only resolutions need direct verification.

#### Implementation note

The engine must track `propagation_updates` per skill in addition to `direct_observations`. This is a new field on the per-skill state in `learner_diagnostic_sessions.posteriors` (see §6.1). It increments every time `engine.lattice.propagate()` returns a non-empty update for this skill as a target.

The verdict logic in `engine.verdicts.assign_verdict()` takes both counters and applies the eight rules above.

### 7.7 Fixed parameters (v1)

| Parameter | Value |
|---|---|
| Slip (`s`) default / fallback | 0.10 |
| Guess (`g`) default / fallback | 0.15 |
| Mastery threshold | 0.95 |
| Not-mastered threshold | 0.10 |
| Verification trigger thresholds | 0.85 (high), 0.15 (low) |
| Edge propagation value | 0.90 |
| Question budgets | G2 = 25, G3 = 42, G4 = 59, G5 = 76 |
| Per-operation base caps | G2 = 6, G3 = 9, G4 = 13, G5 = 16 |
| Offline per-operation allowance (locked) | G2 = +3, G3 = +4, G4 = +4, G5 = +3. Extra questions added beyond the per-operation base for the offline three-pass follow (misconception backfill and skill harvest); see Section 10.5. |
| Hard budget cap (all modes) | The grade question budget is a hard ceiling no session exceeds (25 / 42 / 59 / 76). Verified over-budget fraction is 0.000 at every grade. |
| Misconception coverage target (`conditional_extra`) | Shipped value 0 (deployment `config/engine_config.yaml`); engine code default 2. See Section 7.9. |
| Per-operation cap multiplier (`per_operation_cap_multiplier`) | Shipped 1.5 (per grade, `config/engine_config.yaml`). Caps questions spent on one operation at 1.5x its base allocation (`per_operation`), so no single operation can exhaust the budget. |
| Reserve size (`reserve_size`) | Shipped per grade: G2 7, G3 11, G4 15, G5 19 (`config/engine_config.yaml`). Questions held back from the initial per-operation allocation as a shared reserve the engine can draw on adaptively. |
| Info-gain edge bonus (`info_gain_edge_bonus`) | Shipped 0.5 (`config/engine_config.yaml`). A bonus added in the information-gain scoring to favour a question that adds coverage (a not-yet-probed edge). |

These are loaded at engine startup from a config file or environment variables (Section 10).

**Per-item overrides.** The slip and guess values above are fallback defaults. Per-item calibration now exists: each question has its own measured `slip` and `guess` (and `discrimination`), delivered in a companion calibration file that the engine loads at startup (see §6.2.1 and §7.8). The engine uses the per-item values in the Bayes update for the chosen question, falling back to the uniform defaults only when a question has no calibrated row. The calibration is Delhi-derived (questions used only in other tenants, and questions with thin data, carry borrowed or default values); the calibration method is a two-class DINA model fit by Expectation-Maximization (the DINA family in Appendix B - used here for calibration, not as the runtime scorer); see the design document §4.3 and the Question Calibration Process Report for the full method, and §4.11 for the recalibration cadence.

### 7.8 The question pool

Sections 7.1 through 7.7 describe how the engine decides **which skill** to test next. This section describes how that decision is converted into a **specific question** returned to the client.

The question pool is a separate component (the `QuestionPool` interface; the production implementation is `CsvQuestionPool`). It takes a chosen skill plus the current session state and returns a `question_x_id` along with that question's calibrated `slip` and `guess`.

When a tenant's active bank offers more than one variant of the same underlying question (for example, several `36/3` division forms), the pool resolves to exactly one `question_x_id` per (tenant, item) by a deterministic variant precedence: prefer an `entry` (entry-test-authored) variant, then a `dlg` (Delhi grade-specific) variant, then a `_b`-suffixed variant, then the lexicographically smallest id. This ordering is intended and applies globally: where a tenant has an entry-test-authored variant, it fills that tenant's main-diagnostic slot for the item (confirmed by the engine owner).

#### Inputs the pool loads at startup

| Input | What it is |
|---|---|
| Calibration file | One row per (question, grade) with `item` key, `l2_5_skill`, `q_type`, `grade`, `slip`, `guess`, `discrimination`. This is the sidecar file described in §6.2.1. Keyed on `item` (the content key), not on `question_x_id`. |
| Per-tenant question lookup | A table mapping `(tenant, item)` to a single `question_x_id`. Built ahead of time from each tenant's active-question list (see "The per-tenant lookup build step" below). |

The engine never reads any tenant's live `questions` collection at request time. Both inputs are static files loaded at startup and refreshed deliberately (Section 10.5, design document §4.11).

#### Why selection is keyed on `item`, not on `question_x_id`

The base `question_x_id` is consistent across tenants (sometimes with a tenant suffix), so the issue is not translating an ID from one tenant to another. The reasons for selecting in `item` space are different:

1. **Within a tenant, one `item` can map to several `question_x_id`s.** A skill's content key (the `item`) can be realized by more than one question record in a single tenant's `questions` collection. Calibration is measured per `item`, so the engine selects an `item` and then resolves it to one concrete `question_x_id`.
2. **The active set of questions differs by tenant.** A given `question_x_id` exists in only one tenant's collection; most (not all) `question_x_id`s exist across tenants. So which questions are available for an `item` is tenant-specific, even though the ID values themselves are shared.

The `item` content key is a composite of the question's own fields. A non-division key has **six** fields; a division key carries a **seventh**, `response_includes_remainder`:

```
item = Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2                                (non-division)
item = Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2 | response_includes_remainder   (division only)
```

The seventh field distinguishes the two division answer formats (quotient-only versus quotient-plus-remainder) so that two otherwise-identical division questions do not collapse to one key. It is derived from the stored correct answer, never from `n1 % n2`. The authoritative definition of the key and its construction lives in `question_pool_build_and_resolution_spec.md`, Section 3. **Currently inert but retained:** after a bank correction the current 667-item bank has no two-format division pairs (zero `|True` rows), so the seventh field changes no key today; it is kept deliberately, as regression protection, so that if a two-format pair is reintroduced the two variants stay distinct (Section 16, item 21).

The engine does all of its selection in `item` space and resolves to a concrete `question_x_id` only at the final step, using the per-tenant lookup. One calibration file (keyed on `item`) serves all tenants; the per-tenant lookup and the per-tenant offline trees absorb the tenant-specific active sets. This holds until a common content service removes the per-tenant collections (design document §7).

#### Selection algorithm

Given a chosen `skill`, the session's `grade`, the session's `tenant_id`, and the session `question_history`:

1. **Enumerate candidates.** Take all distinct `item`s whose `l2_5_skill` equals the chosen skill.
2. **Apply no-repeat, and exclude unavailable questions.** Drop any `item` already asked in this session (the history stores `question_x_id`s; map each back to its `item` via the lookup so the no-repeat test is in `item` space). In the same filter, drop any variant that is **retired** or **switched off** for this session (the deactivation failsafe, Section 5.3): the exclusion is keyed on the tenant's resolved `question_x_id`, and an `item` whose only tenant variant is excluded is dropped as if it had no question.
3. **Resolve parameters at the learner's grade.** For each candidate, take its row for the session grade; if no grade-specific row exists, fall back to the pooled (`all`) row. This yields the candidate's `slip`, `guess`, `discrimination` for this learner.
4. **Apply the discrimination window.** Let `best` be the highest `discrimination` among the candidates. Keep a candidate if its `discrimination` is at least `best - 0.10` AND at least `0.50`. Both comparisons use the grade-resolved value from step 3. (The `0.50` floor is an absolute quality bar; the `best - 0.10` window keeps only the near-sharpest. The floor must be checked on the grade-resolved row, because a question can clear it at most grades but fall below it at one - see Appendix A.)
5. **Pick one.**
   - Online (default): choose uniformly at random among the survivors. This spreads exposure across the near-sharpest questions.
   - Offline / deterministic mode: choose the single highest-`discrimination` survivor, breaking ties by smallest `item`. This makes the offline tree reproducible.
6. **Resolve to a `question_x_id` and return.** Look up `(tenant_id, item)` in the per-tenant lookup to get the `question_x_id`, and return it together with the chosen row's `slip` and `guess`.

Step 4 uses a window rather than a fixed "top-k" because discrimination varies between skills, not within them: for most skills the near-sharpest questions are clustered, so the window adapts to each skill's spread instead of imposing an arbitrary count.

#### The per-tenant lookup build step

The lookup is produced by a build step that runs whenever a tenant's active-question list changes (the same regenerate-on-input-change discipline as the offline tree, Section 10.5):

1. The AML team provides, per tenant, a list of active diagnostic questions including the six raw fields (`Q L1 Skill`, `Q L2.5 Skill`, `Q Type`, `Q Text`, `Q N1`, `Q N2`) plus the `question_x_id` (and, for division questions, the remainder-format signal that yields the seventh key field).
2. The build step constructs the `item` key from those fields - six for non-division, seven for division (appending `response_includes_remainder`) - using exactly the same construction as the calibration script, so the join to calibration is exact.
3. It emits the `(tenant, item) -> question_x_id` table. Where one `item` maps to several `question_x_id`s within a tenant, the build step applies a deterministic precedence - prefer a `question_x_id` containing `entry`, then one containing `dlg` (a Delhi grade-specific variant), then one ending in `_b`, then the lexicographically smallest - so selection and the offline tree always resolve the same way. The `entry` preference is deliberate: the dynamic diagnostic replaces the Entry Diagnostic (see below), so where an Entry-Diagnostic-purposed question exists for an `item`, that is the correct one to serve. Because calibration is keyed on `item`, this precedence is rendering-only: it changes which concrete question renders, not any verdict, coverage, or savings number.

**The dynamic diagnostic replaces the Entry Diagnostic.** In v1 the dynamic diagnostic is given to a learner in place of the static Entry Diagnostic, so serving Entry-Diagnostic-purposed questions creates no duplication for the learner. A separate future mode - a Dynamic Main Diagnostic - is out of scope for v1; when it is built, it must exclude the questions a learner already saw in the entry-role diagnostic (a no-repeat check against the entry-served set). That constraint originates here and is recorded so the Main-mode work accounts for it.

#### Returned data

| Field | Required | Used for |
|---|---|---|
| `question_x_id` | yes | The `question_x_id` returned to the client; also the key in idempotency checks |
| `slip` | yes | Bayes update for this question |
| `guess` | yes | Bayes update for this question |

When a chosen `item` has no calibrated row, the engine substitutes the uniform fallback defaults (§7.7).

#### Failure modes

The pool MUST return a question for any valid skill in the engine's scope. If the candidate set is empty after steps 1-4 (no questions for the skill, or all already asked, or none clearing the floor), the engine raises `NO_QUESTION_FOR_SKILL` (HTTP 500) and the session cannot continue - a content-pool gap for engineering and the content team. **The one exception is the failsafe:** when a caller-supplied switched-off list is what empties the pool at session start (the list covers every available question for the grade), the engine raises `NO_USABLE_QUESTION` (HTTP 422) instead, because that is a client-input condition, not a server-side content gap (Section 5.3).

![The deactivation failsafe](img/deactivation_failsafe.png)

If a chosen `item` has no entry in the per-tenant lookup for the session's tenant, that is a content/lookup mismatch: the engine raises `NO_QUESTION_FOR_SKILL` rather than returning an ID that the tenant cannot load.

The pool MUST NOT return a `question_x_id` already in the session's `question_history`. Repeats break the idempotency contract (§8.3).

#### Relationship to the prototype

The prototype's `CsvQuestionPool` implements steps 1-5 and the discrimination window, verified against the calibrated question pool. The per-tenant resolution in step 6 (and the build step that produces the lookup) is the one addition beyond the current prototype: the prototype today returns a single global `question_x_id` per `item`, and the revision is to resolve that `item` to the session tenant's `question_x_id` via the lookup. This is a contained change to the pool's final step and does not affect selection.

### 7.9 Misconception coverage (engine) and classification (out-of-engine)

Two components are involved, and it matters to keep them apart, because only one of them ever sees the learner's raw answer. This does not change the mastery verdict.

**What the engine does: coverage only.** Beyond deciding mastered or not, many wrong answers follow recognisable patterns (for example, dropping a carried digit). The engine's role is to make sure the diagnostic *asks* questions that can reveal a learner's misconceptions: it tracks which applicable misconceptions have been probed in a session and prefers a question that covers a not-yet-seen one where the budget allows. The engine never receives, stores, or inspects the learner's raw response text (consistent with the PII boundary, §6.3); it works only in `question_x_id` and `is_correct` terms. It does not classify, and it does not itself hold a misconception tag.

**What the separate step does: classification and merge.** The misconception classifier is a separate component (the Stage B classifier, `aml_stageb`) that runs after the session, outside the engine. It reads the learner's raw answers, matches each against the 139-code catalogue (Addition A01-A26, Subtraction S01-S31, Multiplication M01-M46, Division D01-D36; Appendix D), and produces a per-skill misconception tag. That tag is merged onto the engine's per-skill mastery verdict to form the learner's learning state (input, output, and merge in Appendix E). The tag is therefore attached to the verdict *downstream of* the engine, not passed *through* it - which is what keeps the §6.3 boundary intact.

**Data flow.**

1. The engine selects questions (biasing toward misconception coverage) and, from `is_correct` responses, produces per-skill mastery verdicts. It sees no raw answers.
2. `aml-api-service` holds the learner's raw answers and, at session end, hands them plus the engine's verdicts to the Stage B classifier.
3. Stage B classifies each raw answer against the catalogue and merges the tags onto the verdicts, yielding the learning state (Appendix E).

*(A figure of this three-step flow is a documentation to-do; the steps above are the normative description.)*

This layer is **built and verified in testing** (part of the current 668-test suite); it is not yet running in production, since nothing in this system is live yet.

**Where it acts.**

- **Offline:** the misconception backfill is Pass 2 of the three-pass follow (§4.3), and it is always on: after the base pass, the walk continues past the per-operation base cap to cover applicable misconceptions, up to the locked per-operation allowance.
- **Online:** within the still-relevant skills, selection can prefer a question that covers an applicable misconception not yet seen, without exceeding the budget.

**The `conditional_extra` parameter.** `conditional_extra` is the target number of times each applicable misconception should be probed before coverage is considered satisfied.

| Setting | Value |
|---|---|
| Engine code default (`MisconceptionConfig`) | 2 |
| Shipped value (`config/engine_config.yaml`) | 0 |

The shipped value is 0, set in deployment config rather than in code; the code default of 2 is intentionally left in place so the behaviour can be turned on by config alone, with no code change. Shipping at 0 means the engine does the always-on backfill described above but does not force repeat probes of an already-seen misconception. The trip-wire for raising it: downstream telemetry showing a MainD resolution gap or false-clear pattern on misconception-bearing skills. That telemetry join (durable sink export plus the MainD join) is a data-platform confirmation, not verifiable from the engine repo, and is the load-bearing check for keeping `conditional_extra = 0`.

### 7.10 Offline scoring (history scorer)

An offline session is scored on the server when its answers are synced (via the offline-batch ingest, Section 5.11), not on the device (§4.3). Mixed-mode sessions are scored the same way: the ingest replays the **full unified history** - every online and offline answer, in order - so the result matches a fully-online session on the same answers (verdict neutrality). The history scorer replays the recorded attempt history (`question_x_id`, `skill_id`, correctness per attempt) through the engine's own single-skill update (§7.2), lattice propagation (§7.3), and verdict assignment (§7.6). It does not re-implement any engine logic, so it is exact for whatever was asked. When the history comes from AML's stored attempt records (`learner_proficiency_question_level_data`, Section 1), those are keyed on `question_id`, which is finer-grained than the engine's `question_x_id`: many `question_id`s map to one `question_x_id`, and each `question_id` resolves to exactly one `question_x_id`. The scorer must apply that `question_id` -> `question_x_id` mapping before replaying; it must not assume the two are identical, and the mapping must be available where the scorer runs (open dependency C-1). Device-recorded offline histories already carry `question_x_id` from the tree nodes and need no mapping.

Verification against engine 0.9.0 (unchanged at 0.10.0, which is verdict-neutral to this): across 420 sampled sessions (8,820 skill comparisons) the scorer's skill verdicts and misconception signals matched the online engine exactly (0 mismatches), and a several-hundred-session mixed-mode sweep (an online prefix, then a real offline-batch ingest, versus pure-online) showed zero mastery-verdict mismatches and zero over-budget sessions. It is source-agnostic: a stitched online-then-offline history scores identically to a fully-online session on the same answers, because the scorer reads only question id and correctness and ignores provenance. Re-deriving every step's skill, slip, guess, and tags from the `question_x_id` alone (the only thing an offline-tree node carries) reproduces the online verdicts exactly, so an offline-tree question is fully scorable from its id.

---

## 8. Engine state lifecycle

This section describes how a session moves through states, what triggers each transition, and how the engine handles edge cases.

### 8.1 The states

```
            +-----------+
            |  (none)   |
            +-----+-----+
                  |
                  | session/start
                  v
            +-----------+
   +------> |  active   |-----+-- budget exhausted OR
   |        +-----+-----+     |   all skills resolved (via response)
   |              |           |
   |              | response  v
   |              v       +-----------+
   +------- (response loop)| complete |
                           +-----------+

   At any time during 'active':
   +-----------+   abandoned/timeout/quit  +-------------+
   |  active   |-------------------------->|  abandoned  |
   +-----------+                           +-------------+
```

### 8.2 Transitions

| From | To | Trigger | Side effects |
|---|---|---|---|
| (none) | active | `POST /session/start` | Creates `learner_diagnostic_sessions` document with `status=active`. Copies priors into `posteriors`. Selects first question. Returns it and the offline tree. |
| active | active | `POST /session/:id/response` | Updates `posteriors`, appends to `question_history`, selects next question, returns it |
| active | complete | `POST /session/:id/response` resulting in budget exhausted OR all skills resolved | Updates session document: `status=complete`, sets `ended_at`. Writes one document per skill to `learner_skill_verdicts`. Returns verdicts in the response |
| active | complete | `POST /session/:id/end` with no abandonment reason | Same side effects as above |
| active | abandoned | `POST /session/:id/end` with reason `abandoned`, `timeout`, or `learner_quit` | Same writes as `complete` but `status=abandoned`. Verdicts still written using the posterior-mean rule for unresolved skills |

### 8.3 Idempotency and replay

The response endpoint is idempotent on `(sub_session_id, question_x_id)`. This matters because:

- `aml-api-service` may retry a network-failed request.
- An offline batch may re-sync a response that was already submitted before connectivity dropped.

The engine handles this as follows:

1. On every `POST /session/:id/response`, the engine looks at the most recent entry in `question_history`.
2. If the most recent entry has the same `question_x_id` and the same `is_correct`, the engine returns the same next-question response as the original call. No second update is applied.
3. If the most recent entry has the same `question_x_id` but a DIFFERENT `is_correct`, the engine returns `409 RESPONSE_CONFLICT`. The caller decides how to resolve.

**Why this matters for the hybrid pattern.** When a client goes offline mid-session, traverses the local tree, and later replays the offline batch, every replayed response is "new" from the engine's perspective until it matches a `question_x_id` already in `question_history`. Duplicates are silently handled, and the order of responses is preserved as long as `aml-api-service` submits the replay batch in sequence.

### 8.4 Crash recovery

The engine is a stateless service. All session state lives in `learner_diagnostic_sessions`. If the engine process crashes mid-request, no in-memory state is lost - the next call from `aml-api-service` (a retry, in this case) reads the database and continues.

There is one edge case worth handling explicitly. When a session ends, the engine writes to two collections:

1. The session document is updated to `status = complete`.
2. Verdicts are written, one document per skill, to `learner_skill_verdicts`.

These are separate writes. If the engine crashes between them, the session looks complete but verdicts are missing. A downstream system asking for verdicts would find none.

**The cleanup job.** A Kubernetes CronJob runs `python -m engine.cli cleanup` every 5 minutes (the cadence is set by the CronJob's `schedule:` field in its manifest, not by the engine process). It looks for sessions where `status = complete` but no verdict records exist. For any it finds, it recomputes the verdicts from the session's final posteriors (which are inside the session document) and writes them. This catches the partial-write edge case without complicating the main request path. The recovery logic is identical whether run as a CronJob or invoked manually; only the scheduling mechanism is external to the engine.

**On read.** If `GET /session/:id/verdicts` finds a `complete` session with no verdicts, the engine returns `500 VERDICTS_NOT_WRITTEN`. The caller can retry; by the next attempt, either the request itself has completed the write or the cleanup job has.

### 8.5 Session timeout

The engine does not auto-time-out sessions. `aml-api-service` is responsible for deciding when a `learner_sub_sessions` is timed out and calling `POST /session/:id/end` with `reason=timeout`. This keeps timeout policy in one place across AML.

### 8.6 Concurrency

**In v1, the engine runs as a single instance.** Only one engine process handles requests at a time. Requests for the same `sub_session_id` arrive one at a time from `aml-api-service` and are processed in order. There is no coordination problem, so no lock is needed.

**Running more than one engine instance requires a lock.** If the engine is scaled to multiple instances for higher throughput, two requests for the same `sub_session_id` could reach two different instances at the same moment. Both would read the same session document, both would update posteriors, and the second write would overwrite the first, losing a response. A per-session lock prevents this. The lock is required before running more than one instance; it does not need to be active for a single-instance deployment.

**Lock design.**

- **Scope is per session.** The lock key is the `sub_session_id`. Different learners' sessions are completely independent and never contend with each other. Contention is possible only between two requests for the *same* session (a client retry or a double-submit), which is at most one or two extra requests, never a crowd. AML already uses the Redlock algorithm for this pattern; the engine uses the same library.
- **The locked section is short.** Only the read-update-write of one session happens inside the lock: read the session, run the Bayes update and lattice propagation (arithmetic over a few dozen numbers), write it back. This is a millisecond-scale operation.
- **No slow or external calls inside the lock.** Nothing that can block (no outbound HTTP, no large query) runs while the lock is held. This is the rule that keeps the lock from becoming a bottleneck: because every holder releases in milliseconds, a second waiter proceeds almost immediately and requests cannot pile up.
- **Operations inside the lock are idempotent.** A retried or duplicated request for the same `(question_x_id, is_correct)` produces the same result rather than double-counting (§8.3), so the lock plus idempotency together make concurrent duplicates safe.
- **Expiry is a crash-recovery ceiling, not the expected hold time.** If the instance holding the lock crashes mid-update, the lock auto-releases after an expiry so the session is not frozen. **Default expiry: 2 seconds.** This is far longer than the millisecond-scale work (so it never fires in normal operation) yet short enough that a crash frees the session quickly. If the lock cannot be acquired within the expiry, the engine returns `503 SESSION_LOCKED` and the caller may retry.

**Open item (revisit after pilot).** The 2-second expiry is a working default. Finalize it once the pilot provides the p99 duration of the locked section under real load, setting the expiry to roughly 10 times that figure. This is the only part of the lock design left open; the scope, the millisecond-hold discipline, the no-external-calls rule, and idempotency are settled.

---

## 9. Observability

### 9.1 Prometheus metrics

The engine exposes `GET /metrics` for Prometheus scraping. The format matches `aml-api-service`'s existing `/metrics` endpoint (text/plain Prometheus exposition format). Default Node-style process metrics (process CPU, memory, GC) are exposed along with the engine-specific business metrics listed below.

| Metric name | Type | Labels | Meaning |
|---|---|---|---|
| `diagnostic_sessions_started_total` | counter | `tenant_id`, `grade` | Total diagnostic sessions started |
| `diagnostic_sessions_completed_total` | counter | `tenant_id`, `grade`, `end_reason` | Sessions ended (`end_reason` ∈ `natural`, `abandoned`, `timeout`, `learner_quit`) |
| `diagnostic_session_duration_seconds` | histogram | `tenant_id`, `grade` | Time between `session/start` and session end |
| `diagnostic_questions_per_session` | histogram | `tenant_id`, `grade` | Number of questions asked per completed session |
| `diagnostic_verdict_total` | counter | `tenant_id`, `grade`, `skill_id`, `confidence_label` | Verdict counts per (skill, label) for distribution tracking |
| `diagnostic_routing_mode_questions_total` | counter | `tenant_id`, `mode` | Hybrid mode usage (`mode` ∈ `online`, `offline_replay`) |
| `diagnostic_offline_sync_events_total` | counter | `tenant_id`, `outcome` | Offline-batch replay events processed (`outcome` ∈ `success`, `conflict`, `partial`) |
| `diagnostic_api_request_duration_seconds` | histogram | `endpoint`, `status` | Per-endpoint latency |
| `diagnostic_api_errors_total` | counter | `endpoint`, `error_code` | Errors by code |
| `diagnostic_response_conflicts_total` | counter | `tenant_id` | Idempotency conflicts - duplicate `question_x_id` with mismatched `is_correct` |
| `diagnostic_cleanup_job_runs_total` | counter | `outcome` | Cleanup job invocations (`outcome` ∈ `success`, `error`) |
| `diagnostic_cleanup_job_recovered_sessions_total` | counter | - | Sessions where the cleanup job had to write missing verdicts |

The two `diagnostic_cleanup_job_*` counters are emitted by the cleanup CronJob (Section 8.4), not by the engine pod. The CronJob pod is short-lived and has no scraped `/metrics` endpoint, so it pushes these counters to a Pushgateway when `PROMETHEUS_PUSHGATEWAY_URL` is set (Section 10.3). All other metrics in this table are exposed on the engine pod's `/metrics` and scraped normally. Alerting on the cleanup counters (Section 14) must therefore target the Pushgateway-sourced series, not the engine pod's scrape.

### 9.2 Downstream / analytical metrics (not engine-emitted)

Some monitoring questions require joining engine output to data the engine does not have. These are computed in the AML analytics layer (Athena), not in Prometheus:

| Metric | Why it can't live in Prometheus |
|---|---|
| Per-band MainD pass rates (the headline calibration check - for learners marked `confident_mastered`, what fraction actually pass MainD if they later take it?) | Requires joining engine verdicts to subsequent MainD outcomes. Engine does not see MainD results |
| Per-skill verdict drift over time (does a skill's `confident_not_mastered` rate change month over month? May signal a content change or a cohort shift) | Aggregation across time windows is cheaper in an analytics warehouse than in Prometheus |
| Cohort-level calibration audits (re-running the testing summary's 97/80/6 calibration check against production data quarterly) | Heavy joins, infrequent reads - analytics warehouse is the right tool |

The engine emits enough Prometheus data for these downstream calculations to be derivable, but does not compute them itself.

### 9.3 Logging

**Format:** Structured JSON to stdout, one event per line. This is the engineering team's call to confirm - `aml-api-service` currently uses plain-text Winston logs. The default for the engine is JSON because it's easier to parse downstream and easier to filter PII from. If the pod log ingestion expects plain text, the engine can be configured to emit Winston-style lines instead. See Section 11.

**Standard fields per log line:**

| Field | Notes |
|---|---|
| `ts` | ISO 8601 timestamp |
| `level` | `debug`, `info`, `warn`, `error` |
| `service` | Always `aml-diagnostic-engine` |
| `version` | The engine's semantic version |
| `request_id` | Trace ID generated per request |
| `learner_id` | If applicable, opaque `identifier` |
| `tenant_id` | If applicable, opaque `identifier` |
| `sub_session_id` | If applicable |
| `message` | Human-readable summary |
| `error` | If applicable, error object with `code` and `message` |

**PII filter.** The logger strips or rejects any log line containing fields outside the allow-list above. This is enforced by the logging library's serializer - a logged object passed with an unexpected field is rejected with a build-time test (in CI) and a runtime warning (in production). The engine never logs question content, response data, or any field marked PII in Section 6.3.

**Error logs to stderr.** Severity `error` and above go to stderr; everything else to stdout. Matches AML's existing convention.

---

## 10. Deployment and operations

### 10.1 Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.11 (pinned). The engine is tested on 3.11 only. Newer minor versions (3.12, 3.13) may work but are not validated. |
| HTTP framework | FastAPI |
| MongoDB driver | PyMongo (synchronous) - sufficient for v1 throughput; Motor (async) is an alternative if engineering prefers full async |
| Prometheus client | `prometheus-client` + `prometheus_fastapi_instrumentator` (auto-generates the standard request-duration histograms) |
| Logging | `structlog` configured for JSON output, with a custom serializer enforcing the PII allow-list |
| Tests | `pytest` with `pytest-asyncio` if Motor is chosen |
| Container | Single Dockerfile, multi-stage build for size |
| Dependency lock file | `pyproject.toml` plus a lock file (`uv.lock` or `requirements.txt` with pinned versions). Lock file is committed to the repo and used in the Docker build to ensure reproducible images. |

**Why Python:** The engine algorithm exists in Python in the simulation code. The production service ports that code into a FastAPI service. The decision to deploy a Python service in the otherwise-TypeScript AML stack has been confirmed with engineering.

### 10.2 Container and deployment

**Container expectations:**

- Base image: `python:3.11-slim` (Debian-based, kept current for security patches by the AML team)
- Working directory: `/app`
- Container runs as a non-root user (uid 1000)
- Stateless container, no local disk dependencies beyond reading the config file mounted at `ENGINE_CONFIG_PATH`
- Listens on the port set by `ENGINE_PORT` (default `4001` to avoid collision with `aml-api-service`'s `4000`)
- `GET /health` is the readiness and liveness probe endpoint (see Section 5.8 for probe semantics)
- Graceful shutdown: on SIGTERM, the engine finishes in-flight requests (timeout: 30 seconds), closes MongoDB connections, exits with code 0

**Dockerfile expectations:**

- Multi-stage build for image size (build stage installs dependencies, runtime stage copies only what's needed)
- Dependency installation uses the committed lock file (no `pip install <package>` without a version pin)
- The container's entrypoint runs the FastAPI app via `uvicorn` (e.g., `uvicorn engine.api.main:app --host 0.0.0.0 --port $ENGINE_PORT`)

**Helm chart and image build pipeline:** The engine is the first Python service in the AML stack. Engineering owns the new Helm chart for the engine and the image build pipeline. The engineering specification is the source of truth for what the chart must do (env vars, secrets, probes, port, resource requests); the chart's internal structure is engineering's call.

### 10.3 Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ENGINE_PORT` | no | `4001` | HTTP listen port |
| `ENGINE_VERSION` | no | `0.10.0` (package version) | Semantic version, stamped on the stored session and verdict records for traceability. It is not returned on the API response - it lives on the persisted record. The installed package is `0.10.0`, so the unset default is correct; set it explicitly in the deployment manifest to guarantee the stamp if the package is ever repackaged. |
| `STORAGE_BACKEND` | no | `memory` | `memory` or `mongodb`. Production uses `mongodb`. |
| `MONGODB_URL` | only if `STORAGE_BACKEND=mongodb` | - | MongoDB connection string. Required when the backend is `mongodb`; ignored otherwise. |
| `MONGODB_DATABASE` | no | `aml_engine` | Database name. Used only when the backend is `mongodb`. |
| `TENANT_TOKENS_JSON` | yes | - | JSON map of `{tenant_id: shared_secret_token}` for per-tenant auth |
| `STRICT_PRIORS_REQUIRED` | no | `false` | When `true`, startup fails if any configured grade has zero priors. Default `false` (warn and continue). |
| `LOG_LEVEL` | no | `info` | One of `debug`, `info`, `warn`, `error` |
| `LOG_FORMAT` | no | `json` | `json` or `text` (Winston-style) |
| `PROMETHEUS_PUSHGATEWAY_URL` | no | - | When set, the cleanup CronJob pushes its counters (Section 9.1) to this Pushgateway. Unset means cleanup metrics are not pushed (the CronJob's pod has no scraped `/metrics` endpoint of its own). |
| `ENGINE_CONFIG_PATH` | no | `/etc/engine/config.yaml` | Path to the engine config file (slip, guess, thresholds, budgets, priors, canonical skill list) |
| `QUESTION_CALIBRATION_PATH` | no | `/etc/engine/question_parameters.csv` | Path to the per-item calibration file the `QuestionPool` loads (§6.2.1, §7.8) |
| `TENANT_QUESTION_LOOKUP_PATH` | no | `/etc/engine/tenant_question_lookup.csv` | Path to the per-tenant `(tenant, item) -> question_x_id` lookup the `QuestionPool` loads (§6.2.1, §7.8) |

The cleanup job's cadence is not an environment variable; it is the CronJob's `schedule:` field (Section 8.4).

The `TENANT_TOKENS_JSON` value should come from a Kubernetes secret. Rotating a token is a secret update plus a pod restart.

### 10.4 Config loading at startup

The engine loads these at startup:

| Item | Source | Reload mechanism |
|---|---|---|
| Engine parameters (slip, guess, thresholds, budgets, canonical skill names) | YAML config file at `ENGINE_CONFIG_PATH` | Container restart |
| Lattice edges | `lattice_edges` MongoDB collection | Container restart (v1) or scheduled reload (v2) |
| Priors per (grade, skill) | YAML config file (same as engine parameters) for v1; can move to a MongoDB collection in v2 | Container restart |
| Per-item calibration | Calibration file at `QUESTION_CALIBRATION_PATH` (§6.2.1) | Container restart |
| Per-tenant question lookup | Lookup file at `TENANT_QUESTION_LOOKUP_PATH` (§6.2.1, §7.8) | Container restart |
| Per-tenant tokens | `TENANT_TOKENS_JSON` env var | Container restart |

If any required configuration is missing or invalid at startup, the engine logs the failure and exits with non-zero status - fail-fast rather than running with partial config.

### 10.5 Offline tree generation batch job

The offline tree artifacts are generated by a separate batch process, not by the engine service itself.

**What it does:** Given the current lattice, priors, anchors, canonical skill list, the per-item calibration file, and the per-tenant question lookup, it builds the **four per-operation trees** for each (tenant, grade) and writes them as gzipped file artifacts (one bundle per (tenant, grade)) under `OFFLINE_ARTIFACT_DIR`, each stamped with the `engine_version` it was built against. It builds per tenant because the active question set differs by tenant (§7.8): the generator selects in `item` space using the same logic as the online engine, then resolves each node's chosen `item` to a single `question_x_id` for that tenant through the same lookup, so the offline trees and the online path always agree on which question a given answer path leads to. The four per-operation trees are walked at run time by the three-pass base-first follow described in §4.3.

**Deterministic selection.** Tree generation runs the question pool in deterministic mode (§7.8 step 5): at each node it takes the single highest-discrimination question (smallest `item` as the tie-break) rather than a random pick. This makes generation reproducible - the same inputs always yield the same tree - which is required for a shippable, versioned artifact. The online engine still uses random selection within the discrimination window; the offline tree is the deterministic projection of the same selection rule.

**Tractability and the state key.** A naive tree enumerates every answer path, which grows exponentially with the number of questions. The generator deduplicates equivalent engine states (two answer paths that leave the engine in the same posterior and observation state share the same subtree) to keep size manageable. This was built and measured against engine 0.9.0: the four per-operation trees compress to roughly 5.4 MB on disk at G5 (the largest grade) and are served as about 24.8 MB of canonical JSON (the size the client downloads), within the accepted envelope and decreasing sharply at lower grades. They are served on demand from the fetch endpoint (Section 5.9), not inlined into the session-start response.

The state key must include enough posterior precision to be sound. Keying on 2-decimal posteriors (an earlier choice) has a rare soundness gap at G5: two states whose third-decimal posterior difference flips the engine's information-gain pick get merged, which was observed on G5 Subtraction. **The generator keys on 3-decimal posteriors,** which removes the gap at a negligible cost (about +2.4% nodes, +1.5% gzipped). The earlier 2-decimal key was sound at G2 (the grade an earlier probe checked), so the gap only appears at G5's larger skill set; this is a case where empirical measurement corrected a spec assumption.

**Determinism.** Generation is deterministic and was checked by replaying many random root-to-leaf paths against the engine's own deterministic choice; residual mismatches are minor and accepted (G2 1, G3 2, G4 and G5 0).

**Priors are shared across tenants for now.** Per-tenant priors are not yet available (Telangana response data is pending; other tenants borrow Delhi). Because priors set the branch structure, node counts are currently identical across tenants and only the resolved `question_x_id`s differ (each tenant's active set). When real per-tenant priors arrive, especially Telangana, the trees must be regenerated; the structure may shift, though size should stay similar because it is depth-driven.

**Deployment:** The batch job is a Python script in the same repository as the engine service. It is packaged as a separate container image (or the same image with a different entrypoint - engineering's call) and deployed as a **Kubernetes CronJob** rather than running inside the engine service pods.

**Why a CronJob:**

- Batch jobs that take more than a few seconds should not block the engine service pods
- Resource limits and scheduling are independent of the engine service
- Failures in tree generation are isolated and surface as failed CronJob runs in the cluster's monitoring

**When to run it (regenerate on input-change):** The tree depends on exactly three inputs - the priors, the lattice, and the question pool (including calibration and the per-tenant lookup). Rebuild it as the final step whenever any of these changes:

- After any change to the priors
- After any change to the lattice (edges added, weights changed)
- After any change to the canonical skill list or anchors
- After any change to the per-item calibration
- After any change to a tenant's active-question list (which changes that tenant's lookup, hence that tenant's tree)
- After any change to the engine's question-selection algorithm

Learner responses do not appear in this list: a learner's answers update only that learner's live session, never the tree's inputs (design document §3.8, §4.11). There is therefore no streaming or nightly-reactive regeneration; the tree is rebuilt deliberately when one of its inputs is deliberately changed.

**Schedule:** The CronJob does NOT run on a regular schedule by default. It is triggered when one of the change conditions above applies (`kubectl create job --from=cronjob/diagnostic-tree-generator tree-gen-<date>`). A nightly idempotent run that no-ops when nothing has changed is acceptable if engineering prefers, but the default is on-change.

**Promotion to active:** The batch job writes new trees with `is_active=false`. Promotion to active requires a manual step (a separate `kubectl create job` against a `promote-tree` job, or a small admin endpoint - engineering's call). Once the new tree is promoted, the engine starts returning it at session-start; in-flight sessions continue using the tree they started with.

**Image and code sharing:** The batch job shares the engine algorithm code (tree generation reuses the same lattice, routing, and question-selection logic) but does NOT need the FastAPI dependencies. Engineering decides whether to ship one image with two entrypoints or two separate images.

### 10.6 Build-time work items

These are one-time tasks that must be completed before the first production session:

1. **Skill-name-to-UUID mapping per tenant.** For each state-instance of AML, confirm that each of the canonical L2.5 skill names (40; 39 in the Delhi scope) matches a `skill_master.name.en` value (or document the translation that `aml-api-service` will apply).
2. **Initial lattice seeding.** Import the 12 lattice edges into `lattice_edges`. The edges are documented in the existing `lattice_edges_final.xlsx` and the testing summary.
3. **Calibration file deployment.** Place the per-item calibration file where the engine loads it (`QUESTION_CALIBRATION_PATH`).
4. **Per-tenant question lookup build.** For each tenant, take that tenant's active-question list (the six raw fields plus the `question_x_id`), run the build step to construct the `(tenant, item) -> question_x_id` lookup (§7.8), and place the combined lookup where the engine loads it (`TENANT_QUESTION_LOOKUP_PATH`).
5. **Initial tree generation.** Run the batch job once per (tenant, grade), validate, promote to active.
6. **Per-tenant secret generation.** Create one shared-secret token per AML instance, distribute it to each instance's `aml-api-service` configuration, and register the same token in the engine's `TENANT_TOKENS_JSON`.
7. **Configure deployment.** Set environment variables, deploy the container, verify `/health` returns 200, verify Prometheus scrape works.
8. **Smoke test.** Run a single end-to-end session from a test learner and verify the verdicts are written correctly.

---

## 11. Versioning and compatibility

The engine writes `engine_version` to every session document and every verdict document (on the stored records; it is not returned in the API response). This section defines how versions are bumped and what downstream systems should do with them.

### 11.1 Version bumping rules

The engine uses semantic versioning (`MAJOR.MINOR.PATCH`):

| Change type | Version bump | Examples |
|---|---|---|
| Bug fix that does not affect verdicts | PATCH (`0.9.0 -> 0.9.1`) | Logging fix, performance fix, internal refactor |
| Algorithm change that affects verdicts | MINOR (`0.9.0 -> 0.10.0`) | Threshold change, new lattice edge, new question selection rule |
| Breaking change to API contract or data model | MAJOR (`0.9.0 -> 1.0.0`) | New required field, removed field, changed endpoint URL |

**Backward-compatible additions** - a new *optional* request field, or a new endpoint - do not force a MINOR or MAJOR bump on their own, because they do not break existing callers. The v9 offline-serving and raw-response work (the `offline_tree` reference, the `offline-tree` and `responses` GET endpoints, and the optional `raw_response` field) were such additions and were kept within `0.9.0` as completion of the v9 scope. The **mixed-mode and deactivation-failsafe work** that followed, although also additive at the wire level (the `offline-batch` and `replace-question` endpoints and the optional switched-off fields), added real new capability, and so was released as the MINOR bump to **`0.10.0`**.

### 11.2 Config-incompatible changes

Some config changes are incompatible with previously generated trees or in-flight sessions. These require a coordinated update:

| Change | Required action |
|---|---|
| Canonical skill list changed (skill added, renamed, removed) | Regenerate offline trees; in-flight sessions started before the change continue using the old `posteriors` keys until they end |
| Lattice edges changed | Regenerate offline trees; engine restart picks up new edges from MongoDB |
| Priors changed | Regenerate offline trees; engine restart picks up new priors from config |
| Slip, guess, or threshold values changed | Engine restart; in-flight sessions continue with the values they started with (engine reads its `engine_version` from the session document when resuming) |

### 11.3 Downstream consumer guidance

Downstream systems (the AML practice router, analytics) read verdicts and should be aware of `engine_version`:

- **Same MAJOR, any MINOR/PATCH**: verdicts are comparable and can be aggregated
- **Different MAJOR**: do NOT aggregate verdicts across major-version boundaries without explicit migration logic
- **Recommendation**: downstream queries that aggregate or compare verdicts over time should include the `engine_version` field and either filter to one major version or document the cross-version assumptions

---

## 12. Error handling and retry semantics

This section consolidates the error codes from Section 5 with their retry semantics, to give `aml-api-service` clear guidance on how to handle each error class.

| Error code | HTTP status | Retryable? | Recommended caller behaviour |
|---|---|---|---|
| `INVALID_TENANT_TOKEN` | 401 | No | Log and alert; do not retry. Indicates misconfiguration. |
| `INVALID_GRADE` | 400 | No | Log; surface to caller. Indicates bad input from upstream. |
| `INVALID_SKILL_ID` | 400 | No | Log; surface to caller. Indicates bad input from upstream. |
| `LEARNER_MISMATCH` | 400 | No | Log; surface to caller. Indicates bad input or session state issue. |
| `PII_FIELD_PRESENT` | 400 | No | Log; surface to caller. The request must be reconstructed without the PII field. |
| `SESSION_ALREADY_EXISTS` | 409 | No (idempotent) | The session already exists. Caller can proceed with the existing session via `/response` or `/verdicts`. |
| `SESSION_ALREADY_ENDED` | 409 | No | The session is complete. Caller can fetch verdicts via `/verdicts`. |
| `SESSION_NOT_FOUND` | 404 | No | The session does not exist on this engine. Caller may need to start a new session. |
| `SESSION_NOT_COMPLETE` | 409 | Yes (with delay) | Verdicts are not yet final. Retry after the session is ended. |
| `RESPONSE_CONFLICT` | 409 | No | The same `question_x_id` was submitted with conflicting `is_correct`. Caller must reconcile before retrying. |
| `NO_TREE_FOR_GRADE` | 404 | No | No tree exists for this tenant/grade (raised only by the fetch endpoint, Section 5.9; `session/start` returns `offline_tree: null` instead). The session proceeds online; retry does not help. |
| `NO_QUESTION_FOR_SKILL` | 500 | No | Content pool has no active question for the chosen skill. Engineering and content team must add a question. Retry will not help. |
| `NO_USABLE_QUESTION` | 422 | No | A caller-supplied switched-off list covers every available question for the grade, so the diagnostic cannot start (deactivation failsafe, Sections 5.3 and 7.8). A client-input condition: fix the list. |
| `OFFLINE_BATCH_TOO_LARGE` | 400 | No | An offline batch is implausibly large (more than twice the grade budget) - a corruption guard (Section 5.11). A correct device never sends this. |
| `VERDICTS_NOT_WRITTEN` | 500 | Yes (with delay) | Verdicts are being computed. Retry after a short delay (the cleanup job runs every 5 minutes). |
| `SESSION_LOCKED` | 503 | Yes (with backoff) | v2 only. Another instance holds the session lock. Retry with exponential backoff. |
| Transient network / connection errors | n/a | Yes (with backoff) | Treat as if the request was not received. Idempotency rules apply (Section 8.3). |

**Recommended retry policy for `aml-api-service`:** exponential backoff starting at 100ms, max 3 retries, max delay 2 seconds. Total retry budget capped at 5 seconds per request to avoid blocking the learner UI.

---

## 13. Tenant onboarding

The operational process for adding a new state instance (Karnataka, future states) to the engine.

| Step | Owner | Description |
|---|---|---|
| 1 | AML platform team | Decide on a `tenant_id` (Text UUID) for the new state; register in the central tenant directory |
| 2 | Engine team | Generate a per-tenant shared-secret token (32 random bytes, hex-encoded). Store in the cluster's secret management system |
| 3 | Engine team | Add the `{tenant_id: token}` entry to `TENANT_TOKENS_JSON` in the engine deployment's secret. Restart engine pods to pick up the new entry. |
| 4 | New state's `aml-api-service` owner | Receive the token securely (1Password, SOPS, sealed secrets - engineering's call). Configure the new state's `aml-api-service` with the token and the engine's URL. |
| 5 | Engine team | Validate that the state's `skill_master` collection has entries matching the canonical L2.5 skill names (40; 39 in the Delhi scope). Document any name mapping the state's `aml-api-service` must apply. |
| 6 | Both teams | Run an end-to-end smoke test from the new state's instance: start a session, submit responses, end the session, verify verdicts written with the correct `tenant_id`. |
| 7 | Engine team | Confirm `diagnostic_verdict_total` metric labeled with the new `tenant_id` shows up in Prometheus. Add the tenant to dashboards. |

**Token rotation:** Same process as onboarding, but with a transition window. Add the new token to `TENANT_TOKENS_JSON` alongside the old one (the engine accepts both during the transition), notify the state's `aml-api-service` owner to update, then remove the old token after confirmation.

---

## 14. Operational runbook (open items for engineering)

The runbook below lists the operational scenarios the engine team will encounter. The spec defines the engine's *behaviour* in each scenario; the *response procedure* (who acts, what tools they use, what alerts fire) is owned by engineering and should be documented as part of the deployment.

| Scenario | Engine behaviour | Required from engineering |
|---|---|---|
| A session is `active` for longer than expected (>1 hour) | Engine does not auto-end; depends on `aml-api-service` to call `/session/:id/end` with `reason=timeout` | Alerting threshold; investigation playbook |
| Verdicts for a `complete` session are not written | The cleanup job (Section 8.4) recomputes them on its next run | Alert when cleanup job recovers >N sessions per hour; investigation playbook |
| MongoDB connection drops | Engine returns 503 from `/health` until reconnected. In-flight requests fail with 500 | Alerting + incident response procedure |
| A tenant token needs immediate rotation (compromise suspected) | Update `TENANT_TOKENS_JSON`, restart pods. Old token immediately invalid; sessions in flight for that tenant will fail | Documented rotation procedure with response time SLA |
| Cleanup job is failing repeatedly | `diagnostic_cleanup_job_runs_total{outcome="error"}` increments (Pushgateway-sourced series, see Section 9.1); verdicts may go missing | Alerting; investigation playbook |
| Offline tree generation fails | The CronJob completes with non-zero exit; no new tree version is written | Alerting; investigation playbook |
| A grade has no tree | `/session/start` returns `offline_tree: null` (no error); the fetch endpoint (Section 5.9) returns `404 NO_TREE_FOR_GRADE` only if the tree is explicitly requested | Alerting; investigation playbook |
| The engine pod restarts unexpectedly | Active sessions resume cleanly via MongoDB state (Section 8.4); no data lost | Alerting on pod restart frequency |
| Disk pressure on the MongoDB volume | Engine returns slow responses, then 503 | Capacity planning; alerting |
| A false skip is detected after the fact (learner already received `skip_maind` on a skill later found not-mastered, e.g. a G2 Subtraction regression surfacing live) | The engine does not retroactively change a written verdict; turning the feature flag off only affects new sessions | Define a remediation path: how to re-open the affected skill's MainD for already-scored learners (re-queue the skill, or a targeted re-diagnostic), plus the detection signal that triggers it. This is a required safety procedure before wide rollout, not just alerting. |

Engineering should produce a runbook document referencing this section, with concrete alert names, dashboards, on-call rotation, and escalation paths.

---

## 15. Backup and data lifecycle (open items for engineering)

The engine writes three collections: `learner_diagnostic_sessions`, `learner_skill_verdicts`, `lattice_edges` (offline trees are gzipped file artifacts under `OFFLINE_ARTIFACT_DIR`, not a collection). The questions below are not answered by the engine team; engineering owns the answers.

| Question | Default assumption (subject to engineering confirmation) |
|---|---|
| What is the backup frequency for these collections? | Same as AML's other operational collections (`learner_sub_sessions`, `learner_proficiency_aggregate_data`, etc.) - engineering to confirm |
| What is the retention period for `learner_diagnostic_sessions` documents? | Indefinite by default. Sessions are small (<10 KB each). If retention is enforced, the engine team should be consulted on impact to historical analysis |
| What is the retention period for `learner_skill_verdicts` documents? | Indefinite by default. Verdicts feed downstream analytics, so deleting them affects reporting |
| When a learner is deleted (GDPR-style data subject request), how is it propagated? | Engine deletes by `learner_id` on receipt of a deletion request. Operational process for receiving and propagating these requests is owned by the AML platform team |
| Are backups tested? | Engineering owns backup validation. Restore procedure should be documented |
| What is the disaster recovery RPO and RTO for engine data? | Engineering to define based on AML's overall DR policy |

Engineering should produce a data lifecycle policy document referencing this section.

---

## 16. Resolved engineering decisions

This section records the resolution of the items this spec previously held as pending. Each carries a tag indicating who acts and when:

- **DECIDED** - settled; no further action needed.
- **CALL FOR ENGINEERING** - a real choice engineering owns; a recommendation is given.
- **ENGINEERING TO CONFIRM** - a default is set; engineering verifies it fits AML's environment.
- **NOTE TO ENGINEERING** - informational; no decision, just an implementation fact.
- **REVISIT DURING PILOT** - action happens around pilot launch.
- **REVISIT AFTER PILOT** - cannot be finalized without pilot data; carries a default meanwhile.

Several items resolve to "no engine code change," meaning they are operational or deployment concerns that do not affect the engine's own behavior.

| # | Item | Tag | Resolution |
|---|---|---|---|
| 1 | Cleanup job cadence (8.4) | DECIDED | Kubernetes CronJob every 5 minutes. Isolated from the request path; the orphaned-verdict case is rare and not learner-facing, so 5 minutes is comfortable. |
| 2 | Per-session lock for multi-copy operation (8.6) | DECIDED + REVISIT AFTER PILOT (expiry value) | Per-session lock, required only when running more than one instance. Per-session scope, millisecond holds, no external calls inside the lock, idempotent operations, crash-release expiry. Default expiry 2 seconds; finalize after the pilot from the p99 locked-section duration (about 10x). |
| 3 | Error-code names (5) | CALL FOR ENGINEERING | Keep the spec's SCREAMING_SNAKE_CASE names unless they clash with AML's house style; if they clash, rename once and uniformly. No behavior change. |
| 4 | Log format (9.3) | ENGINEERING TO CONFIRM | Structured JSON to stdout (the right default for a log aggregator and for `request_id` tracing). Confirm it suits AML's log pipeline. |
| 5 | Service-to-service auth (5.1) | CALL FOR ENGINEERING | Per-tenant shared secrets in `X-Internal-Service-Token` for the pilot. If AML runs a service mesh, mutual TLS is worth considering instead (and removes item 8). |
| 6 | Helm chart (10.2) | NOTE TO ENGINEERING | No engine code change. Engineering owns the chart; reuse AML's standard service chart template if one exists. |
| 7 | Image registry and build pipeline (10.2) | NOTE TO ENGINEERING | No engine code change. Recommend extending AML's existing pipeline with a Python build and test stage rather than a separate pipeline. |
| 8 | Secret storage and rotation (10.3) | CALL FOR ENGINEERING | Kubernetes Secret with rotate-by-restart for the pilot (restart cost is negligible at pilot scale). Automated rotation is a scale-up upgrade. Moot if item 5 adopts a mesh. |
| 9 | Latency target (5) | CALL FOR ENGINEERING | Engineering sets a concrete p95/p99 target. No engine behavior change. The measured p99 of the locked section feeds the item 2 expiry after the pilot. |
| 10 | Peak concurrency (4) | CALL FOR ENGINEERING | Engineering estimates peak concurrent sessions from the rollout plan. No engine code change. Decides single-copy vs multi-copy, which decides whether the item 2 lock is exercised during the pilot. |
| 11 | Service mesh / gateway placement (5) | NOTE TO ENGINEERING | The engine is gateway-agnostic: it does its own shared-secret auth and accepts direct HTTP, and can also sit behind a mesh or gateway with no code change. Engineering confirms placement. |
| 12 | Alerting and dashboards (9, 14) | REVISIT DURING PILOT | No engine code change; the engine already emits the metrics. Built by the AML team (read access to `/metrics` is enough). Build a minimal dashboard before pilot launch covering the Section 14 conditions; refine once real traffic flows. |
| 13 | Operational runbook (14) | REVISIT DURING PILOT | No engine code change. The AML team operates the engine until any future engineering handover, so the AML team writes the runbook. Depends on item 12; draft before pilot from Section 14 plus the item 12 alerts. |
| 14 | Backup and data lifecycle (15) | NOTE TO ENGINEERING | No engine code change provided deletion is a database-layer TTL or an external job, not an engine responsibility (the engine must not perform hard deletes). The no-PII design lowers the stakes, but retention for minors' data may be governed by AML-wide rules; confirm with the data-governance owner. |
| 15 | Offline-tree generation (10.5) | DECIDED | Build the offline tree into the prototype, per tenant. Regenerate on input-change (new priors, calibration, lattice, skills/anchors, a tenant's active-question list, or the selection algorithm), not on a schedule and not via a stream. |
| 16 | Question selection and ID resolution (7.8) | CALL FOR ENGINEERING | The engine selects (required for per-item calibration to reach the Bayes update). It selects in `item` space and never reads a tenant's live `questions` collection; it resolves the chosen `item` to a single `question_x_id` through a per-tenant lookup built ahead of time from each tenant's active-question list (the six raw fields plus the `question_x_id`), with a deterministic tie-break where one `item` maps to several `question_x_id`s. The engine returns a `question_x_id`. Per-tenant offline trees follow from this. |
| 17 | Where calibration values live (6.2.1) | REVISIT AFTER PILOT | Calibration stays in the sidecar file the engine loads. Folding the values onto the question records waits for a single shared content service (no timeline); until then the sidecar is the correct choice, not merely a convenience. |
| 18 | Shared vs tenant-specific pools (7.8) | DECIDED (shared pool) + REVISIT AFTER PILOT (cross-tenant validity) | The pool is shared across tenants; calibration is Delhi-derived (others borrowed or defaulted). Whether Delhi calibration generalizes to other tenant populations is an assumption to validate once per-tenant pilot data exists. The calibration script now warns when a question's slip or guess differs across tenants that both have enough data, by at least 0.05 (reported in bands: 0.05 small, 0.10 large, 0.15+ extreme), matching the published convention for a meaningful difference in this kind of model and the script's existing practical-significance cutoff. |
| 19 | Recalibration pipeline (design document 4.3, 4.11) | REVISIT AFTER PILOT | Recalibration stays a manual, deliberately-triggered step. Automating it into a pipeline waits for a single combined response database (no timeline). Recalibration should be deliberate and reviewed regardless, so values do not shift silently mid-deployment. |
| 20 | Anchor-score derivation cohort (Appendix A, item 4) | DECIDED | The anchor recommendations stay as authored, on the combined Telangana + Delhi cohort. They were verified to produce the same recommendation for every learner-grade and operation under Delhi-only mastery, so the combined-cohort authoring is **accepted and will not be changed** - a settled decision, not an open inconsistency. |
| 21 | Seventh item-key field, `response_includes_remainder` (7.8) | DECIDED | The division-only seventh key field is **retained**, though the current 667-item bank has no two-format division pairs and it is therefore inert today. It is kept as regression protection: if a quotient-only and a quotient-plus-remainder form of the same operands are reintroduced, the seventh field keeps them distinct. |

Three dependency chains are worth keeping in view: items 9 and 10 together decide whether the pilot needs multiple instances, which decides whether the item 2 lock is exercised and supplies the p99 that finalizes its expiry; item 13 depends on item 12, which depends on the metrics the engine already emits; and items 16, 17, and 19 are gated on two pieces of future infrastructure (a single shared content service and a combined response database), so the current sidecar-and-manual design is correct for now with defined upgrade paths (design document Section 7).

---

## 17. Offline-walk handover pack for the AML app team

This section is a step-by-step guide for the AML app team building the offline walk in TypeScript inside `aml-portal`. It is written to stand on its own: read it top to bottom and you have everything needed to build, test, and scope the work. (The same pack appears in the Implementation Spec; the two are kept identical.)

### 17.1 What you are building, and what you are not

You are building the part that **chooses and records questions while the device is offline**. You are **not** building anything that scores or judges mastery - that stays on the server. Keeping this line clear is the single most important thing in this pack.

| Job | Who does it |
|---|---|
| Show the learner a question and read their answer | `aml-portal` (you), online and offline |
| While online: ask the engine for the next question | `aml-api-service` -> engine (`/response`) |
| While offline: choose the next question by following the downloaded tree | `aml-portal` (you) - this is the offline walk |
| Mark each answer right or wrong | `aml-portal` (you) - a simple correctness check, the same one used online |
| Record each answer locally (id, skill, correctness, the typed answer, and when) | `aml-portal` (you), in IndexedDB |
| On reconnect: send the offline answers to the engine | `aml-portal` -> `aml-api-service` -> engine (`/offline-batch`, Section 5.11) |
| Turn answers into mastery verdicts | the **engine**, server-side, when the batch is ingested |
| Produce the final learning state (verdict + misconception tag) | the **data team**, downstream |

So the device sequences, marks, records, and syncs. It does not compute posteriors or verdicts, and it does not need the calibration parameters for scoring - the tree already encodes every branch the walk needs.

### 17.2 What you receive

Three artifacts travel with this pack. They are the contract: build against them, and the port is correct by construction.

| Artifact | What it is | How you use it |
|---|---|---|
| `offline_follow.py` (the walk reference) | The Python source of the exact walk: `follow_capped(...)`, the replay-to-first-unanswered entry point, and the skip-and-do-not-record rule. It is small and readable. | Port its logic to TypeScript, line-for-line in behaviour. It is the specification of "what to ask next," in runnable form. |
| `vectors/offline_walk_vectors.json` (the shared test vectors) | A set of recorded walks: for each case, the inputs (grade, the answers given) and the exact question sequence the walk must produce. Covers fresh starts, resumed walks (online-then-offline), all-correct / all-wrong / mixed answer patterns, and the unavailable-question skip. | Your TypeScript port must reproduce every vector's sequence and count exactly. This is your acceptance test (Section 17.5). |
| `offline_followsim.py` (the harness) | The Python harness that runs the walk in bulk and checks it against the engine. | Reference only - it shows how the walk is exercised and how equivalence is checked; you do not port it. |

### 17.3 The model: port, do not embed

Port the **walk logic** into TypeScript. Do not try to run or embed the Python engine on the device, and do not reimplement scoring. The division of material is:

- **The tree and its parameters** come from the engine, already built, via the offline-tree endpoint. You download and cache them; you do not compute them.
- **The walk** (which node to visit next, when to stop) is the logic you port from `offline_follow.py`.
- **Scoring** never happens on the device. You record answers and sync them; the engine scores.

The reason this is safe: the walk is pure "follow the tree by correctness," with no probability maths. All the hard maths (posteriors, the lattice, verdicts) lives on the server and runs on the synced history.

### 17.4 The offline walk, step by step

**Step 1 - Get the tree and keep it.** When the learner starts (online), `session/start` returns an `offline_tree` reference (Section 5.3). If you want offline capability, fetch the actual tree once from its `fetch_path` (the offline-tree endpoint, Section 5.9) and cache it by `sha256` in IndexedDB. The bundle holds the four per-operation trees (Addition, Subtraction, Multiplication, Division), the shared per-grade parameter block, and a `manifest` of every `question_x_id` the trees can reach - pre-load the content for those ids so you can show any question offline.

**Step 2 - Keep the latest resumption token.** `session/start` and every online `/response` return a small `resumption_token` (Section 5.4): the last-answered question (`resume_anchor`), the budget used, and one entry per answer so far. Overwrite your cached copy every time. This token is how the offline walk knows where the session already is.

**Step 3 - When the connection drops, find the entry point.** Do not start the tree from the top. Take the answers from the resumption token and "replay" them into the tree: for each operation, start at the root and follow the recorded correctness (correct -> the on-correct child, wrong -> the on-incorrect child) as long as the node's question has already been answered. The first node whose question has **not** been answered is your entry point - that is the first question to ask offline. Match answered questions by their **content** (the `item` a node resolves to), not by the raw `question_x_id`, because the online path and the tree can use different id variants of the same question.

![Offline resume: finding the entry point](img/mixed_mode_entry_point.png)

**Step 4 - Walk the tree (base-first, three passes, one budget).** Sweep the four operations in the fixed order **Addition, Subtraction, Multiplication, Division**, and make three passes over them, all under one hard question budget for the grade (25 / 42 / 59 / 76 for G2 / G3 / G4 / G5):

1. **Base pass** - walk each operation's tree up to that operation's base cap.
2. **Misconception backfill** - continue a little past the base cap to cover misconceptions not yet seen, up to the per-operation allowance.
3. **Skill harvest** - if budget remains, ask a few more to settle still-uncertain skills.

At each node you ask its question, read the answer, mark it right or wrong, and move to the on-correct or on-incorrect child. Never ask the same content twice (the no-repeat check is in `item` space, as in Step 3). Stop the moment the grade budget is reached - it is a hard cap and must never be exceeded.

**Step 5 - The skip-and-do-not-record rule.** If the walk lands on a node whose question you cannot actually show - most often because it was switched off on the app after the tree was built - do this: **skip the node, follow its on-incorrect branch, record nothing, and spend no budget.** Treat "cannot show" exactly as "not asked." Do not guess an answer, and do not count it. (This mirrors the engine's own handling of switched-off questions online, Section 7.8.)

**Step 6 - Record every answer locally.** For each question actually answered, store in IndexedDB: `question_x_id`, `skill_id`, `is_correct`, the learner's typed answer (`raw_response`), and `asked_at` (a timestamp). You will need all five when you sync.

**Step 7 - On reconnect, sync the batch.** Send the recorded offline answers to the engine via `POST .../offline-batch` (Section 5.11), including the `tree_id`, `tree_version`, and `tree_compat_version` of the tree you walked, and the `resume_anchor` from your token. The engine folds the batch into the one session, re-scores the whole history, and returns the next question (if the learner continues) or the final verdicts. Sending the same batch twice is harmless. If the learner keeps switching between online and offline, repeat these steps - the session is a single unified thing and can switch any number of times.

### 17.5 How you know the port is correct (the acceptance bar)

The bar is exact reproduction of the shared vectors. For every case in `vectors/offline_walk_vectors.json`, feed your TypeScript walk the same inputs and confirm it produces the **same question sequence and the same count** - no more, no less, in the same order. Wire this as an automated test in the `aml-portal` build so a future change cannot silently drift from the engine. If every vector passes, the walk is correct; the vectors were generated from the engine's own walk, so matching them means matching the engine.

### 17.6 Scope: what is in, and what is deferred

- **In scope:** a session that starts **online** and then goes offline (with the resumption token in hand), any number of switches, and syncing each offline stretch back through `offline-batch`. This is the pilot's mixed-mode.
- **Deferred:** a **never-connect cold start** - running the whole diagnostic on a device that has never been online and so never received a resumption token or a fresh tree. That is a later phase and is not part of this pack.

---

## Appendix A - Known limitations

These are the engine's known weaknesses, carried forward from the design document and testing summary. They are documented here so engineering and the AML team can monitor for them in production.

| # | Limitation |
|---|---|
| 1 | **Simulation-only validation.** The engine's performance (confident-verdict accuracy 93.3% online and 96.0% offline versus 86.9% static, and the savings and calibration figures in Section 1) was measured in simulation by replaying learners' real entry mastery records (with question responses simulated from a fixed 0.90/0.15 model) against engine 0.9.0. It has not been validated against live production traffic. Because responses were simulated i.i.d., the pilot is also the first test against real answer patterns - fatigue, streaks, item-specific difficulty - not merely sim-to-field. The first deployment is effectively a pilot. |
| 2 | **Two persistent bad buckets.** In simulation, G2 Subtraction reaches only ~74% accuracy (vs the static diagnostic's 82%), and G4 Addition reaches ~75% (vs 87%). Both are documented in the testing summary §11. Watch these in production. |
| 3 | **3% false-skip rate at strict thresholds.** When the engine says `confident_mastered`, it is right 97% of the time. The remaining 3% are learners who get `skip_maind` but were actually not yet mastered. Loosening thresholds reduces this but also reduces the size of the `confident_mastered` band, costing savings. |
| 4 | **Calibration cohort specificity.** All numerical engine inputs (priors, lattice edge strengths, and per-item slip/guess) are derived from Delhi data. The lattice's edge structure was identified through Telangana P(B\|A) analysis, but the runtime values come from Delhi Entry→Entry measurements. Anchor recommendations were authored using combined cohort mastery but have been verified to produce the same 35 anchor recommendations (the recommended anchor skill for each learner-grade and operation in the anchor table) under Delhi-only mastery; this combined-cohort authoring is an accepted decision that will not be changed (Section 16, item 20). Per-item calibration is Delhi-derived too, with borrowed or default values for questions used only in other tenants or with thin data. Populations that differ systematically from Delhi may show different distributions; the calibration script's cross-tenant divergence warning (Section 16, item 18) and the downstream per-band MainD pass-rate metric are the signals for when recalibration on a tenant's own data is warranted. |
| 5 | **Per-item calibration is mostly borrowed for now.** Each question uses its own measured slip and guess where available, but only Delhi questions had enough clean data to estimate individually - 55 of the 667 items are directly estimated and the other 612 are borrowed from the most similar calibrated question. As pilot data accumulates and recalibration runs, the share of directly-measured values grows. The model behind the calibration is also the simplest in its family (one skill per question, no modelling of specific wrong-answer choices). |
| 6 | **Discrimination floor is grade-sensitive.** The selection window applies a 0.50 discrimination floor on the grade-resolved row (Section 7.8 step 4). A small number of questions clear the floor at most grades but fall below it at one grade; the floor must therefore be evaluated on the per-grade value, not a pooled value, or such a question would be wrongly included or excluded for the affected grade. |
| 7 | **Numbers operation not covered.** Out of scope for v1 (see Section 2). Place-value misconceptions are picked up post-diagnostic by the misconception classifier on other operations' responses.

To enable this change, the following content logic / rules need to be implemented:
- if the verdict for the ‘2-digit addition without carry’ skills is either uncertain or confident_not_mastered in the Dynamic Diagnostic (i.e., the recommendation for ‘2-digit addition without carry’ is either take_maind_diagnostic or take_maind_confirmation), then the learner needs to take the MainD for both ‘Numbers’ and ‘2-digit addition without carry’.
- if the verdict for ‘2-digit addition without carry’ is confident_mastered in the Dynamic Diagnostic (i.e., recommendation for ‘2-digit addition without carry’ is skip_maind), then the learner needs to take the MainD for both ‘Numbers’ and ‘2-digit addition without carry’. |
| 8 | **G6-G8 use G5 inputs, unmeasured for older learners.** Grades 6, 7, and 8 are scored with the G5 skill set, question budget, and G5-derived Delhi priors (Section 2). Older learners may differ systematically (different forgetting and profile patterns) from the G5 population the priors were measured on; treat G6-G8 verdicts with corresponding caution until their own data is available. |

---

## Appendix B - Considered alternatives

The dynamic engine's design choices were made after testing several alternatives. The alternatives below were considered and rejected. Full detail is in the Testing Summary (separate document).

| Alternative | What it is | Why rejected |
|---|---|---|
| **Routing Option 2 - transition API** | Engine called only at operation boundaries, not per question | Lost too much value when an early operation resolved unexpectedly; less responsive to cross-operation evidence |
| **Routing Option 3 - per-turn API** | Equivalent to Option 1 in routing decisions; the offline tree just precomputes what Option 3 would compute live | Functionally identical to Option 1, so we kept Option 1 (the tree) for its offline use case |
| **MDE (Minimum Direct Evidence) routing** | Force at least one direct test on every skill | Wasted questions on skills already resolved by propagation; net accuracy was equivalent or worse |
| **Lever 1 - forced retests** | Re-test resolved skills to drive down false-skip rate | Cost more questions with no improvement in accuracy; the existing verification mechanism is sufficient |
| **No verification trigger** | Trust propagation-resolved skills without confirmation | False-skip rate jumped from 3% to ~8%; verification is cheap insurance |
| **Monotonic prior adjustment** | Smooth priors to enforce sequence ordering (lower-grade skills always at least as mastered as higher-grade) | Introduced systematic bias; raw priors are noisy but unbiased and behave better in practice |
| **G3-replaces-G2 substitution** | Use G3 priors for G2 learners where G2 data is sparse | Created its own bias and did not improve G2 accuracy; G2 priors are kept as-is |
| **Other named CDM models as the runtime scorer (DINA, classical IRT, BKT)** | Various more sophisticated psychometric models with Q-matrices, item-specific parameters, learning transitions | Rejected only as the *runtime* scorer; the simpler Bayes-plus-lattice model performed well enough in simulation. Note a two-class DINA model *is* used offline to calibrate per-item slip/guess (§7.7) - that is a calibration step, not the runtime scorer. These remain viable v2 runtime directions if data shows the simple model has hit a ceiling. |

---

## Appendix C - Canonical L2.5 skill list

The engine references skills by canonical name. The list below is the source of truth - all 40 names that may appear as `skill_id` (39 in the Delhi scope; the 40th, listed at the end, is served only in non-Delhi tenants) in API calls. State-instance `aml-api-service` is responsible for mapping its local `skill_master` entries to these canonical names.

**Maintenance:** The list is owned by the engine team. Adding or renaming a skill requires a new engine config version, regenerated offline trees, and a coordinated update with each state's `aml-api-service`.

### Addition (11 skills)

| Sequence | Skill name |
|---|---|
| 1 | 1D+1D sum upto 9 |
| 2 | 1D+1D sum upto 20 |
| 3 | 2D+1D sum up to 20 |
| 4 | 2-digit Addition without carry |
| 5 | 2-digit Addition with carry |
| 6 | 3-digit Addition without carry |
| 7 | 3-digit Addition with carry |
| 8 | 4-digit Addition without carry |
| 9 | 4-digit Addition with carry |
| 10 | 5-digit Addition without carry |
| 11 | 5-digit Addition with carry |

### Subtraction (10 skills)

| Sequence | Skill name |
|---|---|
| 1 | 1D - 0 to 9 |
| 2 | 10 to 19 - 1D |
| 3 | 2-digit Subtraction without borrowing |
| 4 | 2-digit Subtraction with borrowing |
| 5 | 3-digit Subtraction without borrowing |
| 6 | 3-digit Subtraction with borrowing |
| 7 | 4-digit Subtraction without borrowing |
| 8 | 4-digit Subtraction with borrowing |
| 9 | 5-digit Subtraction without borrowing |
| 10 | 5-digit Subtraction with borrowing |

### Multiplication (10 skills)

| Sequence | Skill name |
|---|---|
| 1 | Repeated addition |
| 2 | Tables 1, 2 and 5 |
| 3 | Tables 1 to 9 |
| 4 | 2D x 1D |
| 5 | 2D x 2D |
| 6 | 3D x 1D |
| 7 | 3D x 2D |
| 8 | 4D/5D x 1D |
| 9 | 4D x 2D |
| 10 | 3D x 3D |

### Division (8 skills)

| Sequence | Skill name |
|---|---|
| 1 | Division using Distribution |
| 2 | Relationship between Multiplication and Division |
| 3 | 1D/2D by 1D without remainder |
| 4 | 3D by 1D without remainder |
| 5 | 1D/2D/3D by 1D with remainder |
| 6 | 4D by 1D with and without remainder |
| 7 | 5D by 1D with and without remainder |
| 8 | 2D/3D/4D/5D by 2D with and without remainder |

---

### Non-Delhi skill (1)

This skill is in the engine's canonical list but is served only in non-Delhi tenants; the Delhi scope remains 39.

| Sequence | Skill name | Operation | Served in |
|---|---|---|---|
| 40 | 1D - 1 to 4 | Subtraction | Karnataka, Private, Telangana (not Delhi) |

## Appendix D - Misconception code catalogue

The full 139-code set used by the misconception classifier, read from the four shipped modules (Addition `addition_v17.py`, Subtraction `subtraction_v29.py`, Multiplication `multiplication_v20.py`, Division `division_v47.py`). Each module works through its codes in a fixed order and returns the first that matches; the final code in each operation is an unclassified catch-all. The `Pattern (source label)` column is the module's own constant, the authoritative meaning; the `Plain reading` column is a readable rendering of it.

### Addition (26 codes)

| Code | Pattern (source label) | Plain reading |
|---|---|---|
| A01 | `RANDOM_OR_INVALID` | Random or invalid |
| A02 | `INPUT_ORDERING_ERROR` | Input ordering error |
| A03 | `WRONG_OP_SUBTRACTION` | Used wrong operation: subtraction |
| A04 | `WRONG_OP_MULTIPLICATION` | Used wrong operation: multiplication |
| A05 | `WRONG_OP_DIVISION` | Used wrong operation: division |
| A06 | `CONCAT_FORWARD` | Concat forward |
| A07 | `CONCAT_REVERSE` | Concat reverse |
| A08 | `PARTIAL_OPERAND_COPY` | Partial operand copy |
| A09 | `UNITS_ONLY_ADDITION` | Units only addition |
| A10 | `DIGIT_SUM_STRATEGY` | Digit sum strategy |
| A11 | `PARTIAL_DIGIT_SUM` | Partial digit sum |
| A12 | `PLACE_VALUE_ERROR` | Place value error |
| A13 | `CARRY_APPENDED` | Carry appended |
| A14 | `CARRY_APPENDED_REVERSED` | Carry appended reversed |
| A15 | `INCOMPLETE_ANSWER_WIDTH` | Incomplete answer width |
| A16 | `CARRY_IGNORED` | Carry ignored |
| A17 | `CARRY_FLOWS_RIGHT` | Carry flows right |
| A18 | `CARRY_ADDED_NO_NEED` | Carry added no need |
| A19 | `CARRY_DOUBLED` | Carry doubled |
| A20 | `CARRY_RESULT_SWAP` | Carry result swap |
| A21 | `ZERO_RULE_ERROR` | Zero rule error |
| A22 | `DOUBLE_RULE_ERROR` | Double rule error |
| A23 | `SINGLE_COLUMN_SLIP` | Single column slip |
| A24 | `MULTI_COLUMN_SLIP` | Multi column slip |
| A25 | `INCOMPLETE_ENTRY` | Incomplete entry |
| A26 | `UNCLASSIFIED_ERROR` | Unclassified error |

### Subtraction (31 codes)

| Code | Pattern (source label) | Plain reading |
|---|---|---|
| S01 | `RANDOM_OR_INVALID` | Random or invalid |
| S02 | `INPUT_ORDERING_ERROR` | Input ordering error |
| S03 | `CONCAT_FORWARD` | Concat forward |
| S04 | `CONCAT_REVERSE` | Concat reverse |
| S05 | `N1_OR_N2_COPIED_AS_ANSWER` | First operand or second operand copied as answer |
| S06 | `WRONG_OPERATION_ADDITION` | Used wrong operation: addition |
| S07 | `WRONG_OPERATION_MULTIPLICATION` | Used wrong operation: multiplication |
| S08 | `WRONG_OPERATION_DIVISION` | Used wrong operation: division |
| S09 | `UNITS_ONLY_SUBTRACTION` | Units only subtraction |
| S10 | `N1_UNITS_DIGIT_AS_TENS` | First operand units digit as tens |
| S11 | `DOUBLE_SUBTRACTION` | Double subtraction |
| S12 | `PLACE_VALUE_POSITIONING` | Place value positioning |
| S13 | `OPERAND_DIGIT_REVERSAL` | Operand digit reversal |
| S14 | `LEADING_DIGIT_DROPPED` | Leading digit dropped |
| S15 | `UNITS_DIGIT_DROPPED` | Units digit dropped |
| S16 | `BORROW_FORGOTTEN_BIGGER_MINUS_SMALLER` | Borrow forgotten bigger minus smaller |
| S17 | `BORROW_NON_ZERO_SMALLER_TOP_COPIES_N2_DIGIT` | Borrow non zero smaller top copies second operand digit |
| S18 | `BORROW_NO_REDUCE` | Borrow no reduce |
| S19 | `BORROW_ADDS_10_TO_BOTH_COLUMNS` | Borrow adds 10 to both columns |
| S20 | `BORROW_WRITES_ZERO` | Borrow writes zero |
| S21 | `BORROW_SKIPS_INTERIOR_ZERO` | Borrow skips interior zero |
| S22 | `BORROW_INDUCED_ZERO_OMITTED` | Borrow induced zero omitted |
| S23 | `BORROW_ZERO_TOP_COPIES_N2_DIGIT` | Borrow zero top copies second operand digit |
| S24 | `BORROW_ZERO_TOP_NO_REDUCE` | Borrow zero top no reduce |
| S25 | `BORROW_N2_DIGIT_IGNORED` | Borrow second operand digit ignored |
| S26 | `X_MINUS_ZERO_IDENTITY_FAILURE` | X minus zero identity failure |
| S27 | `X_MINUS_X_EQUALS_X` | X minus x equals x |
| S28 | `CORRECT_ANSWER_DIGITS_SUBTRACTED` | Correct answer digits subtracted |
| S29 | `SINGLE_COLUMN_SLIP` | Single column slip |
| S30 | `MULTI_COLUMN_SLIP` | Multi column slip |
| S31 | `UNCLASSIFIED_ERROR` | Unclassified error |

### Multiplication (46 codes)

| Code | Pattern (source label) | Plain reading |
|---|---|---|
| M01 | `RANDOM_OR_INVALID` | Random or invalid |
| M02 | `ZERO_ANSWER` | Zero answer |
| M03 | `ZERO_PROPERTY_ERROR` | Zero property error |
| M04 | `WRONG_OP_ADDITION` | Used wrong operation: addition |
| M05 | `WRONG_OP_SUBTRACTION` | Used wrong operation: subtraction |
| M06 | `WRONG_OP_DIVISION` | Used wrong operation: division |
| M07 | `PARTIAL_OPERAND_COPY` | Partial operand copy |
| M08 | `DIGIT_CONCAT_RTL` | Digit concat right to left |
| M09 | `DIGIT_CONCAT_LTR` | Digit concat left to right |
| M10 | `CARRY_IGNORED` | Carry ignored |
| M11 | `CARRY_ADD_BEFORE_MUL` | Carry add before multiply |
| M12 | `TENS_NOT_MULTIPLIED` | Tens not multiplied |
| M13 | `CARRY_ADD_TO_MULTIPLIER` | Carry add to multiplier |
| M14 | `STEP_OP_ADDITION` | Step op addition |
| M15 | `STEP_WRONG_MULTIPLIER` | Step wrong multiplier |
| M16 | `STEP_CARRY_ADD_ERROR` | Step carry add error |
| M17 | `SHIFT_INDENTATION` | Shift indentation |
| M18 | `CARRYING_SHIFT` | Carrying shift |
| M19 | `CARRY_WRITE_SWAP` | Carry write swap |
| M20 | `CARRY_PROPAGATION_CONFUSION` | Carry propagation confusion |
| M21 | `SAME_DIGIT_IDENTITY` | Same digit identity |
| M22 | `LTR_DIRECTION` | Left to right direction |
| M23 | `LTR_SHIFT` | Left to right shift |
| M24 | `LTR_CARRYING_SHIFT` | Left to right carrying shift |
| M25 | `TRAILING_ZERO_PREFIX1` | Trailing zero prefix 1 |
| M26 | `TENS_ROW_TENS_DIGIT_ONLY` | Tens row tens digit only |
| M27 | `COLUMN_WISE_MUL` | Column wise multiply |
| M28 | `TENS_STEP_ADDITION` | Tens step addition |
| M29 | `MUL_LEADING_ADD_TRAILING` | Multiply leading add trailing |
| M30 | `TRUNCATED_ANSWER` | Truncated answer |
| M31 | `OPERAND_CONCATENATION` | Operand concatenation |
| M32 | `REVERSED_N1` | Reversed first operand |
| M33 | `ROW_CONCAT_DIGIT_MUL` | Row concat digit multiply |
| M34 | `LEAD_X_UNITS_APPEND_UNITS` | Lead x units append units |
| M35 | `ROW1_CARRY_DROPPED` | Row 1 carry dropped |
| M36 | `PARTIAL_PRODUCT` | Partial product |
| M37 | `DIGIT_SUM_SUBSTITUTION` | Digit sum substitution |
| M38 | `ALL_DIGIT_SUM` | All digit sum |
| M39 | `PLACE_VALUE_ERROR` | Place value error |
| M40 | `WRONG_MULTIPLIER` | Wrong multiplier |
| M41 | `DIGIT_REVERSAL_ANSWER` | Digit reversal answer |
| M42 | `FINAL_CARRY_REPLACED_BY_N2` | Final carry replaced by second operand |
| M43 | `DIGIT_ASSEMBLY_ORDER` | Digit assembly order |
| M44 | `NEAR_MISS` | Near miss |
| M45 | `ROW_RESULT_CONCAT` | Row result concat |
| M46 | `UNCLASSIFIED_ERROR` | Unclassified error |

### Division (36 codes)

| Code | Pattern (source label) | Plain reading |
|---|---|---|
| D01 | `RANDOM_OR_INVALID` | Random or invalid |
| D02 | `Q_DIGITS_REORDERED` | Quotient digits reordered |
| D03 | `WRONG_OP_MULTIPLY` | Used wrong operation: multiply |
| D04 | `WRONG_OP_ADD` | Used wrong operation: add |
| D05 | `WRONG_OP_SUB` | Used wrong operation: sub |
| D06 | `ZERO_ANSWER` | Zero answer |
| D07 | `CORRECT_QUOTIENT_IN_REMAINDER_SLOT` | Correct quotient in remainder slot |
| D08 | `ANSWER_EQ_DIVIDEND` | Answer equals dividend |
| D09 | `ANSWER_EQ_DIVISOR` | Answer equals divisor |
| D10 | `PROBLEM_COPIED_IN_QR_FORMAT` | Problem copied in quotient/remainder format |
| D11 | `Q_RIGHT_R_ZERO` | Quotient right remainder zero |
| D12 | `Q_RIGHT_R_EQUALS_DIVISOR` | Quotient right remainder equals divisor |
| D13 | `Q_RIGHT_R_COPIED_AS_Q` | Quotient right remainder copied as quotient |
| D14 | `Q_RIGHT_R_DOUBLED` | Quotient right remainder doubled |
| D15 | `Q_RIGHT_R_WRONG_OTHER` | Quotient right remainder wrong other |
| D16 | `R_RIGHT_Q_ZERO` | Remainder right quotient zero |
| D17 | `R_RIGHT_Q_OFF_BY_ONE` | Remainder right quotient off by one |
| D18 | `Q_EXTRA_TRAILING_ZEROS` | Quotient extra trailing zeros |
| D19 | `NO_DIGIT_BY_DIGIT_DIVISION` | No digit by digit division |
| D20 | `Q_MISSING_ZERO_DIVIDEND_ENDS_IN_ZERO` | Quotient missing zero dividend ends in zero |
| D21 | `Q_MISSING_ZERO_DIVIDEND_HAS_INTERNAL_ZERO` | Quotient missing zero dividend has internal zero |
| D22 | `Q_MISSING_TRAILING_ZERO_DIVIDEND_NO_ZERO` | Quotient missing trailing zero dividend no zero |
| D23 | `Q_MISSING_INTERNAL_ZERO_DIVIDEND_NO_ZERO` | Quotient missing internal zero dividend no zero |
| D24 | `Q_EXTRA_INTERNAL_ZERO_DIVIDEND_HAS_ZERO` | Quotient extra internal zero dividend has zero |
| D25 | `Q_EXTRA_INTERNAL_ZERO_DIVIDEND_NO_ZERO` | Quotient extra internal zero dividend no zero |
| D26 | `INCOMPLETE_DIVISION` | Incomplete division |
| D27 | `QR_RIGHT_INTERCHANGED` | Quotient/remainder right interchanged |
| D28 | `UNDER_DIVISION` | Under division |
| D29 | `STEP_REMAINDER_IGNORED` | Step remainder ignored |
| D30 | `SINGLE_STEP_TABLE_SLIP` | Single step table slip |
| D31 | `FIRST_DIGIT_QUOTIENT` | First digit quotient |
| D32 | `LAST_DIGIT_QUOTIENT` | Last digit quotient |
| D33 | `CONCAT_OPERANDS` | Concat operands |
| D34 | `Q_OFF_BY_ONE` | Quotient off by one |
| D35 | `QUOTIENT_NEAR_MISS` | Quotient near miss |
| D36 | `UNCLASSIFIED_NEAR_RANDOM` | Unclassified near random |

---

## Appendix E - Sample misconception classifier input and output

Illustrative values with the real field names (the structure is what `aml_stageb.build_learning_state` consumes and returns). The input is three payloads the engine glue assembles after a session is finalized: the per-question `responses`, the per-skill `mastery` verdicts, and run `meta`. The output is the merged learning state stored on the learner, one entry per in-scope skill, carrying both the mastery verdict and any misconception codes. Only `Fib` (fill-in-the-blank) questions are classified; Mcq and Number-Sense items pass through and are skipped by the classifier.

**Input**

```json
{
  "responses": {
    "learner_id": "DL-2025-08831",
    "learner_grade": 3,
    "items": [
      { "question_id": "q_ADD_2dc_000742_b", "skill_id": "2-digit Addition with carry",
        "operation": "Addition", "n1": 45, "n2": 27, "response": "62", "q_type": "Fib" }
      // a Division item would additionally carry  "response_includes_remainder": false
    ]
  },
  "mastery": {
    "learner_id": "DL-2025-08831",
    "learner_grade": 3,
    "skills": {
      "2-digit Addition with carry": { "verdict": "confident_not_mastered", "posterior": 0.11 }
    }
  },
  "meta": {
    "tenant": "Delhi",
    "engine_version": "0.10.0",
    "calibration_version": "667-item-2026-06",
    "diagnostic_session": { "session_id": "sess-4471", "mode": "online", "completed_utc": "2026-06-30T07:30:00Z" }
  }
}
```

**Output** (one skill shown; a real file lists every in-scope skill)

```json
{
  "schema_version": "1.0",
  "learner_id": "DL-2025-08831",
  "learner_grade": 3,
  "tenant": "Delhi",
  "generated_utc": "2026-06-30T07:31:02Z",
  "diagnostic_session": { "session_id": "sess-4471", "mode": "online", "completed_utc": "2026-06-30T07:30:00Z" },
  "provenance": {
    "engine_version": "0.10.0",
    "calibration_version": "667-item-2026-06",
    "eligibility_table_version": "2026-06-01",
    "classifier_modules": { "Addition": "v17", "Subtraction": "v29", "Multiplication": "v20", "Division": "v47" },
    "low_support_k": 2
  },
  "skills": [
    {
      "skill_id": "2-digit Addition with carry",
      "operation": "Addition",
      "mastery": { "verdict": "confident_not_mastered", "posterior": 0.11 },
      "misconceptions": {
        "status": "classified",
        "n_questions_classified": 3,
        "accuracy": 0.0,
        "n_invalid": 0,
        "ranked": [
          { "code": "A16", "name": "CARRY_IGNORED", "misconception_evidence_index": 0.83,
            "n_fired": 2, "n_eligible": 3, "mean_score_when_fired": 1.0, "low_support": false }
        ]
      }
    }
  ],
  "operation_rollup": { "Addition": { "n_classified": 3, "accuracy": 0.0, "invalid_rate": 0.0 } },
  "errors": []
}
```

The `ranked` list is ordered by `misconception_evidence_index` (the share of eligible probes on which the pattern fired); here the learner's answer of 62 to 45 + 27 fired **A16** (`CARRY_IGNORED`), the dropped-carry pattern. `low_support` flags a code seen on too few eligible questions to be reliable.

**A note on `question_id` vs `question_x_id`.** The engine's API wire fields and the offline trees use `question_x_id` (the request/response schema fields were renamed from `question_id` to `question_x_id` so the wire name matches the value it carries). The engine's own internal session-history attribute is still named `question_id` and holds that same `question_x_id` value. Two other things are also named `question_id` and are not necessarily the same value: AML's `learner_proficiency_question_level_data.question_id` (the key the offline history scorer joins on, §7.10) and the Stage B classifier's own item `question_id`. Whether AML's `question_id` equals `question_x_id` is the join the offline scorer depends on and must be confirmed against the AML schema during integration; it cannot be settled from the engine repo alone.

---

*End of Engineering Specification - v10 document set (engine 0.10.0)*
