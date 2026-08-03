"""Misconception-coverage phase controller (misconception_coverage_selection_spec
sections 4-5).

This is the orchestration that sequences the three phases on top of the existing
adaptive engine. It is a pure function of the current session state (it reads the
ledger, the posteriors, and the question history) with ONE persisted side effect:
it sets `session.reserve_phase_started_at` the first time Phase 1 ends, which
fixes the reserve baseline (forfeiting any unspent adaptive budget) and stops
Phase 1 from resuming if a later backfill answer un-resolves a skill.

It returns the next question to ask as a `(skill_id, QuestionPick)` pair -
uniform across phases so the response path can stash and serve it the same way -
or None when the session is complete. It does NOT mutate posteriors, finalize
verdicts, or set session status; the caller (the route) applies the answer before
calling this and finalizes when this returns None.

`reserve_size == 0` makes the controller inert: Phase 1 runs the full grade
budget and the reserve phases never start, so behaviour matches the pre-coverage
engine exactly.
"""

from __future__ import annotations

import dataclasses
from typing import Iterable, List, Optional, Set, Tuple

from engine.routing import (
    QuestionChoice,
    RoutingState,
    pick_next_question,
    select_leftover_skill,
)
from engine.session import EngineParams, Session
from engine.question_pool import QuestionPick
from engine.misconception import wants_misconception_extra

# (skill_id, resolved pick) - the uniform "next question" shape across phases.
NextQuestion = Tuple[str, QuestionPick]


def _routing_state(session: Session, params: EngineParams) -> RoutingState:
    return RoutingState(
        skills_in_scope=params.skills_in_scope,
        skill_to_operation=params.skill_to_operation,
        operation_anchors=params.operation_anchors,
        posteriors=session.posteriors,
        direct_obs_count=session.direct_obs_count,
        questions_total=session.questions_total,
        questions_per_operation=session.questions_per_operation,
    )


def _is_resolved(posterior: float, params: EngineParams) -> bool:
    return (
        posterior >= params.mastery_threshold
        or posterior <= params.not_mastered_threshold
    )


def _resolve_choice(
    choice: QuestionChoice, session: Session, params: EngineParams, pool
) -> Optional[NextQuestion]:
    """Resolve a routing skill choice to a concrete (skill, pick), or None if the
    skill's questions are exhausted (no-repeat empties it)."""
    from engine.api.errors import NoQuestionForSkillError
    try:
        pick = pool.pick_question_for_skill(
            skill=choice.skill, session=session, grade=params.grade,
            tenant_id=session.tenant_id,
        )
    except NoQuestionForSkillError:
        return None
    return choice.skill, pick


def select_next_coverage(
    session: Session, params: EngineParams, pool, *, trace: Optional[List[str]] = None,
) -> Optional[NextQuestion]:
    """Return the next (skill, pick) to ask across Phases 1-3, or None if done.

    Call AFTER the just-received answer has been applied to the session, so the
    ledger and posteriors are current.

    `trace` is an optional, opt-in instrumentation hook (off in production): when
    a list is passed, the phase that produced the returned pick is appended -
    "phase1", "phase2a", "phase2b", "phase3", or "done". It is used by the
    trade-off simulation to detect Phase-3 entry; it never affects selection.
    """
    def _tag(label: str) -> None:
        if trace is not None:
            trace.append(label)

    state = _routing_state(session, params)

    # --- Phase 1: adaptive, under the lowered total stop -------------------
    if session.reserve_phase_started_at is None and params.adaptive_budget > 0:
        # Lower the total stop to adaptive_budget. A per-operation cap can never
        # exceed the (lowered) total, so clamp it to keep the RoutingConfig
        # invariant; this does not change behaviour because the total stop bites
        # first whenever per_op would have exceeded it.
        phase1_total = params.adaptive_budget
        phase1_config = dataclasses.replace(
            params.routing_config,
            total_budget=phase1_total,
            per_operation_budget=min(
                params.routing_config.per_operation_budget, phase1_total
            ),
        )
        choice = pick_next_question(state, phase1_config, params.lattice_index)
        if choice is not None:
            resolved = _resolve_choice(choice, session, params, pool)
            if resolved is not None:
                _tag("phase1")
                return resolved
            # The chosen skill is exhausted; treat Phase 1 as ended and let the
            # reserve phases (which skip exhausted skills) take over.
        # Phase 1 has ended: fix the reserve baseline (forfeit point).
        session.reserve_phase_started_at = session.questions_total
    elif session.reserve_phase_started_at is None:
        # Degenerate config (reserve >= total): no adaptive phase at all.
        session.reserve_phase_started_at = session.questions_total

    # --- reserve accounting (Phases 2 & 3 draw from reserve_size) ----------
    reserve_consumed = session.questions_total - session.reserve_phase_started_at
    if reserve_consumed >= params.reserve_size:
        _tag("done")
        return None  # reserve spent; any still-unmet misconceptions are shortfall

    # --- Phase 2: backfill -------------------------------------------------
    applicable = session.misconception_applicable
    target = pool.misconception_target
    asked = session.misconception_asked
    correct = session.misconception_correct

    def _backfill(needed: Set[str]) -> Optional[NextQuestion]:
        if not needed:
            return None
        return pool.backfill_pick(
            tenant_id=session.tenant_id, grade=params.grade,
            skills_in_scope=params.skills_in_scope, session=session, needed=needed,
        )

    # Pass A: bring each applicable misconception up to the floor.
    needed_a = {m for m in applicable if asked.get(m, 0) < target}
    res = _backfill(needed_a)
    if res is not None:
        _tag("phase2a")
        return res

    # Pass B (v7): the reachability-gated extra. Once a misconception is at/above
    # the floor, ask one more tagged question iff it is not yet cleared and 75% is
    # still reachable within the cap (= target + x). Spends extras only on the
    # "bubble" learner; clear passers and clear failers get none. The gate is the
    # shared `wants_misconception_extra`, re-evaluated every call, so the
    # ask/re-check loop falls out of the per-question call structure.
    extra = params.misconception_conditional_extra
    needed_b = {
        m for m in applicable
        if asked.get(m, 0) >= target
        and wants_misconception_extra(
            asked.get(m, 0), correct.get(m, 0), target=target, extra=extra,
            clear_threshold=params.misconception_clear_threshold,
        )
    }
    res = _backfill(needed_b)
    if res is not None:
        _tag("phase2b")
        return res

    # --- Phase 3: leftover-to-mastery (info-gain among unsure, caps lifted) -
    unsure = [
        s for s in params.skills_in_scope
        if not _is_resolved(session.posteriors[s], params)
    ]
    while unsure:
        choice = select_leftover_skill(
            state, params.routing_config, params.lattice_index, unsure
        )
        if choice is None:
            break
        resolved = _resolve_choice(choice, session, params, pool)
        if resolved is not None:
            _tag("phase3")
            return resolved
        # That skill's questions are exhausted; drop it and try the next.
        unsure = [s for s in unsure if s != choice.skill]

    _tag("done")
    return None  # nothing left to ask; session complete
