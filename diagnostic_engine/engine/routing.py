"""
Question selection (routing) for the dynamic diagnostic engine.

Implements the Option 4 online algorithm from spec section 7.5:

  1. Process operations in a per-grade order (Multiplication-first for G2-G4,
     Division-first for G5; remaining operations follow in canonical order).
  2. For each operation, ask the configured anchor first.
  3. Then loop within the operation, picking either a verification question
     (a skill whose posterior reached the extreme zone purely by propagation,
     with zero direct observations) or the unresolved skill with the highest
     information-gain score.
  4. Stop the operation block when all its skills are resolved, the per-
     operation budget is hit, or the total grade budget is hit.

Routing is a pure function over session state. It does not mutate state or
perform I/O. The session layer reads the returned QuestionChoice, asks the
question, observes the response, and updates state before the next call.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Mapping, Optional, Sequence

from engine.lattice import LatticeIndex


class Purpose(str, Enum):
    """Why a question is being asked. Recorded in question_history (spec section 6.1)."""

    ANCHOR = "anchor"
    VERIFICATION = "verification"
    INFO_GAIN = "info_gain"


@dataclass(frozen=True)
class QuestionChoice:
    """The engine's decision about what to ask next."""

    skill: str
    operation: str
    purpose: Purpose


@dataclass(frozen=True)
class RoutingConfig:
    """Routing parameters for one grade.

    Loaded from engine_config.yaml at startup; one instance per grade.
    Frozen so config can be shared across concurrent requests without copying.
    """

    operation_order: Sequence[str]
    per_operation_budget: int
    total_budget: int
    mastery_threshold: float
    not_mastered_threshold: float
    verification_high: float
    verification_low: float
    info_gain_edge_bonus: float

    def __post_init__(self) -> None:
        if self.per_operation_budget <= 0:
            raise ValueError(
                f"per_operation_budget must be > 0, got {self.per_operation_budget}"
            )
        if self.total_budget <= 0:
            raise ValueError(f"total_budget must be > 0, got {self.total_budget}")
        if self.per_operation_budget > self.total_budget:
            raise ValueError(
                f"per_operation_budget ({self.per_operation_budget}) "
                f"must be <= total_budget ({self.total_budget})"
            )
        if not 0.5 < self.mastery_threshold < 1.0:
            raise ValueError(
                f"mastery_threshold must be in (0.5, 1.0), got {self.mastery_threshold}"
            )
        if not 0.0 < self.not_mastered_threshold < 0.5:
            raise ValueError(
                f"not_mastered_threshold must be in (0, 0.5), "
                f"got {self.not_mastered_threshold}"
            )
        if not 0.5 < self.verification_high < 1.0:
            raise ValueError(
                f"verification_high must be in (0.5, 1.0), got {self.verification_high}"
            )
        if not 0.0 < self.verification_low < 0.5:
            raise ValueError(
                f"verification_low must be in (0, 0.5), got {self.verification_low}"
            )
        if self.verification_high > self.mastery_threshold:
            raise ValueError(
                f"verification_high ({self.verification_high}) must be <= "
                f"mastery_threshold ({self.mastery_threshold})"
            )
        if self.verification_low < self.not_mastered_threshold:
            raise ValueError(
                f"verification_low ({self.verification_low}) must be >= "
                f"not_mastered_threshold ({self.not_mastered_threshold})"
            )
        if self.info_gain_edge_bonus < 0.0:
            raise ValueError(
                f"info_gain_edge_bonus must be >= 0, got {self.info_gain_edge_bonus}"
            )


@dataclass
class RoutingState:
    """Aggregate view of session state needed for routing decisions.

    Routing reads from this object and never mutates it. The session layer
    maintains the underlying state and either passes a live reference or
    constructs a fresh RoutingState per call.
    """

    skills_in_scope: Sequence[str]
    skill_to_operation: Mapping[str, str]
    operation_anchors: Mapping[str, str]  # operation -> anchor skill name
    posteriors: Mapping[str, float]
    direct_obs_count: Mapping[str, int]
    questions_total: int
    questions_per_operation: Mapping[str, int] = field(default_factory=dict)


def pick_next_question(
    state: RoutingState,
    config: RoutingConfig,
    lattice_index: LatticeIndex,
) -> Optional[QuestionChoice]:
    """Pick the next question to ask in the session.

    Returns:
        A QuestionChoice if there is a question to ask.
        None if the session is complete:
            - the total grade budget has been hit, OR
            - every operation in config.operation_order is either out of
              scope for this learner or fully resolved / out of per-op budget.
    """
    # Global budget hard stop.
    if state.questions_total >= config.total_budget:
        return None

    # Walk operations in configured order; pick within the first non-complete one.
    for op in config.operation_order:
        skills_in_op = _skills_in_operation(state, op)
        if not skills_in_op:
            continue
        if _is_operation_complete(state, config, op, skills_in_op):
            continue
        return _select_within_operation(state, config, lattice_index, op, skills_in_op)

    return None


def select_leftover_skill(
    state: RoutingState,
    config: RoutingConfig,
    lattice_index: LatticeIndex,
    candidate_skills: Sequence[str],
) -> Optional[QuestionChoice]:
    """Phase 3 (leftover-to-mastery) skill pick: among the supplied still-unsure
    candidate skills, return the highest info-gain one, ignoring per-operation
    caps and the operation-walk order (info-gain-first; spec section 4.3).

    Additive: `pick_next_question` never calls this, so the online walk and the
    offline tree are byte-for-byte unchanged. The phase controller calls it only
    after Phase 1 has ended, with the set of in-scope skills still lacking a
    confident verdict. Returns None when no candidate is unresolved. Purpose is
    tagged INFO_GAIN; the operation is looked up for telemetry only.
    """
    unresolved = [
        s for s in candidate_skills
        if s in state.posteriors and not _is_resolved(state.posteriors[s], config)
    ]
    if not unresolved:
        return None
    scored = [
        (s, info_gain_score(state.posteriors[s], s, lattice_index,
                            config.info_gain_edge_bonus))
        for s in unresolved
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    chosen = scored[0][0]
    op = state.skill_to_operation.get(chosen, "")
    return QuestionChoice(skill=chosen, operation=op, purpose=Purpose.INFO_GAIN)


def info_gain_score(
    posterior: float,
    skill: str,
    lattice_index: LatticeIndex,
    edge_bonus: float,
) -> float:
    """Score function for the info-gain pick.

      score = entropy(posterior) * (1 + edge_bonus * (out_edges + in_edges))

    The entropy factor is highest at posterior = 0.5 (maximum uncertainty)
    and drops to 0 at posterior = 0 or 1. The edge multiplier boosts skills
    whose lattice connections mean a direct test will also propagate to
    other skills, making the question more informative overall.
    """
    h = _binary_entropy(posterior)
    edge_count = len(lattice_index.out_edges(skill)) + len(lattice_index.in_edges(skill))
    return h * (1.0 + edge_bonus * edge_count)


# Internal helpers ------------------------------------------------------------


def _skills_in_operation(state: RoutingState, op: str) -> List[str]:
    """Skills in scope that belong to a given operation."""
    return [s for s in state.skills_in_scope if state.skill_to_operation.get(s) == op]


def _is_resolved(posterior: float, config: RoutingConfig) -> bool:
    """A skill is 'resolved' when its posterior has crossed either threshold."""
    return (
        posterior >= config.mastery_threshold
        or posterior <= config.not_mastered_threshold
    )


def _is_operation_complete(
    state: RoutingState,
    config: RoutingConfig,
    op: str,
    skills_in_op: Sequence[str],
) -> bool:
    """An operation block is complete when either the per-op budget is exhausted
    or every skill in the operation has been resolved."""
    if state.questions_per_operation.get(op, 0) >= config.per_operation_budget:
        return True
    return all(_is_resolved(state.posteriors[s], config) for s in skills_in_op)


def _select_within_operation(
    state: RoutingState,
    config: RoutingConfig,
    lattice_index: LatticeIndex,
    op: str,
    skills_in_op: Sequence[str],
) -> Optional[QuestionChoice]:
    """Pick the next skill within an active operation.

    Order of precedence:
      1. Anchor (only on the first question in this op, and only if the
         configured anchor is in the learner's scope).
      2. Verification (an unresolved, never-directly-tested skill whose
         posterior is in the extreme zone via propagation).
      3. Info-gain (the unresolved skill with the highest entropy * edge bonus).
    """
    op_questions = state.questions_per_operation.get(op, 0)

    # 1. Anchor first (only on the very first question of this op).
    if op_questions == 0:
        anchor_skill = state.operation_anchors.get(op)
        if anchor_skill is not None and anchor_skill in skills_in_op:
            return QuestionChoice(skill=anchor_skill, operation=op, purpose=Purpose.ANCHOR)
        # else: anchor not in scope; fall through to within-op picking. The
        # first within-op question implicitly anchors the op (the next call
        # will see op_questions >= 1 and skip this branch).

    # Unresolved skills only (resolved ones never get asked again in this op).
    unresolved = [s for s in skills_in_op if not _is_resolved(state.posteriors[s], config)]
    if not unresolved:
        # _is_operation_complete should have caught this; defensive return.
        return None

    # 2. Verification trigger: extreme posterior, zero direct observations.
    verification_candidates = [
        s for s in unresolved
        if state.direct_obs_count.get(s, 0) == 0
        and (
            state.posteriors[s] >= config.verification_high
            or state.posteriors[s] <= config.verification_low
        )
    ]
    if verification_candidates:
        skill = sorted(verification_candidates)[0]  # deterministic tiebreaker
        return QuestionChoice(skill=skill, operation=op, purpose=Purpose.VERIFICATION)

    # 3. Info-gain pick: highest score, alphabetical tiebreaker on skill name.
    scored = [
        (s, info_gain_score(state.posteriors[s], s, lattice_index, config.info_gain_edge_bonus))
        for s in unresolved
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return QuestionChoice(skill=scored[0][0], operation=op, purpose=Purpose.INFO_GAIN)


def _binary_entropy(p: float) -> float:
    """Shannon entropy of a binary distribution in bits.

    H(0) = H(1) = 0, H(0.5) = 1.0. Defined here in plain Python rather than
    NumPy so the engine has one fewer dependency.
    """
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))
