"""
Pydantic request and response schemas for the API endpoints.

All request models set extra='forbid' so unexpected fields (potentially PII)
are rejected at the validation layer. The exception handler in api/main.py
translates ValidationError into a PII_FIELD_PRESENT response per spec
section 6.3.
"""

from typing import Dict, List, Literal, Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from engine.verdicts import ConfidenceLabel, Recommendation


# Common config: all request bodies forbid extra fields ----------------------


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# Request schemas ------------------------------------------------------------


class SessionStartRequest(_StrictBase):
    """POST /session/start request body (spec section 5.3)."""

    learner_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    sub_session_id: str = Field(min_length=1)
    class_id: str = Field(min_length=1)
    # Spec section 2 supports grades 2-5 with explicit per-grade config and
    # grades 6-8 falling back to G5. Outside this range is rejected at the
    # Pydantic layer; mapped to INVALID_GRADE by the global exception
    # handler so the error envelope shape is unchanged.
    grade: int = Field(ge=2, le=8)
    # Deactivation Failsafe (spec section 4). Optional: the variants currently
    # switched off on the app. Applied in the candidate filter; persists on the
    # session. `replace` (default) overwrites the session's set (also how a
    # question is switched back on, and an empty list clears it); `append` adds.
    switched_off_question_x_ids: Optional[List[str]] = None
    switched_off_mode: Literal["replace", "append"] = "replace"


class SessionResponseRequest(_StrictBase):
    """POST /session/:id/response request body (spec section 5.4)."""

    learner_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    question_x_id: str = Field(min_length=1)
    is_correct: bool
    response_time_ms: Optional[int] = Field(default=None, ge=0)
    # Deactivation Failsafe (spec section 4): optional switched-off update on the
    # submit-answer call (which selects the next question). See SessionStartRequest.
    switched_off_question_x_ids: Optional[List[str]] = None
    switched_off_mode: Literal["replace", "append"] = "replace"
    # raw_response is the learner's typed answer, for Stage B (misconception
    # classification) ONLY. It is deliberately declared here so it is allow-
    # listed past the extra='forbid' PII guard; mastery never consumes it
    # (is_correct is the only mastery input). Optional and nullable: the core
    # pilot does not send it, and a response without it produces a verdict
    # unchanged. It is never written to logs (see observability.logging
    # allow-list).
    raw_response: Optional[str] = Field(default=None)


class SessionEndRequest(_StrictBase):
    """POST /session/:id/end request body (spec section 5.5)."""

    learner_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    reason: Optional[Literal["abandoned", "timeout", "learner_quit"]] = "abandoned"


# Response sub-schemas -------------------------------------------------------


class QuestionRef(BaseModel):
    """A question reference: x_id plus the canonical skill it tests."""

    question_x_id: str
    skill_id: str


class VerdictPayload(BaseModel):
    """One skill's verdict in the API response (spec section 5.4).

    `propagation_updates` is the count of lattice-propagation events that
    moved this skill's posterior during the session; required by spec
    section 6.1 and exposed in the API so downstream consumers can audit
    why a verdict ended up confident vs uncertain.
    """

    skill_id: str
    operation: str
    posterior: float
    direct_observations: int
    propagation_updates: int
    confidence_label: ConfidenceLabel
    recommendation: Recommendation


class MisconceptionSignalPayload(BaseModel):
    """One misconception's triage signal (verdict-rule spec), a sibling to verdicts.

    `state` is one of not_applicable / likely_present / likely_absent / unsure,
    an accuracy band over all tagged asks (v7): cleared at >=75%, flagged below
    50%, else unsure. This is a prior for MainD, not a verdict; it never alters
    mastery. A carrier shortfall is reported simply as `unsure` (no separate flag).
    """

    misconception: str
    state: str
    asked: int
    correct: int
    wrong: int


# Response result payloads ---------------------------------------------------


class OfflineAnswerItem(_StrictBase):
    """One learner answer collected during an offline segment (mixed-mode v11
    section 9). raw_response IS included for offline answers (not optional) so
    they feed Stage B misconception classification exactly as online answers do;
    the server derives item and calibration from the pool by question_x_id, so
    the batch need not send them. asked_at reuses the existing history-entry
    field for chronological placement within the offline block."""
    question_x_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    is_correct: bool
    raw_response: str
    asked_at: datetime


class OfflineBatchRequest(_StrictBase):
    """Ingest of a completed offline segment (mixed-mode v11 section 9). The tree
    fields are batch-level (one tree per offline segment). resume_anchor is the
    question_x_id of the last answer before the drop (from the resumption token),
    used to place this block in chronological order; it may be null if the drop
    happened before any answer."""
    learner_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    resume_anchor: Optional[str] = None
    tree_id: str = Field(min_length=1)
    tree_version: int
    tree_compat_version: int
    answers: List[OfflineAnswerItem]
    # Deactivation Failsafe (spec section 4): optional switched-off update on the
    # ingest call (which returns the next online question). See SessionStartRequest.
    switched_off_question_x_ids: Optional[List[str]] = None
    switched_off_mode: Literal["replace", "append"] = "replace"


class ReplaceQuestionRequest(_StrictBase):
    """POST /session/:id/replace-question - decline the offered question and get a
    different one (Deactivation Failsafe mechanism 2, spec section 5). The declined
    question_x_id joins a transient per-session set (separate from the switched-off
    list); no answer is recorded and no budget is spent."""
    learner_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    question_x_id: str = Field(min_length=1)


class OfflineTreeRef(BaseModel):
    """A lightweight reference to a precomputed offline decision tree.

    The tree itself is NOT inlined in the session/start response: the
    deserialized G5 tree is ~30 MB of JSON, so inlining it would make every
    session/start body enormous. Instead the client fetches the tree once from
    fetch_path (GET, same X-Internal-Service-Token auth). `grade` is the
    RESOLVED grade after the online engine's fallback (grades 2-4 map to
    themselves, grade 5 and above map to 5), so a G7 session references the G5
    tree. `size_bytes` and `sha256` describe the JSON payload the client will
    receive from fetch_path, for integrity and download sizing.
    """

    available: bool
    grade: int
    engine_version: str
    # The tree's compatibility version - the value the device echoes back in the
    # offline-batch, and what the serving guard checks (mixed-mode v11 decision
    # 8). engine_version is retained for information only; it no longer gates
    # serving.
    tree_compat_version: int
    size_bytes: int
    sha256: str
    fetch_path: str


class ResumptionEntry(BaseModel):
    """One answered entry in the resumption token (mixed-mode v11 section 8). The
    device needs `item` and `operation` to run entry-point matching / no-repeat in
    item space and to structure the offline walk - neither is derivable from the
    shipped artifact (which carries skill and calibration only), so the server
    supplies them here. `item` is None only if the id is not in the pool."""
    question_x_id: str
    is_correct: bool
    item: Optional[str]
    skill_id: str
    operation: Optional[str]
    asked_at: datetime


class ResumptionToken(BaseModel):
    """Server-pushed resumption snapshot (mixed-mode v11 section 8, decision 1).
    The device caches the latest one and, on a connectivity drop, uses it to seed
    the offline walk from the unified history. `resume_anchor` is the
    question_x_id of the last answer recorded so far - echoed back in the
    offline-batch to place it in chronological order (section 9); None before any
    answer. `budget_used` == len(answers), the unified budget already spent. The
    posteriors block (for the deferred confident-skill enhancement, decision 4)
    is intentionally omitted in v1."""
    resume_anchor: Optional[str] = None
    budget_used: int
    answers: List[ResumptionEntry]


class SessionStartResult(BaseModel):
    sub_session_id: str
    first_question: Optional[QuestionRef]
    # None when no offline tree is servable for the (tenant, resolved-grade):
    # a non-Delhi tenant, a grade below G2, or a version-drift mismatch. When
    # servable, this is a reference the client fetches separately (never the
    # inlined tree). Sibling of the verdicts/misconception payloads.
    offline_tree: Optional[OfflineTreeRef] = None
    question_budget: int
    # The resumption snapshot to cache for offline use (mixed-mode v11 section 8).
    # At session start the history is empty (resume_anchor None, answers []).
    resumption_token: Optional[ResumptionToken] = None


class SessionResponseResult(BaseModel):
    """The result payload for a /response call.

    Either next_question is set (session continuing) OR verdicts is set
    (session complete). Never both. When the session completes,
    misconception_signals carries the per-misconception triage signal
    (spec section 7) alongside the verdicts; it is None while continuing.
    """

    session_complete: bool
    next_question: Optional[QuestionRef] = None
    questions_asked_so_far: Optional[int] = None
    questions_remaining_budget: Optional[int] = None
    verdicts: Optional[List[VerdictPayload]] = None
    misconception_signals: Optional[List[MisconceptionSignalPayload]] = None
    # Refreshed resumption snapshot to cache for offline use (mixed-mode v11
    # sections 8, 10 - the token is refreshed on every online turn and after
    # every ingest). None once the session is complete (no offline continuation).
    resumption_token: Optional[ResumptionToken] = None


class SessionEndResult(BaseModel):
    session_complete: bool = True
    next_question: None = None
    verdicts: List[VerdictPayload]
    misconception_signals: Optional[List[MisconceptionSignalPayload]] = None


class VerdictsResult(BaseModel):
    verdicts: List[VerdictPayload]
    misconception_signals: Optional[List[MisconceptionSignalPayload]] = None


class RawResponseItem(BaseModel):
    """One stored raw response, keyed for Stage B's use."""

    question_x_id: str
    raw_response: Optional[str] = None
    is_correct: bool
    skill_id: str


class SessionRawResponsesResult(BaseModel):
    """Result payload for GET /session/:id/responses (spec section 8.4).

    Returns the session's stored raw learner answers so Stage B can classify
    misconceptions from real responses. raw_response is nullable per item:
    it is only present for responses the caller sent it on.
    """

    sub_session_id: str
    learner_id: str
    grade: int
    responses: List[RawResponseItem]


class HealthResult(BaseModel):
    status: str
    version: str
    storage: str
    engine_config_loaded: bool
    tree_versions: Dict[str, int] = Field(default_factory=dict)
    # Grades configured in engine_config.yaml that have no cohort priors.
    # The engine starts up regardless but logs a WARN per grade; see spec
    # section 7.7 and engine.config.check_priors_coverage. Operators can
    # set STRICT_PRIORS_REQUIRED=true to make startup fail-fast instead.
    priors_missing_for_grades: List[int] = Field(default_factory=list)
