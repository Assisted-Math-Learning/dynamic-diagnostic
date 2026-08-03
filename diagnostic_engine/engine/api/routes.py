"""
Route handlers for the 6 API endpoints from spec section 5.

  POST /api/v1/diagnostic/session/start
  POST /api/v1/diagnostic/session/:sub_session_id/response
  POST /api/v1/diagnostic/session/:sub_session_id/end
  GET  /api/v1/diagnostic/session/:sub_session_id/verdicts
  GET  /health
  GET  /metrics

Each handler:
  1. Verifies the tenant token.
  2. Loads or constructs the relevant session state.
  3. Calls into the engine core (session.* functions).
  4. Persists state changes.
  5. Returns an envelope-wrapped response.

Errors are raised as EngineApiError subclasses; the global exception handler
in main.py translates them into envelope-wrapped 4xx/5xx responses.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Path, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from engine.api.auth import TOKEN_HEADER, verify_tenant_token
from engine.api.envelope import success_envelope
from engine.api.errors import (
    InvalidGradeError,
    InvalidSkillIdError,
    LearnerMismatchError,
    NoTreeForGradeError,
    ResponseConflictError,
    SessionAlreadyEndedError,
    SessionAlreadyExistsError,
    SessionNotCompleteError,
    SessionNotFoundError,
    VerdictsNotWrittenError,
)
from engine.api.schemas import (
    HealthResult,
    MisconceptionSignalPayload,
    QuestionRef,
    RawResponseItem,
    SessionEndRequest,
    SessionEndResult,
    SessionRawResponsesResult,
    SessionResponseRequest,
    SessionResponseResult,
    SessionStartRequest,
    SessionStartResult,
    VerdictPayload,
    VerdictsResult,
)
from engine.routing import QuestionChoice
from engine.misconception import derive_misconception_signals
from engine.session import (
    EndReason,
    RoutingMode,
    Session,
    SessionConflictError,
    SessionStateError,
    SessionStatus,
    SkillVerdict,
    UnknownSkillError,
    end_session,
    finalize_session,
    record_response,
    start_session,
)
from engine.coverage import select_next_coverage
from engine.observability.logging import get_logger

router = APIRouter(prefix="/api/v1/diagnostic")


# Endpoint IDs (for the envelope's `id` field) ------------------------------

ID_SESSION_START = "api.diagnostic.session.start"
ID_SESSION_RESPONSE = "api.diagnostic.session.response"
ID_SESSION_END = "api.diagnostic.session.end"
ID_VERDICTS = "api.diagnostic.session.verdicts"
ID_OFFLINE_TREE = "api.diagnostic.offline_tree"
ID_SESSION_RESPONSES = "api.diagnostic.session.responses"


# Helpers ---------------------------------------------------------------------


def _app_state(request: Request) -> Any:
    """Shorthand for request.app.state."""
    return request.app.state


def _header_token(request: Request) -> Optional[str]:
    return request.headers.get(TOKEN_HEADER)


def _build_engine_params(request: Request, grade: int):
    """Construct EngineParams for the given grade via the loaded config.

    Translates a ValueError from config.get_engine_params (out-of-range grade
    or unconfigured native grade) into an InvalidGradeError.
    """
    state = _app_state(request)
    try:
        return state.config.get_engine_params(grade, state.lattice_index)
    except ValueError as e:
        raise InvalidGradeError(str(e))


def _stash_resolved(session: Session, skill_id: str, pick) -> QuestionRef:
    """Stash an already-resolved QuestionPick on the session's pending_* fields.

    Used by both _pick_question_and_stash (legacy / session start) and the
    coverage controller path (which resolves the pick itself). The caller must
    save_session() afterwards to persist the pending state.
    """
    session.pending_question_id = pick.question_id
    session.pending_question_slip_override = pick.slip_override
    session.pending_question_guess_override = pick.guess_override
    session.pending_question_skill_id = skill_id
    session.pending_question_misconceptions = pick.misconceptions
    return QuestionRef(question_x_id=pick.question_id, skill_id=skill_id)


def _pick_question_and_stash(
    choice: QuestionChoice,
    session: Session,
    question_pool,
    *,
    grade: int,
    tenant_id: str,
) -> QuestionRef:
    """Resolve a chosen skill to a concrete question and stash per-item overrides on the session.

    Calls the pool's `pick_question_for_skill` with the spec section 7.8
    signature. Side-effect: writes the QuestionPick's question_id and
    optional slip / guess overrides to session.pending_question_* fields
    so that the next /response can apply them in the Bayes update (spec
    section 7.7). The caller must save_session() after this call to
    persist the pending state.
    """
    pick = question_pool.pick_question_for_skill(
        skill=choice.skill,
        session=session,
        grade=grade,
        tenant_id=tenant_id,
    )
    return _stash_resolved(session, choice.skill, pick)


def _verdict_to_payload(v: SkillVerdict) -> VerdictPayload:
    return VerdictPayload(
        skill_id=v.skill_id,
        operation=v.operation,
        posterior=v.posterior,
        direct_observations=v.direct_observations,
        propagation_updates=v.propagation_updates,
        confidence_label=v.confidence_label,
        recommendation=v.recommendation,
    )


def _build_misconception_signals(session, question_pool, mc_cfg=None) -> List[MisconceptionSignalPayload]:
    """Derive the per-misconception triage signal payloads for a finished session.

    `mc_cfg` is the engine-wide misconception config block (target + the two
    accuracy thresholds). When absent (defensive), the target falls back to the
    pool's and the thresholds to the module constants. Applicability (set at
    session start from the pool's tags) is what makes a misconception
    not_applicable - a pool with no tags yields an all-not_applicable signal
    regardless of target. Spec section 7.
    """
    if mc_cfg is not None:
        target = mc_cfg.target
        return [
            MisconceptionSignalPayload(
                misconception=s.misconception, state=s.state, asked=s.asked,
                correct=s.correct, wrong=s.wrong,
            )
            for s in derive_misconception_signals(
                session, misconception_target=target,
                clear_threshold=mc_cfg.clear_threshold,
                present_threshold=mc_cfg.present_threshold,
            )
        ]
    target = getattr(question_pool, "misconception_target", 0) or 0
    return [
        MisconceptionSignalPayload(
            misconception=s.misconception, state=s.state, asked=s.asked,
            correct=s.correct, wrong=s.wrong,
        )
        for s in derive_misconception_signals(session, misconception_target=target)
    ]


def _record_metrics_on_start(request: Request, tenant_id: str, grade: int) -> None:
    metrics = getattr(_app_state(request), "metrics", None)
    if metrics is not None:
        metrics.sessions_started_total.labels(tenant_id=tenant_id, grade=str(grade)).inc()


def _record_metrics_on_complete(
    request: Request, session: Session, end_reason: str,
) -> None:
    metrics = getattr(_app_state(request), "metrics", None)
    if metrics is None:
        return
    grade_label = str(session.grade)
    metrics.sessions_completed_total.labels(
        tenant_id=session.tenant_id, grade=grade_label, end_reason=end_reason,
    ).inc()
    if session.started_at and session.ended_at:
        duration = (session.ended_at - session.started_at).total_seconds()
        metrics.session_duration_seconds.labels(
            tenant_id=session.tenant_id, grade=grade_label,
        ).observe(duration)
    metrics.questions_per_session.labels(
        tenant_id=session.tenant_id, grade=grade_label,
    ).observe(session.questions_total)


def _record_metrics_on_verdicts(request: Request, session: Session, verdicts) -> None:
    metrics = getattr(_app_state(request), "metrics", None)
    if metrics is None:
        return
    for v in verdicts:
        metrics.verdict_total.labels(
            tenant_id=session.tenant_id,
            grade=str(session.grade),
            skill_id=v.skill_id,
            confidence_label=v.confidence_label.value,
        ).inc()


# === Endpoints ==============================================================


@router.post("/session/start")
def session_start(body: SessionStartRequest, request: Request):
    """Create a new session and return the first question + offline tree (spec section 5.3)."""
    state = _app_state(request)
    verify_tenant_token(
        header_token=_header_token(request),
        tenant_id=body.tenant_id,
        tenant_tokens=state.tenant_tokens,
    )

    if state.storage.session_exists(body.sub_session_id):
        raise SessionAlreadyExistsError(
            f"an engine session for sub_session_id '{body.sub_session_id}' already exists"
        )

    params = _build_engine_params(request, body.grade)

    result = start_session(
        sub_session_id=body.sub_session_id,
        learner_id=body.learner_id,
        tenant_id=body.tenant_id,
        class_id=body.class_id,
        grade=body.grade,
        engine_version=state.engine_version,
        params=params,
    )

    # Compute the applicable-misconception set once, now, from the pool, using
    # the exact runtime eligibility (spec section 3.4). Stored on the session
    # before saving so it persists for the rest of the session. Pools without a
    # per-tenant lookup return an empty set (the layer is inert in legacy mode).
    applicable_fn = getattr(state.question_pool, "applicable_misconceptions", None)
    if applicable_fn is not None:
        result.session.misconception_applicable = applicable_fn(
            body.tenant_id, body.grade, params.skills_in_scope
        )

    # Pick the first question and stash per-item overrides on the session
    # BEFORE saving, so the pending_* state is persisted alongside the rest
    # of the session document.
    first_q = (
        _pick_question_and_stash(
            result.first_question, result.session, state.question_pool,
            grade=body.grade, tenant_id=body.tenant_id,
        )
        if result.first_question is not None
        else None
    )

    state.storage.save_session(result.session)
    _record_metrics_on_start(request, body.tenant_id, body.grade)

    # B1: attach a REFERENCE (not the inlined ~30 MB tree) to the offline
    # decision tree for this (tenant, resolved-grade), when one is shipped and
    # its engine_version matches the running engine. Missing tree, an
    # unsupported grade, a non-Delhi tenant, or version drift -> null. Offline
    # is a fallback: a Delhi-only rollout must never break another tenant's
    # online session, so this path never raises NO_TREE_FOR_GRADE.
    registry = getattr(state, "offline_tree_registry", None)
    offline_tree_ref = None
    if registry is not None:
        offline_tree_ref = registry.reference(
            body.tenant_id,
            body.grade,
            state.engine_version,
            fetch_path=lambda t, g: f"{router.prefix}/offline-tree/{t}/{g}",
            warn=lambda t, g, av, rv: get_logger(__name__).warning(
                f"offline_tree version drift for tenant={t} grade=g{g}: "
                f"artifact {av} != engine {rv}; serving null offline_tree"
            ),
        )

    payload = SessionStartResult(
        sub_session_id=body.sub_session_id,
        first_question=first_q,
        offline_tree=offline_tree_ref,
        question_budget=params.routing_config.total_budget,
    )
    return success_envelope(ID_SESSION_START, payload.model_dump())


@router.post("/session/{sub_session_id}/response")
def session_response(
    body: SessionResponseRequest,
    request: Request,
    sub_session_id: str = Path(..., min_length=1),
):
    """Record a response, return next question or session-complete verdicts (spec section 5.4)."""
    state = _app_state(request)
    verify_tenant_token(
        header_token=_header_token(request),
        tenant_id=body.tenant_id,
        tenant_tokens=state.tenant_tokens,
    )

    session = state.storage.get_session(sub_session_id)
    if session is None:
        raise SessionNotFoundError(f"no engine session for sub_session_id '{sub_session_id}'")
    if session.status != SessionStatus.ACTIVE:
        raise SessionAlreadyEndedError(
            f"session is {session.status.value}; submit a new session/start for a new session"
        )
    if session.learner_id != body.learner_id:
        raise LearnerMismatchError(
            f"learner_id '{body.learner_id}' does not match session's learner '{session.learner_id}'"
        )

    params = _build_engine_params(request, session.grade)

    # Per-item slip / guess overrides for the question we just received,
    # if the engine handed them out on the previous turn. The override is
    # only honored when the question_id matches the one we stashed -
    # otherwise (replay of an old question, mismatched client, etc.) we
    # fall back to the config defaults, matching the "calibrated-if-
    # available, defaults otherwise" semantics from spec section 7.7.
    slip_override: Optional[float] = None
    guess_override: Optional[float] = None
    if session.pending_question_id == body.question_x_id:
        slip_override = session.pending_question_slip_override
        guess_override = session.pending_question_guess_override

    try:
        rr = record_response(
            session,
            skill_id=body.skill_id,
            question_id=body.question_x_id,
            is_correct=body.is_correct,
            params=params,
            routing_mode=RoutingMode.ONLINE,
            slip_override=slip_override,
            guess_override=guess_override,
            defer_next=True,
            raw_response=body.raw_response,
        )
    except UnknownSkillError as e:
        raise InvalidSkillIdError(str(e))
    except SessionConflictError as e:
        metrics = getattr(state, "metrics", None)
        if metrics is not None:
            metrics.response_conflicts_total.labels(tenant_id=body.tenant_id).inc()
        raise ResponseConflictError(str(e))
    except SessionStateError as e:
        # Shouldn't happen given our pre-check above, but defensive.
        raise SessionAlreadyEndedError(str(e))

    metrics = getattr(state, "metrics", None)
    if metrics is not None:
        metrics.routing_mode_questions_total.labels(
            tenant_id=body.tenant_id, mode=RoutingMode.ONLINE.value,
        ).inc()

    if rr.is_idempotent_replay:
        # Replay of an already-recorded answer: the controller is NOT re-run
        # (state is unchanged); re-serve the question already stashed on the
        # previous turn so the response is idempotent. No save (no mutation).
        if session.pending_question_id is not None:
            next_q = QuestionRef(
                question_x_id=session.pending_question_id,
                skill_id=session.pending_question_skill_id,
            )
            payload = SessionResponseResult(
                session_complete=False,
                next_question=next_q,
                questions_asked_so_far=session.questions_total,
                questions_remaining_budget=(
                    params.routing_config.total_budget - session.questions_total
                ),
                verdicts=None,
            )
            return success_envelope(ID_SESSION_RESPONSE, payload.model_dump())
        # No pending question on an active session is not expected; fall through
        # to the controller, which will finalize if there is nothing to ask.

    next_res = select_next_coverage(session, params, state.question_pool)

    if next_res is not None:
        # The controller already resolved the pick (Phase 1/3 routing or Phase 2
        # backfill); stash it directly - do NOT re-pick - before save_session.
        skill_id, pick = next_res
        next_q = _stash_resolved(session, skill_id, pick)
        state.storage.save_session(session)
        payload = SessionResponseResult(
            session_complete=False,
            next_question=next_q,
            questions_asked_so_far=session.questions_total,
            questions_remaining_budget=(
                params.routing_config.total_budget - session.questions_total
            ),
            verdicts=None,
        )
    else:
        # Controller signalled completion: finalize (verdicts + status/ended_at).
        # record_response(defer_next=True) already cleared the pending_* fields.
        verdicts = finalize_session(session, params)
        state.storage.save_session(session)
        state.storage.save_verdicts(session, verdicts or [])
        _record_metrics_on_complete(request, session, end_reason="natural")
        _record_metrics_on_verdicts(request, session, verdicts or [])
        payload = SessionResponseResult(
            session_complete=True,
            next_question=None,
            questions_asked_so_far=session.questions_total,
            questions_remaining_budget=(
                params.routing_config.total_budget - session.questions_total
            ),
            verdicts=[_verdict_to_payload(v) for v in (verdicts or [])],
            misconception_signals=_build_misconception_signals(
                session, state.question_pool, state.config.misconception
            ),
        )

    return success_envelope(ID_SESSION_RESPONSE, payload.model_dump())


@router.post("/session/{sub_session_id}/end")
def session_end(
    body: SessionEndRequest,
    request: Request,
    sub_session_id: str = Path(..., min_length=1),
):
    """Mark a session ended explicitly and return verdicts (spec section 5.5)."""
    state = _app_state(request)
    verify_tenant_token(
        header_token=_header_token(request),
        tenant_id=body.tenant_id,
        tenant_tokens=state.tenant_tokens,
    )

    session = state.storage.get_session(sub_session_id)
    if session is None:
        raise SessionNotFoundError(f"no engine session for sub_session_id '{sub_session_id}'")
    if session.status != SessionStatus.ACTIVE:
        raise SessionAlreadyEndedError(f"session is already {session.status.value}")
    if session.learner_id != body.learner_id:
        raise LearnerMismatchError(
            f"learner_id '{body.learner_id}' does not match session's learner '{session.learner_id}'"
        )

    params = _build_engine_params(request, session.grade)

    reason_str = body.reason or "abandoned"
    reason_enum = {
        "abandoned": EndReason.ABANDONED,
        "timeout": EndReason.TIMEOUT,
        "learner_quit": EndReason.LEARNER_QUIT,
    }[reason_str]

    er = end_session(session, reason=reason_enum, params=params)
    state.storage.save_session(session)
    state.storage.save_verdicts(session, er.verdicts)

    _record_metrics_on_complete(request, session, end_reason=reason_str)
    _record_metrics_on_verdicts(request, session, er.verdicts)

    payload = SessionEndResult(
        verdicts=[_verdict_to_payload(v) for v in er.verdicts],
        misconception_signals=_build_misconception_signals(session, state.question_pool, state.config.misconception),
    )
    return success_envelope(ID_SESSION_END, payload.model_dump())


@router.get("/session/{sub_session_id}/verdicts")
def get_verdicts(
    request: Request,
    sub_session_id: str = Path(..., min_length=1),
):
    """Re-fetch the verdicts for a completed session (spec section 5.6).

    Note: this endpoint has no request body, so no tenant_id is available to
    check the shared-secret token. We still require the header to be present,
    and accept it if it matches ANY registered token. This is a weaker guard
    than the body-bearing endpoints but matches the spec's no-body design.
    """
    state = _app_state(request)
    header_token = _header_token(request)
    if not header_token or header_token not in set(state.tenant_tokens.values()):
        from engine.api.errors import InvalidTenantTokenError
        raise InvalidTenantTokenError("invalid X-Internal-Service-Token")

    session = state.storage.get_session(sub_session_id)
    if session is None:
        raise SessionNotFoundError(f"no engine session for sub_session_id '{sub_session_id}'")
    if session.status == SessionStatus.ACTIVE:
        raise SessionNotCompleteError("session is still active; verdicts are not final")

    verdicts = state.storage.get_verdicts(sub_session_id)
    if not verdicts:
        raise VerdictsNotWrittenError(
            "session is complete but verdicts have not been written yet; "
            "the cleanup job recovers these every 5 minutes"
        )

    payload = VerdictsResult(
        verdicts=[_verdict_to_payload(v) for v in verdicts],
        misconception_signals=_build_misconception_signals(session, state.question_pool, state.config.misconception),
    )
    return success_envelope(ID_VERDICTS, payload.model_dump())


@router.get("/offline-tree/{tenant_id}/{grade}")
def get_offline_tree(
    request: Request,
    tenant_id: str = Path(..., min_length=1),
    grade: int = Path(..., ge=0, le=99),
):
    """Serve the precomputed offline decision tree for (tenant, grade) as JSON
    (B1). The grade is resolved with the online engine's fallback (G5-G8 -> G5).
    Returns 404 NO_TREE_FOR_GRADE when no tree is servable for the resolved
    grade (below G2, or a tenant with no shipped trees) or on engine-version
    drift (a stale tree is never served). Same X-Internal-Service-Token model;
    the tenant is in the path so the token is checked against it directly.
    The precomputed artifact is served as-is - no tree is recomputed per
    request. The response body is the canonical JSON whose size and sha256 the
    session/start reference advertises."""
    state = _app_state(request)
    verify_tenant_token(
        header_token=_header_token(request),
        tenant_id=tenant_id,
        tenant_tokens=state.tenant_tokens,
    )
    registry = getattr(state, "offline_tree_registry", None)
    body = (
        registry.tree_bytes(tenant_id, grade, state.engine_version)
        if registry is not None
        else None
    )
    if body is None:
        raise NoTreeForGradeError(
            f"no offline tree for tenant '{tenant_id}' grade {grade}"
        )
    return Response(content=body, media_type="application/json")


@router.get("/session/{sub_session_id}/responses")
def get_session_responses(
    request: Request,
    sub_session_id: str = Path(..., min_length=1),
):
    """Return a session's stored raw learner responses, keyed for Stage B
    (spec section 8.4). raw_response is null per item unless the caller sent it
    on that response. No request body, so the tenant is resolved from the
    session and the X-Internal-Service-Token header is verified against it."""
    state = _app_state(request)
    header_token = _header_token(request)
    if not header_token or header_token not in set(state.tenant_tokens.values()):
        from engine.api.errors import InvalidTenantTokenError

        raise InvalidTenantTokenError("invalid X-Internal-Service-Token")

    session = state.storage.get_session(sub_session_id)
    if session is None:
        raise SessionNotFoundError(
            f"no engine session for sub_session_id '{sub_session_id}'"
        )
    # Strong per-tenant check now that the session's tenant is known.
    verify_tenant_token(
        header_token=header_token,
        tenant_id=session.tenant_id,
        tenant_tokens=state.tenant_tokens,
    )

    responses = [
        RawResponseItem(
            question_x_id=e.question_id,
            raw_response=e.raw_response,
            is_correct=e.is_correct,
            skill_id=e.skill_id,
        )
        for e in session.question_history
    ]
    payload = SessionRawResponsesResult(
        sub_session_id=sub_session_id,
        learner_id=session.learner_id,
        grade=session.grade,
        responses=responses,
    )
    return success_envelope(ID_SESSION_RESPONSES, payload.model_dump())


# === Health and metrics =====================================================


# A second router with no prefix for the bare /health and /metrics paths.
flat_router = APIRouter()


@flat_router.get("/health", include_in_schema=False)
def health(request: Request):
    """Health check used by Kubernetes readiness and liveness probes (spec section 5.8).

    Mounted on the bare path (`/health`) only, not under the API prefix.
    The API prefix is for tenant-facing endpoints; health probes are
    operational concerns and should not require knowing the API version.
    """
    state = _app_state(request)
    storage_ok = state.storage.health_check()
    config_loaded = state.config is not None
    status = "ok" if (storage_ok and config_loaded) else "degraded"
    payload = HealthResult(
        status=status,
        version=state.engine_version,
        storage="connected" if storage_ok else "down",
        engine_config_loaded=config_loaded,
        tree_versions={},  # offline trees are out of scope for v1
        priors_missing_for_grades=getattr(state, "priors_missing_for_grades", []),
    )
    # /health returns a flat JSON object (no envelope), matching what most
    # Kubernetes probes expect to read.
    return payload.model_dump()


@flat_router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """Prometheus scrape endpoint (spec section 5.7 / 9.1)."""
    state = _app_state(request)
    registry = getattr(state, "prometheus_registry", None)
    data = generate_latest(registry) if registry is not None else generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
