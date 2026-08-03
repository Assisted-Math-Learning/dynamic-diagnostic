"""
Session orchestration for the dynamic diagnostic engine.

This module ties bayes, lattice, routing, and verdicts together. It is the
only place in the engine where state mutates. The other engine modules are
pure functions; session holds and updates the session document.

Public API:

  Data types
    SessionStatus, EndReason, RoutingMode   - lifecycle enums
    QuestionHistoryEntry                    - one entry in question_history
    SkillVerdict                            - verdict with skill_id attached
    Session                                 - mirrors the learner_diagnostic_sessions doc
    EngineParams                            - bundle of per-session engine parameters
    StartResult, ResponseResult, EndResult  - return types

  Lifecycle functions
    start_session(...)        - create a new session, pick the first question
    record_response(...)      - apply a scored response, return next question or verdicts
    end_session(...)          - early termination, return verdicts
    compute_verdicts(...)     - pure read of current verdicts

  Exceptions
    SessionStateError, UnknownSkillError, SessionConflictError
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set

from engine.bayes import update_posterior
from engine.lattice import LatticeIndex, propagate
from engine.misconception import MISCONCEPTIONS
from engine.routing import (
    Purpose,
    QuestionChoice,
    RoutingConfig,
    RoutingState,
    pick_next_question,
)
from engine.verdicts import (
    ConfidenceLabel,
    Recommendation,
    Verdict,
    assign_verdict,
)


# Enums -----------------------------------------------------------------------


class SessionStatus(str, Enum):
    """Lifecycle state of a session (spec section 8)."""

    ACTIVE = "active"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class EndReason(str, Enum):
    """Reason a session was ended (spec section 5.5 and 8.2)."""

    NATURAL = "natural"        # all skills resolved or budget exhausted
    ABANDONED = "abandoned"
    TIMEOUT = "timeout"
    LEARNER_QUIT = "learner_quit"


class RoutingMode(str, Enum):
    """Where a response was decided (spec section 4)."""

    ONLINE = "online"
    OFFLINE_REPLAY = "offline_replay"


# Data structures ------------------------------------------------------------


@dataclass(frozen=True)
class QuestionHistoryEntry:
    """One entry in question_history (spec section 6.1 schema)."""

    sequence: int
    question_id: str
    skill_id: str
    is_correct: bool
    asked_at: datetime
    posterior_before: float
    posterior_after: float
    purpose: Purpose
    routing_mode: RoutingMode
    # The learner's raw typed answer, for Stage B only (never consumed by
    # mastery). None when the caller did not send it (the core pilot).
    raw_response: Optional[str] = None


@dataclass(frozen=True)
class SkillVerdict:
    """A persisted verdict (one row in learner_skill_verdicts).

    `operation` is the L1 skill (Addition / Subtraction / Multiplication /
    Division). Stored alongside the L2.5 skill_id so downstream consumers
    that filter by operation (e.g., the practice router) don't need a
    separate lookup table.

    `propagation_updates` is the count of lattice-propagation events that
    moved this skill's posterior during the session; required by spec
    section 6.1 and used by the verdict rules in spec section 7.6 to
    separate priors-only from propagation-only resolutions.
    """

    skill_id: str
    operation: str
    posterior: float
    direct_observations: int
    propagation_updates: int
    confidence_label: ConfidenceLabel
    recommendation: Recommendation


@dataclass
class Session:
    """Persistent representation of a diagnostic session.

    Mirrors the learner_diagnostic_sessions document from spec section 6.1.
    The storage layer is responsible for serialising this to and from BSON.
    """

    sub_session_id: str
    learner_id: str
    tenant_id: str
    class_id: str
    grade: int
    status: SessionStatus
    started_at: datetime
    ended_at: Optional[datetime]
    engine_version: str
    posteriors: Dict[str, float]
    direct_obs_count: Dict[str, int]
    questions_per_operation: Dict[str, int]
    question_history: List[QuestionHistoryEntry]
    routing_mode_counts: Dict[RoutingMode, int] = field(default_factory=dict)
    tree_id_used: Optional[str] = None
    tree_version_used: Optional[int] = None

    # Per-skill count of times this skill's posterior was moved by lattice
    # propagation from a different skill's observation (spec sections 6.1
    # and 7.6). Incremented in record_response after each propagate() call,
    # for every skill in the returned propagation-update dict. Used by the
    # verdict rule table to distinguish priors-only resolutions (no direct
    # obs AND no propagation updates -> trust the prior, earn confident)
    # from propagation-only resolutions (no direct obs BUT propagation
    # touched -> downgrade to uncertain so MainD verifies).
    propagation_updates_count: Dict[str, int] = field(default_factory=dict)

    # The most-recent QuestionPick handed to the client (spec section 7.7
    # per-item overrides). Set by the route handler immediately before
    # returning a question to the client; read on the next /response to
    # apply per-item calibrated slip / guess in the Bayes update. Cleared
    # by record_response once the matching response has been applied.
    # Not part of the spec section 6.1 schema; engine-internal state.
    pending_question_id: Optional[str] = None
    pending_question_slip_override: Optional[float] = None
    pending_question_guess_override: Optional[float] = None
    # The skill the pending question belongs to. Stored so a replay can re-serve
    # the same pending question (id + skill) idempotently, and because the
    # coverage controller's backfill picks are skill-agnostic (the skill is not
    # otherwise recoverable from the stashed id).
    pending_question_skill_id: Optional[str] = None

    # --- misconception-coverage ledger (spec sections 3.3-3.4) -------------
    # Per-misconception counters, updated at answer-time in record_response
    # whenever an answered question carries the tag. `asked` means asked AND
    # answered; `wrong` is derived as asked - correct. `applicable` is the set
    # of misconceptions the pool can actually serve to this learner, computed
    # once at session start (by the route, which holds the pool) and then fixed.
    # In legacy mode (no per-tenant lookup) the ledger stays empty and the
    # layer is inert. Populated but not yet acted on at this checkpoint.
    misconception_asked: Dict[str, int] = field(default_factory=dict)
    misconception_correct: Dict[str, int] = field(default_factory=dict)
    misconception_applicable: Set[str] = field(default_factory=set)
    # Question count at the moment Phase 1 (adaptive) ended, set once by the
    # phase controller. Marks the reserve baseline: reserve_consumed =
    # questions_total - this. Persisting it forfeits any unspent adaptive budget
    # (the reserve is capped at reserve_size, per spec) and prevents Phase 1 from
    # "resuming" if a later backfill answer un-resolves a skill. None until
    # Phase 1 ends; stays None for the whole session when reserve_size is 0.
    reserve_phase_started_at: Optional[int] = None
    # The chosen question's 11 tags, stashed by the route alongside the slip/
    # guess overrides and read+cleared by record_response to update the ledger.
    # None when the pool carried no tags (legacy mode).
    pending_question_misconceptions: Optional[Dict[str, int]] = None

    @property
    def questions_total(self) -> int:
        """Total questions asked so far. Derived from question_history length."""
        return len(self.question_history)


@dataclass(frozen=True)
class EngineParams:
    """All engine parameters needed to run one session.

    Built by the storage/API layer from the loaded engine config and the
    learner's grade. Treated as immutable for the duration of the session.
    """

    grade: int
    skills_in_scope: Sequence[str]
    skill_to_operation: Mapping[str, str]
    operation_anchors: Mapping[str, str]
    priors: Mapping[str, float]
    routing_config: RoutingConfig
    lattice_index: LatticeIndex
    slip: float
    guess: float
    edge_propagation_value: float
    # Misconception-coverage reserve: questions withheld from Phase 1 for
    # backfill / leftover. 0 (default) means no reserve -> the coverage phase
    # controller is inert and Phase 1 runs the full grade budget, identical to
    # before the layer. `misconception_conditional_extra` (x) is the max extra
    # asks beyond target under the v7 reachability gate; cap = target + x. Default
    # 2 (so cap=4, which tolerates one slip while clearing at 75%). The two
    # thresholds are the v7 accuracy bands; defaults mirror the module constants
    # in engine.misconception and are overridden from config (selection spec 3.5).
    reserve_size: int = 0
    misconception_conditional_extra: int = 2
    misconception_clear_threshold: float = 0.75
    misconception_present_threshold: float = 0.50

    @property
    def mastery_threshold(self) -> float:
        return self.routing_config.mastery_threshold

    @property
    def adaptive_budget(self) -> int:
        """Phase 1 question stop: the grade total minus the coverage reserve.
        Equals the grade total when reserve_size is 0 (coverage inert)."""
        return self.routing_config.total_budget - self.reserve_size

    @property
    def not_mastered_threshold(self) -> float:
        return self.routing_config.not_mastered_threshold


# Result types --------------------------------------------------------------


@dataclass(frozen=True)
class StartResult:
    session: Session
    first_question: Optional[QuestionChoice]


@dataclass(frozen=True)
class ResponseResult:
    next_question: Optional[QuestionChoice]
    verdicts: Optional[List[SkillVerdict]]
    is_idempotent_replay: bool


@dataclass(frozen=True)
class EndResult:
    verdicts: List[SkillVerdict]


# Exceptions ----------------------------------------------------------------


class SessionStateError(Exception):
    """Operation attempted on a session in the wrong state."""


class UnknownSkillError(Exception):
    """skill_id is not in the learner's scope for this session."""


class SessionConflictError(Exception):
    """Same question_id submitted with different is_correct (spec section 8.3)."""


# Default clock -------------------------------------------------------------


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


# Public functions ----------------------------------------------------------


def start_session(
    *,
    sub_session_id: str,
    learner_id: str,
    tenant_id: str,
    class_id: str,
    grade: int,
    engine_version: str,
    params: EngineParams,
    clock: Optional[Callable[[], datetime]] = None,
) -> StartResult:
    """Create a new active Session and pick the first question.

    Posteriors are initialised from cohort priors. If a skill is missing from
    priors, it defaults to 0.5 (the entropy maximum).
    """
    if grade != params.grade:
        raise ValueError(
            f"grade {grade} does not match EngineParams.grade {params.grade}"
        )
    clock = clock or _default_clock
    now = clock()

    posteriors = {s: float(params.priors.get(s, 0.5)) for s in params.skills_in_scope}
    direct_obs_count = {s: 0 for s in params.skills_in_scope}

    session = Session(
        sub_session_id=sub_session_id,
        learner_id=learner_id,
        tenant_id=tenant_id,
        class_id=class_id,
        grade=grade,
        status=SessionStatus.ACTIVE,
        started_at=now,
        ended_at=None,
        engine_version=engine_version,
        posteriors=posteriors,
        direct_obs_count=direct_obs_count,
        questions_per_operation={},
        question_history=[],
        routing_mode_counts={RoutingMode.ONLINE: 0, RoutingMode.OFFLINE_REPLAY: 0},
        # Ledger counters start at zero for all 11 misconceptions; the applicable
        # set is filled by the route (which holds the pool) right after this call.
        misconception_asked={m: 0 for m in MISCONCEPTIONS},
        misconception_correct={m: 0 for m in MISCONCEPTIONS},
    )

    first_question = _select_next(session, params)
    return StartResult(session=session, first_question=first_question)


def record_response(
    session: Session,
    *,
    skill_id: str,
    question_id: str,
    is_correct: bool,
    params: EngineParams,
    routing_mode: RoutingMode = RoutingMode.ONLINE,
    clock: Optional[Callable[[], datetime]] = None,
    slip_override: Optional[float] = None,
    guess_override: Optional[float] = None,
    defer_next: bool = False,
    raw_response: Optional[str] = None,
) -> ResponseResult:
    """Apply a scored response and return the next decision.

    Mutates the session in place: posteriors, direct_obs_count,
    questions_per_operation, question_history, routing_mode_counts, and
    (if the session completes) status, ended_at. Also clears the
    pending_question_* fields once the matching response has been applied.

    Per-item calibration (spec section 7.7): if slip_override and / or
    guess_override are provided (i.e. not None), they replace params.slip
    and params.guess in the Bayes update for this question. The caller
    (typically the API route handler) sources these from the session's
    pending_question_* fields, which were populated when the question was
    handed to the client. When the values are None, the engine uses the
    uniform defaults from engine_config.yaml.

    Idempotency (spec section 8.3): if the most recent question_history entry
    has the same question_id, this call is treated as a replay. Same
    is_correct returns the same next-question response without applying a
    second update; different is_correct raises SessionConflictError.

    defer_next (misconception-coverage route): when True, this call does the
    state mutation only and does NOT decide the next question or finalize the
    session. It returns a ResponseResult with next_question=None, verdicts=None,
    and is_idempotent_replay set, leaving the caller (the coverage-aware route)
    to run the phase controller and finalize via finalize_session(). When False
    (the default, used by the CLI and the legacy path) behaviour is unchanged.
    """
    if session.status != SessionStatus.ACTIVE:
        raise SessionStateError(
            f"cannot record response on session with status={session.status.value}"
        )
    if skill_id not in session.posteriors:
        raise UnknownSkillError(
            f"skill_id '{skill_id}' is not in scope for this session"
        )

    # 1. Idempotency check on most-recent entry only.
    if session.question_history:
        last = session.question_history[-1]
        if last.question_id == question_id:
            if last.is_correct == is_correct:
                if defer_next:
                    return ResponseResult(
                        next_question=None, verdicts=None,
                        is_idempotent_replay=True,
                    )
                return _build_response_result(
                    session, params, is_idempotent_replay=True, clock=clock,
                )
            raise SessionConflictError(
                f"question_id '{question_id}' was already submitted with "
                f"is_correct={last.is_correct}, now received is_correct={is_correct}"
            )

    clock = clock or _default_clock
    now = clock()

    # 2. Determine purpose from the pre-update routing state.
    purpose = _infer_purpose(session, params, skill_id)

    # 3. Bayes update on the source skill. Per-item slip / guess overrides
    #    (spec section 7.7) win over the config defaults when provided.
    effective_slip = slip_override if slip_override is not None else params.slip
    effective_guess = guess_override if guess_override is not None else params.guess
    posterior_before = session.posteriors[skill_id]
    posterior_after = update_posterior(
        prior=posterior_before,
        is_correct=is_correct,
        slip=effective_slip,
        guess=effective_guess,
    )
    session.posteriors[skill_id] = posterior_after
    session.direct_obs_count[skill_id] = session.direct_obs_count.get(skill_id, 0) + 1

    # 4. Lattice propagation (reads the just-updated source posterior).
    propagation_updates = propagate(
        source_skill=skill_id,
        is_correct=is_correct,
        posteriors=session.posteriors,
        lattice_index=params.lattice_index,
        edge_propagation_value=params.edge_propagation_value,
    )
    for skill, new_p in propagation_updates.items():
        session.posteriors[skill] = new_p
        # Increment the per-skill propagation counter. Used by spec section
        # 7.6 to separate priors-only resolutions (counter stays at 0 ->
        # confident verdict) from propagation-only resolutions (counter
        # >= 1 -> downgraded to uncertain).
        session.propagation_updates_count[skill] = (
            session.propagation_updates_count.get(skill, 0) + 1
        )

    # 5. Update counters.
    op = params.skill_to_operation.get(skill_id)
    if op is not None:
        session.questions_per_operation[op] = (
            session.questions_per_operation.get(op, 0) + 1
        )
    session.routing_mode_counts[routing_mode] = (
        session.routing_mode_counts.get(routing_mode, 0) + 1
    )

    # 6. Append to question_history.
    session.question_history.append(QuestionHistoryEntry(
        sequence=len(session.question_history) + 1,
        question_id=question_id,
        skill_id=skill_id,
        is_correct=is_correct,
        asked_at=now,
        posterior_before=posterior_before,
        posterior_after=posterior_after,
        purpose=purpose,
        routing_mode=routing_mode,
        raw_response=raw_response,
    ))

    # 6b. Update the misconception ledger (spec section 3.3). The answered
    #     question's tags were stashed by the route alongside the slip/guess
    #     overrides. Count every tag the question carries (asked; correct only
    #     when the learner got it right). Reached only on a real (non-replay)
    #     update, so each answered question is counted exactly once. None in
    #     legacy mode (no tags), so the ledger stays untouched there.
    if session.pending_question_misconceptions:
        for tag, value in session.pending_question_misconceptions.items():
            if value == 1:
                session.misconception_asked[tag] = (
                    session.misconception_asked.get(tag, 0) + 1
                )
                if is_correct:
                    session.misconception_correct[tag] = (
                        session.misconception_correct.get(tag, 0) + 1
                    )

    # 7. Clear the pending_question_* state. The next question (if any) will
    #    be picked by the route handler, which will populate these fields
    #    again before returning to the client.
    session.pending_question_id = None
    session.pending_question_slip_override = None
    session.pending_question_guess_override = None
    session.pending_question_skill_id = None
    session.pending_question_misconceptions = None

    if defer_next:
        return ResponseResult(
            next_question=None, verdicts=None, is_idempotent_replay=False,
        )
    return _build_response_result(
        session, params, is_idempotent_replay=False, clock=clock,
    )


def end_session(
    session: Session,
    *,
    reason: EndReason,
    params: EngineParams,
    clock: Optional[Callable[[], datetime]] = None,
) -> EndResult:
    """End an active session early. Returns verdicts for all skills.

    NATURAL ends set status=COMPLETE; all other reasons set status=ABANDONED.
    For natural completion via record_response, status is set automatically;
    this function is for explicit termination by aml-api-service (timeout,
    abandonment, learner quit).
    """
    if session.status != SessionStatus.ACTIVE:
        raise SessionStateError(
            f"cannot end session with status={session.status.value}"
        )
    clock = clock or _default_clock
    session.status = (
        SessionStatus.COMPLETE if reason == EndReason.NATURAL else SessionStatus.ABANDONED
    )
    session.ended_at = clock()
    return EndResult(verdicts=compute_verdicts(session, params=params))


def compute_verdicts(session: Session, *, params: EngineParams) -> List[SkillVerdict]:
    """Compute per-skill verdicts from current state. Pure read; no mutation.

    Walks params.skills_in_scope so every in-scope skill gets a verdict, even
    those never observed (the downgrade rule in verdicts.assign_verdict handles
    propagation-only resolutions correctly).
    """
    out: List[SkillVerdict] = []
    for skill in params.skills_in_scope:
        posterior = session.posteriors.get(skill, float(params.priors.get(skill, 0.5)))
        direct_obs = session.direct_obs_count.get(skill, 0)
        propagation_updates = session.propagation_updates_count.get(skill, 0)
        verdict: Verdict = assign_verdict(
            posterior=posterior,
            direct_observations=direct_obs,
            mastery_threshold=params.mastery_threshold,
            not_mastered_threshold=params.not_mastered_threshold,
            propagation_updates=propagation_updates,
        )
        out.append(SkillVerdict(
            skill_id=skill,
            operation=params.skill_to_operation.get(skill, ""),
            posterior=verdict.posterior,
            direct_observations=verdict.direct_observations,
            propagation_updates=verdict.propagation_updates,
            confidence_label=verdict.confidence_label,
            recommendation=verdict.recommendation,
        ))
    return out


# Internal helpers ----------------------------------------------------------


def _select_next(session: Session, params: EngineParams) -> Optional[QuestionChoice]:
    """Wrap routing.pick_next_question with a freshly built RoutingState."""
    state = RoutingState(
        skills_in_scope=params.skills_in_scope,
        skill_to_operation=params.skill_to_operation,
        operation_anchors=params.operation_anchors,
        posteriors=session.posteriors,
        direct_obs_count=session.direct_obs_count,
        questions_total=session.questions_total,
        questions_per_operation=session.questions_per_operation,
    )
    return pick_next_question(state, params.routing_config, params.lattice_index)


def _infer_purpose(
    session: Session, params: EngineParams, skill_id: str,
) -> Purpose:
    """Re-derive the purpose of an incoming response using the pre-update state.

    The API caller submits skill_id and question_id but not purpose; we
    re-compute by asking routing what it would pick right now. If the
    incoming skill matches, we use routing's purpose tag. Mismatches
    (which shouldn't happen with a well-behaved caller) fall back to
    INFO_GAIN.
    """
    expected = _select_next(session, params)
    if expected is not None and expected.skill == skill_id:
        return expected.purpose
    return Purpose.INFO_GAIN


def finalize_session(
    session: Session,
    params: EngineParams,
    *,
    clock: Optional[Callable[[], datetime]] = None,
) -> List[SkillVerdict]:
    """Compute verdicts and mark the session complete.

    Used by the coverage-aware route after the phase controller signals
    completion (the defer_next path). Mirrors the natural-completion branch of
    _build_response_result: compute verdicts, and if the session is still ACTIVE
    set status=COMPLETE and ended_at. Idempotent if already COMPLETE (it just
    recomputes verdicts and leaves status/ended_at as-is).
    """
    verdicts = compute_verdicts(session, params=params)
    if session.status == SessionStatus.ACTIVE:
        session.status = SessionStatus.COMPLETE
        session.ended_at = (clock or _default_clock)()
    return verdicts


def _build_response_result(
    session: Session,
    params: EngineParams,
    *,
    is_idempotent_replay: bool,
    clock: Optional[Callable[[], datetime]],
) -> ResponseResult:
    """Determine next_question or verdicts after a response is processed.

    If routing returns None, the session has just naturally completed:
    set status, ended_at, and return verdicts.
    """
    next_question = _select_next(session, params)
    if next_question is not None:
        return ResponseResult(
            next_question=next_question,
            verdicts=None,
            is_idempotent_replay=is_idempotent_replay,
        )

    verdicts = finalize_session(session, params, clock=clock)
    return ResponseResult(
        next_question=None,
        verdicts=verdicts,
        is_idempotent_replay=is_idempotent_replay,
    )
