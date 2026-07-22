"""
Serialisation between engine dataclasses and MongoDB documents.

Used exclusively by the MongoDB storage backend. The in-memory backend stores
dataclasses directly and doesn't need these helpers.

Schema follows spec section 6.1:
  - learner_diagnostic_sessions: posteriors stored as nested per-skill state
    {skill: {posterior, direct_observations, last_updated_at}}
  - learner_skill_verdicts: one row per (session, skill); l1_skill_id is the
    operation, l2_5_skill_id is the canonical skill name
  - lattice_edges: skill_a / skill_b / weight / probabilities, with
    edge_type derived from operation_a vs operation_b

The `last_updated_at` per skill is set to the session start time as a
placeholder. The engine does not use this field; if engineering needs precise
per-skill timestamps a future refinement can walk question_history.
"""

import uuid
from datetime import datetime
from typing import Any, Dict

from engine.lattice import LatticeEdge
from engine.routing import Purpose
from engine.session import (
    QuestionHistoryEntry,
    RoutingMode,
    Session,
    SessionStatus,
    SkillVerdict,
)
from engine.verdicts import ConfidenceLabel, Recommendation


# === Sessions ===


def session_to_doc(session: Session) -> Dict[str, Any]:
    """Convert a Session dataclass into a MongoDB-ready document.

    The audit fields (created_at, updated_at, created_by, updated_by) are
    NOT set here; the storage layer adds them at insert/update time.
    """
    # Per-skill last_updated_at: walk question_history once to find the
    # most recent direct question on each skill. Skills never directly
    # asked fall back to session.started_at (their posterior is either
    # still at the cohort prior or was moved by lattice propagation;
    # propagation events do not have a timestamp in the session state).
    # See spec section 6.1.
    last_direct_ask: Dict[str, datetime] = {}
    for entry in session.question_history:
        last_direct_ask[entry.skill_id] = entry.asked_at

    posteriors_nested = {
        skill: {
            "posterior": session.posteriors[skill],
            "direct_observations": session.direct_obs_count.get(skill, 0),
            # Per spec section 6.1, propagation_updates is a required field
            # in the per-skill posterior sub-document. Used by the verdict
            # rules in spec section 7.6 to distinguish priors-only from
            # propagation-only resolutions.
            "propagation_updates": session.propagation_updates_count.get(skill, 0),
            "last_updated_at": last_direct_ask.get(skill, session.started_at),
        }
        for skill in session.posteriors
    }
    # The engine carries the most-recent QuestionPick's overrides as
    # pending_* state on Session so that the next /response can apply
    # per-item slip / guess (spec section 7.7). We persist them as a
    # nested 'pending_question' document. When pending_question_id is
    # None, we write None so that absence is round-trippable.
    pending_question = (
        {
            "question_id": session.pending_question_id,
            "slip_override": session.pending_question_slip_override,
            "guess_override": session.pending_question_guess_override,
            "skill_id": session.pending_question_skill_id,
            "misconceptions": session.pending_question_misconceptions,
        }
        if session.pending_question_id is not None
        else None
    )
    return {
        "identifier": session.sub_session_id,
        "learner_id": session.learner_id,
        "tenant_id": session.tenant_id,
        "class_id": session.class_id,
        "grade": session.grade,
        "status": session.status.value,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "engine_version": session.engine_version,
        "tree_id_used": session.tree_id_used,
        "tree_version_used": session.tree_version_used,
        "posteriors": posteriors_nested,
        "questions_per_operation": dict(session.questions_per_operation),
        "question_history": [
            _history_entry_to_doc(e) for e in session.question_history
        ],
        "routing_mode_counts": {
            mode.value: count for mode, count in session.routing_mode_counts.items()
        },
        "pending_question": pending_question,
        # Misconception-coverage ledger (spec sections 3.3-3.4). Must round-trip
        # because the API reloads the session from storage each request; the
        # applicable set is persisted as a sorted list for stable documents.
        "misconception_asked": dict(session.misconception_asked),
        "misconception_correct": dict(session.misconception_correct),
        "misconception_applicable": sorted(session.misconception_applicable),
        "reserve_phase_started_at": session.reserve_phase_started_at,
    }


def doc_to_session(doc: Dict[str, Any]) -> Session:
    """Convert a MongoDB document back into a Session dataclass."""
    posteriors_nested = doc.get("posteriors", {})
    posteriors = {s: float(d["posterior"]) for s, d in posteriors_nested.items()}
    direct_obs_count = {
        s: int(d.get("direct_observations", 0)) for s, d in posteriors_nested.items()
    }
    propagation_updates_count = {
        s: int(d.get("propagation_updates", 0)) for s, d in posteriors_nested.items()
    }
    pending_question = doc.get("pending_question") or {}
    return Session(
        sub_session_id=doc["identifier"],
        learner_id=doc["learner_id"],
        tenant_id=doc["tenant_id"],
        class_id=doc["class_id"],
        grade=int(doc["grade"]),
        status=SessionStatus(doc["status"]),
        started_at=doc["started_at"],
        ended_at=doc.get("ended_at"),
        engine_version=doc["engine_version"],
        posteriors=posteriors,
        direct_obs_count=direct_obs_count,
        propagation_updates_count=propagation_updates_count,
        questions_per_operation=dict(doc.get("questions_per_operation", {})),
        question_history=[
            _doc_to_history_entry(e) for e in doc.get("question_history", [])
        ],
        routing_mode_counts={
            RoutingMode(k): int(v) for k, v in doc.get("routing_mode_counts", {}).items()
        },
        tree_id_used=doc.get("tree_id_used"),
        tree_version_used=doc.get("tree_version_used"),
        pending_question_id=pending_question.get("question_id"),
        pending_question_slip_override=pending_question.get("slip_override"),
        pending_question_guess_override=pending_question.get("guess_override"),
        pending_question_skill_id=pending_question.get("skill_id"),
        pending_question_misconceptions=pending_question.get("misconceptions"),
        # Ledger; older documents predating this field deserialize to empty
        # counters / empty applicable set (the layer is inert for them).
        misconception_asked={
            k: int(v) for k, v in doc.get("misconception_asked", {}).items()
        },
        misconception_correct={
            k: int(v) for k, v in doc.get("misconception_correct", {}).items()
        },
        misconception_applicable=set(doc.get("misconception_applicable", [])),
        reserve_phase_started_at=doc.get("reserve_phase_started_at"),
    )


def _history_entry_to_doc(entry: QuestionHistoryEntry) -> Dict[str, Any]:
    return {
        "sequence": entry.sequence,
        "question_id": entry.question_id,
        "skill_id": entry.skill_id,
        "is_correct": entry.is_correct,
        "asked_at": entry.asked_at,
        "posterior_before": entry.posterior_before,
        "posterior_after": entry.posterior_after,
        "purpose": entry.purpose.value,
        "routing_mode": entry.routing_mode.value,
        "raw_response": entry.raw_response,
    }


def _doc_to_history_entry(doc: Dict[str, Any]) -> QuestionHistoryEntry:
    return QuestionHistoryEntry(
        sequence=int(doc["sequence"]),
        question_id=doc["question_id"],
        skill_id=doc["skill_id"],
        is_correct=bool(doc["is_correct"]),
        asked_at=doc["asked_at"],
        posterior_before=float(doc["posterior_before"]),
        posterior_after=float(doc["posterior_after"]),
        purpose=Purpose(doc["purpose"]),
        routing_mode=RoutingMode(doc["routing_mode"]),
        raw_response=doc.get("raw_response"),
    )


# === Verdicts ===


def verdict_to_doc(verdict: SkillVerdict, session: Session) -> Dict[str, Any]:
    """Convert a SkillVerdict into a learner_skill_verdicts row.

    Uses the session for cross-reference fields (learner_id, tenant_id, etc.).
    Generates a fresh UUID for the verdict's identifier.
    """
    return {
        "identifier": str(uuid.uuid4()),
        "learner_id": session.learner_id,
        "tenant_id": session.tenant_id,
        "class_id": session.class_id,
        "l1_skill_id": verdict.operation,
        "l2_5_skill_id": verdict.skill_id,
        "sub_session_id": session.sub_session_id,
        "posterior": verdict.posterior,
        "direct_observations": verdict.direct_observations,
        # propagation_updates joins direct_observations on the verdict
        # document per spec section 6.1. Used downstream to audit why a
        # verdict ended up confident vs uncertain (Rules 2/7 vs 3/8 in
        # spec section 7.6).
        "propagation_updates": verdict.propagation_updates,
        "confidence_label": verdict.confidence_label.value,
        "recommendation": verdict.recommendation.value,
        "engine_version": session.engine_version,
    }


def doc_to_verdict(doc: Dict[str, Any]) -> SkillVerdict:
    return SkillVerdict(
        skill_id=doc["l2_5_skill_id"],
        operation=doc.get("l1_skill_id", "") or "",
        posterior=float(doc["posterior"]),
        direct_observations=int(doc["direct_observations"]),
        # Defaults to 0 for pre-change-#6 verdict documents that lack the
        # field. New writes always include it.
        propagation_updates=int(doc.get("propagation_updates", 0)),
        confidence_label=ConfidenceLabel(doc["confidence_label"]),
        recommendation=Recommendation(doc["recommendation"]),
    )


# === Lattice edges ===


def lattice_edge_to_doc(edge: LatticeEdge) -> Dict[str, Any]:
    return {
        "identifier": str(uuid.uuid4()),
        "skill_a": edge.skill_a,
        "skill_b": edge.skill_b,
        "operation_a": edge.operation_a,
        "operation_b": edge.operation_b,
        "edge_type": (
            "within_operation"
            if edge.operation_a == edge.operation_b
            else "cross_operation"
        ),
        "p_b_given_a": edge.p_b_given_a,
        "p_b_given_not_a": edge.p_b_given_not_a,
        "weight": edge.weight,
        "is_active": True,
    }


def doc_to_lattice_edge(doc: Dict[str, Any]) -> LatticeEdge:
    return LatticeEdge(
        skill_a=doc["skill_a"],
        skill_b=doc["skill_b"],
        operation_a=doc["operation_a"],
        operation_b=doc["operation_b"],
        p_b_given_a=float(doc["p_b_given_a"]),
        p_b_given_not_a=float(doc["p_b_given_not_a"]),
        weight=float(doc["weight"]),
    )
