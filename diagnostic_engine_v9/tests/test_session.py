"""Unit tests for engine.session."""

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

import pytest

from engine.lattice import LatticeEdge, LatticeIndex
from engine.routing import Purpose, RoutingConfig
from engine.session import (
    EndReason,
    EndResult,
    EngineParams,
    QuestionHistoryEntry,
    ResponseResult,
    RoutingMode,
    Session,
    SessionConflictError,
    SessionStateError,
    SessionStatus,
    SkillVerdict,
    StartResult,
    UnknownSkillError,
    compute_verdicts,
    end_session,
    record_response,
    start_session,
)
from engine.verdicts import ConfidenceLabel, Recommendation


# Test fixtures -----------------------------------------------------------------

ENGINE_VERSION = "0.1.0-test"

# A small but realistic-feeling scope: 2 Multiplication, 2 Addition skills.
SKILLS = ["Tables 1 to 9", "2D x 1D", "1D+1D sum upto 9", "2-digit Addition with carry"]
SKILL_TO_OP = {
    "Tables 1 to 9": "Multiplication",
    "2D x 1D": "Multiplication",
    "1D+1D sum upto 9": "Addition",
    "2-digit Addition with carry": "Addition",
}
ANCHORS = {"Multiplication": "Tables 1 to 9", "Addition": "1D+1D sum upto 9"}
PRIORS = {
    "Tables 1 to 9": 0.5,
    "2D x 1D": 0.5,
    "1D+1D sum upto 9": 0.7,
    "2-digit Addition with carry": 0.3,
}


def make_routing_config(
    *,
    operation_order=("Multiplication", "Addition"),
    per_operation_budget=6,
    total_budget=20,
) -> RoutingConfig:
    return RoutingConfig(
        operation_order=list(operation_order),
        per_operation_budget=per_operation_budget,
        total_budget=total_budget,
        mastery_threshold=0.95,
        not_mastered_threshold=0.10,
        verification_high=0.85,
        verification_low=0.15,
        info_gain_edge_bonus=0.5,
    )


def make_params(
    *,
    skills: Sequence[str] = SKILLS,
    skill_to_op: Mapping[str, str] = SKILL_TO_OP,
    anchors: Mapping[str, str] = ANCHORS,
    priors: Mapping[str, float] = PRIORS,
    routing_config: RoutingConfig = None,
    lattice_edges: Iterable[LatticeEdge] = (),
    slip: float = 0.10,
    guess: float = 0.15,
    edge_propagation_value: float = 0.90,
    grade: int = 3,
) -> EngineParams:
    return EngineParams(
        grade=grade,
        skills_in_scope=list(skills),
        skill_to_operation=dict(skill_to_op),
        operation_anchors=dict(anchors),
        priors=dict(priors),
        routing_config=routing_config or make_routing_config(),
        lattice_index=LatticeIndex(list(lattice_edges)),
        slip=slip,
        guess=guess,
        edge_propagation_value=edge_propagation_value,
    )


def fixed_clock(start: datetime = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)):
    """Returns a clock callable that advances by 1 second per call."""
    state = {"now": start}

    def now() -> datetime:
        result = state["now"]
        state["now"] = result + timedelta(seconds=1)
        return result

    return now


def start_simple_session(params: EngineParams = None, clock=None) -> StartResult:
    return start_session(
        sub_session_id="ss-1",
        learner_id="learner-1",
        tenant_id="tenant-1",
        class_id="class-1",
        grade=3,
        engine_version=ENGINE_VERSION,
        params=params or make_params(),
        clock=clock or fixed_clock(),
    )


# start_session ----------------------------------------------------------------


class TestStartSession:
    def test_creates_active_session(self):
        result = start_simple_session()
        assert result.session.status == SessionStatus.ACTIVE
        assert result.session.sub_session_id == "ss-1"
        assert result.session.learner_id == "learner-1"
        assert result.session.tenant_id == "tenant-1"
        assert result.session.grade == 3
        assert result.session.engine_version == ENGINE_VERSION
        assert result.session.ended_at is None

    def test_posteriors_initialised_from_priors(self):
        result = start_simple_session()
        assert result.session.posteriors == PRIORS

    def test_missing_prior_defaults_to_half(self):
        params = make_params(priors={"Tables 1 to 9": 0.5})  # other skills not in priors
        result = start_session(
            sub_session_id="ss-1", learner_id="l", tenant_id="t", class_id="c",
            grade=3, engine_version=ENGINE_VERSION, params=params,
        )
        for s in SKILLS:
            if s != "Tables 1 to 9":
                assert result.session.posteriors[s] == 0.5

    def test_direct_obs_initialised_to_zero(self):
        result = start_simple_session()
        for s in SKILLS:
            assert result.session.direct_obs_count[s] == 0

    def test_history_initially_empty(self):
        result = start_simple_session()
        assert result.session.question_history == []
        assert result.session.questions_total == 0

    def test_first_question_is_first_op_anchor(self):
        # Multiplication is first in op order; its anchor is "Tables 1 to 9".
        result = start_simple_session()
        assert result.first_question is not None
        assert result.first_question.skill == "Tables 1 to 9"
        assert result.first_question.purpose == Purpose.ANCHOR

    def test_empty_scope_returns_no_first_question(self):
        params = make_params(skills=[], skill_to_op={}, anchors={}, priors={})
        result = start_session(
            sub_session_id="ss-1", learner_id="l", tenant_id="t", class_id="c",
            grade=3, engine_version=ENGINE_VERSION, params=params,
        )
        assert result.first_question is None
        # Session is still ACTIVE; the API layer decides what to do next.
        assert result.session.status == SessionStatus.ACTIVE

    def test_grade_mismatch_raises(self):
        params = make_params(grade=3)
        with pytest.raises(ValueError, match="grade"):
            start_session(
                sub_session_id="ss-1", learner_id="l", tenant_id="t", class_id="c",
                grade=4, engine_version=ENGINE_VERSION, params=params,
            )


# record_response basic mechanics ---------------------------------------------


class TestRecordResponseMechanics:
    def test_applies_bayes_update_on_correct(self):
        params = make_params()
        session = start_simple_session(params).session
        result = record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        # P(mastered | correct, prior=0.5) = 0.9*0.5 / (0.9*0.5 + 0.15*0.5) = 6/7
        assert math.isclose(session.posteriors["Tables 1 to 9"], 6 / 7, rel_tol=1e-9)
        assert result.is_idempotent_replay is False

    def test_applies_bayes_update_on_incorrect(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=False, params=params,
        )
        # P(mastered | incorrect, prior=0.5) = 0.1*0.5 / (0.1*0.5 + 0.85*0.5) = 2/19
        assert math.isclose(session.posteriors["Tables 1 to 9"], 2 / 19, rel_tol=1e-9)

    def test_direct_obs_count_incremented(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        assert session.direct_obs_count["Tables 1 to 9"] == 1
        # Other skills unchanged.
        assert session.direct_obs_count["2D x 1D"] == 0

    def test_questions_per_operation_incremented(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        assert session.questions_per_operation == {"Multiplication": 1}

    def test_routing_mode_counts_incremented(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params, routing_mode=RoutingMode.ONLINE,
        )
        assert session.routing_mode_counts[RoutingMode.ONLINE] == 1
        assert session.routing_mode_counts[RoutingMode.OFFLINE_REPLAY] == 0

    def test_offline_replay_routing_mode(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params, routing_mode=RoutingMode.OFFLINE_REPLAY,
        )
        assert session.routing_mode_counts[RoutingMode.OFFLINE_REPLAY] == 1
        assert session.routing_mode_counts[RoutingMode.ONLINE] == 0
        assert session.question_history[-1].routing_mode == RoutingMode.OFFLINE_REPLAY


class TestQuestionHistoryEntry:
    def test_entry_captured_correctly(self):
        params = make_params()
        clock = fixed_clock()
        session = start_simple_session(params, clock=clock).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q-abc",
            is_correct=True, params=params, clock=clock,
        )
        assert len(session.question_history) == 1
        e = session.question_history[0]
        assert e.sequence == 1
        assert e.question_id == "q-abc"
        assert e.skill_id == "Tables 1 to 9"
        assert e.is_correct is True
        assert e.purpose == Purpose.ANCHOR
        assert e.routing_mode == RoutingMode.ONLINE
        assert e.posterior_before == 0.5  # the prior
        assert math.isclose(e.posterior_after, 6 / 7, rel_tol=1e-9)

    def test_sequence_increments(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        record_response(
            session, skill_id="2D x 1D", question_id="q2",
            is_correct=False, params=params,
        )
        assert session.question_history[0].sequence == 1
        assert session.question_history[1].sequence == 2


# Purpose inference -----------------------------------------------------------


class TestPurposeInference:
    def test_first_question_in_op_is_anchor(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        assert session.question_history[-1].purpose == Purpose.ANCHOR

    def test_verification_when_propagation_pushed_into_extreme_zone(self):
        # Lattice edge: "2D x 1D" -> "Tables 1 to 9" (harder -> easier).
        # Convention from real lattice: arrows point toward prerequisites.
        # Asking "2D x 1D" correctly pushes "Tables 1 to 9" toward 0.9.
        edge = LatticeEdge(
            skill_a="2D x 1D", skill_b="Tables 1 to 9",
            operation_a="Multiplication", operation_b="Multiplication",
            p_b_given_a=0.95, p_b_given_not_a=0.5, weight=1.0,
        )
        params = make_params(lattice_edges=[edge])
        # We need Tables to start at the threshold so that propagation pushes
        # it into the verification zone without a direct test on Tables.
        priors = dict(PRIORS)
        priors["Tables 1 to 9"] = 0.5  # exactly 0.5; will be pushed to 0.9 by edge
        priors["2D x 1D"] = 0.5
        params = make_params(lattice_edges=[edge], priors=priors)
        session = start_simple_session(params).session

        # Step 1: anchor on Tables (the configured anchor). Skip it by changing the anchor.
        # Easier: directly ask 2D x 1D first. To do that, we need the anchor to NOT be
        # Tables, OR we need to ask it as the anchor and have it move into the zone.
        # 
        # Path: ask the anchor (Tables) correctly, posterior moves to 6/7 ~ 0.857.
        # On the next call, the anchor's been done; we go to verification/info_gain.
        # Now ask 2D x 1D correctly: posterior moves to 6/7, propagation pushes
        # Tables toward 0.9. But Tables already at 0.857 < 0.9, so Tables goes
        # to max(0.857, 0.9) = 0.9. Then verification trigger? Tables has direct_obs=1
        # (from the anchor), so no verification.
        #
        # To get verification, we need Tables to have direct_obs=0 AND be in the
        # extreme zone via propagation. That means we never ask Tables directly.
        # Try: change the anchor config so Tables is not the anchor.
        params2 = make_params(
            lattice_edges=[edge],
            priors=priors,
            anchors={"Multiplication": "2D x 1D", "Addition": "1D+1D sum upto 9"},
        )
        session = start_simple_session(params2).session
        # Anchor is "2D x 1D". Ask it correctly.
        record_response(
            session, skill_id="2D x 1D", question_id="q1",
            is_correct=True, params=params2,
        )
        # Posterior of 2D x 1D: 6/7 ~ 0.857.
        # Propagation: 2D x 1D correct + posterior > 0.5 -> push Tables toward 0.9.
        # Tables was at 0.5, weighted blend = 1.0 * 0.9 + 0 * 0.5 = 0.9.
        assert math.isclose(session.posteriors["Tables 1 to 9"], 0.9, rel_tol=1e-9)
        # Tables has direct_obs == 0 and posterior 0.9 >= verification_high (0.85).
        # Next question should be a verification on Tables.
        next_pick = record_response(
            session, skill_id="Tables 1 to 9", question_id="q2",
            is_correct=True, params=params2,
        )
        # The response we just recorded should have purpose=VERIFICATION.
        assert session.question_history[-1].purpose == Purpose.VERIFICATION

    def test_info_gain_when_no_anchor_no_verification(self):
        # Anchor done (Multiplication anchor asked), no extreme posteriors with
        # zero direct obs in any op. Next pick should be INFO_GAIN.
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        # After this: Tables direct_obs=1, posterior 6/7 ~ 0.857. 2D x 1D
        # posterior still 0.5 with 0 direct obs. Not in extreme zone, so
        # no verification. Next pick: highest info-gain unresolved.
        record_response(
            session, skill_id="2D x 1D", question_id="q2",
            is_correct=True, params=params,
        )
        assert session.question_history[-1].purpose == Purpose.INFO_GAIN


# Propagation in record_response ----------------------------------------------


class TestPropagationApplied:
    def test_forward_propagation_updates_target_posterior(self):
        # When 2D x 1D is observed correct, the edge pushes Tables 1 to 9 up.
        edge = LatticeEdge(
            skill_a="2D x 1D", skill_b="Tables 1 to 9",
            operation_a="Multiplication", operation_b="Multiplication",
            p_b_given_a=0.95, p_b_given_not_a=0.5, weight=1.0,
        )
        params = make_params(
            lattice_edges=[edge],
            anchors={"Multiplication": "2D x 1D", "Addition": "1D+1D sum upto 9"},
        )
        session = start_simple_session(params).session
        record_response(
            session, skill_id="2D x 1D", question_id="q1",
            is_correct=True, params=params,
        )
        # 2D x 1D posterior went up via Bayes (0.5 -> 6/7) and Tables 1 to 9
        # was pushed via propagation toward 0.9.
        assert session.posteriors["Tables 1 to 9"] == 0.9

    def test_no_propagation_when_source_posterior_doesnt_cross_half(self):
        # When a correct response moves the source's posterior but it stays at
        # or below 0.5, the lattice trigger (spec section 7.3: "now above 0.5")
        # does not fire and the target's posterior is unchanged.
        edge = LatticeEdge(
            skill_a="2D x 1D", skill_b="Tables 1 to 9",
            operation_a="Multiplication", operation_b="Multiplication",
            p_b_given_a=0.95, p_b_given_not_a=0.5, weight=1.0,
        )
        # Source prior 0.10: a single correct response gives Bayes update
        # 0.9 * 0.10 / (0.9 * 0.10 + 0.15 * 0.90) = 0.09 / 0.225 = 0.4,
        # which is <= 0.5, so the forward-propagation trigger does NOT fire.
        priors = {**PRIORS, "2D x 1D": 0.10, "Tables 1 to 9": 0.3}
        params = make_params(
            lattice_edges=[edge], priors=priors,
            anchors={"Multiplication": "2D x 1D", "Addition": "1D+1D sum upto 9"},
        )
        session = start_simple_session(params).session
        record_response(
            session, skill_id="2D x 1D", question_id="q1",
            is_correct=True, params=params,
        )
        # Source moved up via Bayes but stayed at/below 0.5.
        assert math.isclose(session.posteriors["2D x 1D"], 0.4, rel_tol=1e-9)
        assert session.posteriors["2D x 1D"] <= 0.5
        # Target unchanged: propagation did not fire.
        assert session.posteriors["Tables 1 to 9"] == 0.3

    def test_propagation_updates_counter_increments_on_target_skill(self):
        """Spec section 7.6: propagation_updates_count is incremented per skill
        every time lattice propagation moves that skill's posterior."""
        edge = LatticeEdge(
            skill_a="2D x 1D", skill_b="Tables 1 to 9",
            operation_a="Multiplication", operation_b="Multiplication",
            p_b_given_a=0.95, p_b_given_not_a=0.5, weight=1.0,
        )
        params = make_params(
            lattice_edges=[edge],
            anchors={"Multiplication": "2D x 1D", "Addition": "1D+1D sum upto 9"},
        )
        session = start_simple_session(params).session
        # Pre-propagation: no skill has been touched by propagation.
        assert session.propagation_updates_count == {}

        record_response(
            session, skill_id="2D x 1D", question_id="q1",
            is_correct=True, params=params,
        )
        # The source skill was observed directly; it should NOT appear in
        # the propagation counter (direct obs vs propagation are distinct).
        assert session.propagation_updates_count.get("2D x 1D", 0) == 0
        assert session.direct_obs_count["2D x 1D"] == 1
        # The target skill's posterior moved via propagation; counter = 1.
        assert session.propagation_updates_count["Tables 1 to 9"] == 1
        assert session.direct_obs_count.get("Tables 1 to 9", 0) == 0

    def test_propagation_counter_does_not_increment_when_no_trigger(self):
        """When propagate() returns an empty dict, the counter stays at 0."""
        edge = LatticeEdge(
            skill_a="2D x 1D", skill_b="Tables 1 to 9",
            operation_a="Multiplication", operation_b="Multiplication",
            p_b_given_a=0.95, p_b_given_not_a=0.5, weight=1.0,
        )
        # Source posterior 0.10: correct answer moves to 0.4, no trigger.
        priors = {**PRIORS, "2D x 1D": 0.10, "Tables 1 to 9": 0.3}
        params = make_params(
            lattice_edges=[edge], priors=priors,
            anchors={"Multiplication": "2D x 1D", "Addition": "1D+1D sum upto 9"},
        )
        session = start_simple_session(params).session
        record_response(
            session, skill_id="2D x 1D", question_id="q1",
            is_correct=True, params=params,
        )
        # Propagation did not fire; counter for target stays at 0.
        assert session.propagation_updates_count.get("Tables 1 to 9", 0) == 0


# Session completion ----------------------------------------------------------


class TestSessionCompletion:
    def test_completion_when_total_budget_exhausted(self):
        # Total budget = 2, just enough to anchor each op, then end.
        params = make_params(
            routing_config=make_routing_config(
                operation_order=["Multiplication", "Addition"],
                per_operation_budget=1,
                total_budget=2,
            ),
        )
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        # Multiplication is done (1/1 budget). Move to Addition.
        result = record_response(
            session, skill_id="1D+1D sum upto 9", question_id="q2",
            is_correct=True, params=params,
        )
        # Total budget hit. Session should be complete.
        assert result.next_question is None
        assert result.verdicts is not None
        assert session.status == SessionStatus.COMPLETE
        assert session.ended_at is not None

    def test_completion_when_all_resolved(self):
        # Use priors that almost-resolve everything and one correct answer that
        # carries them over the line.
        priors = {
            "Tables 1 to 9": 0.94,           # one correct lifts to >=0.95
            "2D x 1D": 0.94,
            "1D+1D sum upto 9": 0.94,
            "2-digit Addition with carry": 0.94,
        }
        params = make_params(priors=priors)
        session = start_simple_session(params).session
        # Ask all four anchors / first questions and answer correctly.
        # After each, the skill's posterior should be >= 0.95 (resolved).
        responses = [
            ("Tables 1 to 9", "q1"),
            ("2D x 1D", "q2"),
            ("1D+1D sum upto 9", "q3"),
            ("2-digit Addition with carry", "q4"),
        ]
        result = None
        for skill, qid in responses:
            result = record_response(
                session, skill_id=skill, question_id=qid,
                is_correct=True, params=params,
            )
        assert result.next_question is None
        assert result.verdicts is not None
        assert session.status == SessionStatus.COMPLETE


# Idempotency ------------------------------------------------------------------


class TestIdempotency:
    def test_duplicate_same_is_correct_does_not_update(self):
        params = make_params()
        session = start_simple_session(params).session
        result1 = record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        posterior_after_first = session.posteriors["Tables 1 to 9"]
        history_len_after_first = len(session.question_history)
        # Same call again.
        result2 = record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        # No state change.
        assert session.posteriors["Tables 1 to 9"] == posterior_after_first
        assert len(session.question_history) == history_len_after_first
        assert result2.is_idempotent_replay is True
        # Same next-question response.
        if result1.next_question is not None:
            assert result2.next_question == result1.next_question

    def test_duplicate_different_is_correct_raises(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        with pytest.raises(SessionConflictError, match="q1"):
            record_response(
                session, skill_id="Tables 1 to 9", question_id="q1",
                is_correct=False, params=params,
            )

    def test_different_question_id_processes_normally(self):
        params = make_params()
        session = start_simple_session(params).session
        record_response(
            session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        # Different question_id: not a duplicate.
        result = record_response(
            session, skill_id="2D x 1D", question_id="q2",
            is_correct=True, params=params,
        )
        assert result.is_idempotent_replay is False
        assert len(session.question_history) == 2


# State validation -----------------------------------------------------------


class TestStateValidation:
    def test_record_on_completed_session_raises(self):
        params = make_params()
        session = start_simple_session(params).session
        session.status = SessionStatus.COMPLETE
        with pytest.raises(SessionStateError, match="complete"):
            record_response(
                session, skill_id="Tables 1 to 9", question_id="q1",
                is_correct=True, params=params,
            )

    def test_record_on_abandoned_session_raises(self):
        params = make_params()
        session = start_simple_session(params).session
        session.status = SessionStatus.ABANDONED
        with pytest.raises(SessionStateError, match="abandoned"):
            record_response(
                session, skill_id="Tables 1 to 9", question_id="q1",
                is_correct=True, params=params,
            )

    def test_unknown_skill_raises(self):
        params = make_params()
        session = start_simple_session(params).session
        with pytest.raises(UnknownSkillError, match="not_a_real_skill"):
            record_response(
                session, skill_id="not_a_real_skill", question_id="q1",
                is_correct=True, params=params,
            )


# end_session ----------------------------------------------------------------


class TestEndSession:
    def test_abandoned_sets_status_and_returns_verdicts(self):
        params = make_params()
        session = start_simple_session(params).session
        result = end_session(session, reason=EndReason.ABANDONED, params=params)
        assert session.status == SessionStatus.ABANDONED
        assert session.ended_at is not None
        assert len(result.verdicts) == len(SKILLS)

    def test_timeout_marks_abandoned(self):
        params = make_params()
        session = start_simple_session(params).session
        end_session(session, reason=EndReason.TIMEOUT, params=params)
        assert session.status == SessionStatus.ABANDONED

    def test_natural_marks_complete(self):
        params = make_params()
        session = start_simple_session(params).session
        end_session(session, reason=EndReason.NATURAL, params=params)
        assert session.status == SessionStatus.COMPLETE

    def test_end_on_already_ended_session_raises(self):
        params = make_params()
        session = start_simple_session(params).session
        session.status = SessionStatus.COMPLETE
        with pytest.raises(SessionStateError):
            end_session(session, reason=EndReason.TIMEOUT, params=params)

    def test_verdicts_priors_only_earns_confident_mastered(self):
        # Spec section 7.6 Rule 2: posterior >= mastery_threshold AND
        # direct_obs == 0 AND propagation_updates == 0 -> confident_mastered.
        # Priors are calibrated from real learner data and are trusted
        # without verification when nothing else touched the skill.
        priors = {**PRIORS, "Tables 1 to 9": 0.97}
        params = make_params(priors=priors)
        session = start_simple_session(params).session
        # Sanity: this is the priors-only path; nothing in session touched
        # the skill, so direct_obs and propagation_updates are both 0.
        assert session.direct_obs_count.get("Tables 1 to 9", 0) == 0
        assert session.propagation_updates_count.get("Tables 1 to 9", 0) == 0

        result = end_session(session, reason=EndReason.ABANDONED, params=params)
        tables_verdict = next(v for v in result.verdicts if v.skill_id == "Tables 1 to 9")
        assert tables_verdict.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert tables_verdict.recommendation == Recommendation.SKIP_MAIND


# compute_verdicts ------------------------------------------------------------


class TestComputeVerdicts:
    def test_one_verdict_per_skill_in_scope(self):
        params = make_params()
        session = start_simple_session(params).session
        verdicts = compute_verdicts(session, params=params)
        assert len(verdicts) == len(SKILLS)
        assert {v.skill_id for v in verdicts} == set(SKILLS)

    def test_verdicts_reflect_current_state(self):
        params = make_params()
        session = start_simple_session(params).session
        # Drive Tables 1 to 9 to mastery: 4 correct answers should do it from 0.5.
        for i in range(4):
            try:
                record_response(
                    session, skill_id="Tables 1 to 9", question_id=f"q{i}",
                    is_correct=True, params=params,
                )
            except SessionStateError:
                break  # session may complete mid-way
        # Tables 1 to 9 should now have posterior >= 0.95 with direct_obs >= 1.
        tables_p = session.posteriors["Tables 1 to 9"]
        tables_obs = session.direct_obs_count["Tables 1 to 9"]
        assert tables_p >= 0.95
        assert tables_obs >= 1
        verdicts = compute_verdicts(session, params=params)
        tables_v = next(v for v in verdicts if v.skill_id == "Tables 1 to 9")
        assert tables_v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED


# End-to-end walkthrough -----------------------------------------------------


class TestEndToEndWalkthrough:
    """A complete session: start -> several responses -> natural completion."""

    def test_three_correct_responses_starts_resolving_skills(self):
        # Small scope, generous priors, small budget.
        skills = ["A1", "A2"]
        params = EngineParams(
            grade=3,
            skills_in_scope=skills,
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            priors={"A1": 0.5, "A2": 0.5},
            routing_config=make_routing_config(
                operation_order=["Addition"], per_operation_budget=10, total_budget=10
            ),
            lattice_index=LatticeIndex([]),
            slip=0.10, guess=0.15, edge_propagation_value=0.90,
        )
        result = start_session(
            sub_session_id="ss", learner_id="l", tenant_id="t", class_id="c",
            grade=3, engine_version=ENGINE_VERSION, params=params,
        )
        session = result.session

        # First question: anchor on A1.
        assert result.first_question.skill == "A1"

        # Respond correctly to A1. Posterior moves 0.5 -> 6/7 ~ 0.857.
        r1 = record_response(session, skill_id="A1", question_id="q1",
                             is_correct=True, params=params)
        assert r1.next_question is not None
        assert r1.verdicts is None

        # Second question: info_gain on A2 (highest entropy).
        assert r1.next_question.skill == "A2"

        # Respond correctly to A2. Posterior moves 0.5 -> 6/7.
        r2 = record_response(session, skill_id="A2", question_id="q2",
                             is_correct=True, params=params)
        assert r2.next_question is not None

        # Keep going correctly on both until they cross 0.95.
        # From 6/7 ~ 0.857, two more correct: 6/7 -> 0.9714 (mastery).
        r3 = record_response(session, skill_id=r2.next_question.skill,
                             question_id="q3", is_correct=True, params=params)
        # Session not yet complete; one skill resolved, other still being asked.
        # Continue until completion.
        n = 4
        while r3.next_question is not None and n < 15:
            r3 = record_response(session, skill_id=r3.next_question.skill,
                                 question_id=f"q{n}", is_correct=True, params=params)
            n += 1

        assert session.status == SessionStatus.COMPLETE
        assert r3.verdicts is not None
        # Both skills should be confident_mastered.
        for v in r3.verdicts:
            assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
            assert v.recommendation == Recommendation.SKIP_MAIND


# Per-item slip / guess overrides (fix-pack change #3) ====================


class TestPerItemOverrides:
    """record_response honors per-item slip / guess overrides when provided.

    Spec section 7.7 ("Per-item overrides"): if the QuestionPool returns a
    calibrated slip_i and / or guess_i for the picked question, the engine
    uses those values in the Bayes update instead of the config defaults.
    Absent overrides (None) fall back to params.slip / params.guess.
    """

    def _apply_one(self, *, slip_override=None, guess_override=None, prior=0.5):
        """Start a session, ask one question on 'Tables 1 to 9', return the post-update posterior."""
        params = make_params(
            priors={**PRIORS, "Tables 1 to 9": prior},
            slip=0.10, guess=0.15,
        )
        start = start_simple_session(params=params)
        record_response(
            start.session,
            skill_id="Tables 1 to 9",
            question_id="q1",
            is_correct=True,
            params=params,
            slip_override=slip_override,
            guess_override=guess_override,
        )
        return start.session.posteriors["Tables 1 to 9"]

    def test_no_overrides_uses_config_defaults(self):
        """Baseline: with no overrides, posterior matches the default-Bayes update."""
        # Hand-computed: prior=0.5, correct, slip=0.10, guess=0.15
        # posterior_after = (1-slip)*prior / ((1-slip)*prior + guess*(1-prior))
        #                 = 0.45 / (0.45 + 0.075) = 0.45 / 0.525 = 0.857...
        post = self._apply_one()
        assert post == pytest.approx(0.857, abs=0.001)

    def test_slip_override_changes_posterior(self):
        """A smaller slip (more reliable item) pushes the posterior higher on correct."""
        post_default = self._apply_one()
        post_low_slip = self._apply_one(slip_override=0.02)
        assert post_low_slip > post_default
        # Hand-computed: 0.98*0.5 / (0.98*0.5 + 0.15*0.5) = 0.49 / 0.565 = 0.867
        assert post_low_slip == pytest.approx(0.867, abs=0.001)

    def test_guess_override_changes_posterior(self):
        """A smaller guess (correct = stronger signal) pushes the posterior higher on correct."""
        post_default = self._apply_one()
        post_low_guess = self._apply_one(guess_override=0.05)
        assert post_low_guess > post_default

    def test_both_overrides_applied_together(self):
        """When both overrides are set, both are used in the Bayes update."""
        post = self._apply_one(slip_override=0.02, guess_override=0.05)
        # 0.98*0.5 / (0.98*0.5 + 0.05*0.5) = 0.49 / 0.515 = 0.9514
        assert post == pytest.approx(0.951, abs=0.001)

    def test_partial_override_falls_back_for_unspecified(self):
        """Only slip_override given -> guess stays at config default."""
        params = make_params(slip=0.10, guess=0.15)
        start = start_simple_session(params=params)
        record_response(
            start.session,
            skill_id="Tables 1 to 9",
            question_id="q1",
            is_correct=True,
            params=params,
            slip_override=0.02,
            # guess_override left as None -> 0.15 from params
        )
        post = start.session.posteriors["Tables 1 to 9"]
        # 0.98*0.5 / (0.98*0.5 + 0.15*0.5) = 0.49 / 0.565 = 0.867
        assert post == pytest.approx(0.867, abs=0.001)

    def test_record_response_clears_pending_fields_after_apply(self):
        """After a non-replay record_response, pending_* fields are cleared."""
        params = make_params()
        start = start_simple_session(params=params)
        # Simulate that the route set pending_* before the response.
        start.session.pending_question_id = "q1"
        start.session.pending_question_slip_override = 0.02
        start.session.pending_question_guess_override = 0.05

        record_response(
            start.session,
            skill_id="Tables 1 to 9",
            question_id="q1",
            is_correct=True,
            params=params,
            slip_override=0.02,
            guess_override=0.05,
        )
        assert start.session.pending_question_id is None
        assert start.session.pending_question_slip_override is None
        assert start.session.pending_question_guess_override is None

    def test_idempotent_replay_does_not_clear_pending(self):
        """Idempotent replay short-circuits before the clear step.

        This matters because the route handler relies on pending_* surviving
        a replay so the cached next_question (which routes will resolve via
        the pool) still has the matching overrides available.
        """
        params = make_params()
        start = start_simple_session(params=params)
        # First call applies the update and clears pending_*.
        record_response(
            start.session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        # Routes would now pick the next question and re-set pending_*.
        start.session.pending_question_id = "q-next"
        start.session.pending_question_slip_override = 0.07
        start.session.pending_question_guess_override = 0.11

        # Idempotent replay of the FIRST response: matches last entry in
        # question_history (q1). record_response returns cached without
        # touching pending_*.
        result = record_response(
            start.session, skill_id="Tables 1 to 9", question_id="q1",
            is_correct=True, params=params,
        )
        assert result.is_idempotent_replay is True
        # pending_* untouched
        assert start.session.pending_question_id == "q-next"
        assert start.session.pending_question_slip_override == 0.07
        assert start.session.pending_question_guess_override == 0.11
