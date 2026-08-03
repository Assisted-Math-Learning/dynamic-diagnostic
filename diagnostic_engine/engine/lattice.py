"""
Lattice propagation for the dynamic diagnostic engine.

The lattice is a small directed graph of relationships between L2.5 skills.
After a direct observation on one skill updates that skill's posterior
(via the Bayes update in engine.bayes), the lattice lets the engine push
related skills' posteriors in the appropriate direction without spending
direct questions on them.

Propagation rules (engineering spec section 7.3):

  Forward propagation
    Trigger:  the response was correct AND posterior(source) > 0.5
    Action:   for every edge source -> target, push target's posterior up
              toward edge_propagation_value (0.90 in v1), weighted by edge
              weight.

  Backward propagation (contrapositive)
    Trigger:  the response was incorrect AND posterior(source) < 0.5
    Action:   for every edge prereq -> source, push prereq's posterior down
              toward 1 - edge_propagation_value (0.10 in v1), weighted by
              edge weight.

  Never overshoots
    A target whose current posterior is already more extreme than the
    blended target is left alone.

Pure functions, no I/O.
"""

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

# Source-side trigger threshold for both directions of propagation.
# Spec section 7.3: "posterior on A is now above 0.5" / "below 0.5".
_TRIGGER_THRESHOLD = 0.5


@dataclass(frozen=True)
class LatticeEdge:
    """A directed skill-to-skill relationship used for propagation.

    The arrow `skill_a -> skill_b` is read as "mastery of skill_a predicts
    mastery of skill_b".

    `p_b_given_a` and `p_b_given_not_a` are stored for completeness and
    audit; they describe how the edge was estimated. The propagation math
    itself uses only `weight` and the engine's `edge_propagation_value`
    parameter.
    """

    skill_a: str
    skill_b: str
    operation_a: str
    operation_b: str
    p_b_given_a: float        # P(skill_b mastered | skill_a mastered)
    p_b_given_not_a: float    # P(skill_b mastered | skill_a NOT mastered)
    weight: float             # 1.0 for multi-view (high confidence), 0.5 for single-view

    def __post_init__(self) -> None:
        if not self.skill_a or not self.skill_b:
            raise ValueError("skill_a and skill_b must be non-empty")
        if self.skill_a == self.skill_b:
            raise ValueError(f"self-loops not allowed: {self.skill_a}")
        if not 0.0 <= self.p_b_given_a <= 1.0:
            raise ValueError(f"p_b_given_a must be in [0, 1], got {self.p_b_given_a}")
        if not 0.0 <= self.p_b_given_not_a <= 1.0:
            raise ValueError(
                f"p_b_given_not_a must be in [0, 1], got {self.p_b_given_not_a}"
            )
        if not 0.0 < self.weight <= 1.0:
            raise ValueError(f"weight must be in (0, 1], got {self.weight}")


class LatticeIndex:
    """Lookup-optimised view of a list of LatticeEdges.

    Built once at engine startup from the lattice_edges MongoDB collection
    (or the in-memory seed). Read-only at request time.
    """

    def __init__(self, edges: List[LatticeEdge]):
        self._edges: Tuple[LatticeEdge, ...] = tuple(edges)
        self._out: Dict[str, List[LatticeEdge]] = {}
        self._in: Dict[str, List[LatticeEdge]] = {}
        for e in self._edges:
            self._out.setdefault(e.skill_a, []).append(e)
            self._in.setdefault(e.skill_b, []).append(e)

    @property
    def edges(self) -> Tuple[LatticeEdge, ...]:
        return self._edges

    def out_edges(self, skill: str) -> List[LatticeEdge]:
        """Edges where `skill` is the source (A in A -> B)."""
        return list(self._out.get(skill, []))

    def in_edges(self, skill: str) -> List[LatticeEdge]:
        """Edges where `skill` is the target (B in A -> B)."""
        return list(self._in.get(skill, []))

    def __len__(self) -> int:
        return len(self._edges)


def propagate(
    source_skill: str,
    is_correct: bool,
    posteriors: Mapping[str, float],
    lattice_index: LatticeIndex,
    edge_propagation_value: float,
) -> Dict[str, float]:
    """Compute lattice-propagation updates after one direct observation.

    The caller MUST have already applied the Bayes update to
    `posteriors[source_skill]` before calling this function. The trigger
    condition reads `posteriors[source_skill]` as the post-update value.

    Args:
        source_skill: the skill the question tested.
        is_correct: response Boolean (already scored upstream).
        posteriors: current per-skill posteriors, with source_skill at its
            post-Bayes-update value.
        lattice_index: pre-built edge index.
        edge_propagation_value: target value for forward propagation
            (typically 0.90); 1 - this value is used for backward.

    Returns:
        Mapping {skill: new_posterior} for every target skill whose
        posterior actually moved. Empty dict if no propagation triggered
        or no target moved.

        The source skill is never in the returned mapping.

    Raises:
        KeyError: if source_skill is not in posteriors.
        ValueError: if edge_propagation_value is outside (0.5, 1.0).
    """
    _validate_propagation_inputs(source_skill, posteriors, edge_propagation_value)

    source_posterior = posteriors[source_skill]
    updates: Dict[str, float] = {}

    if is_correct and source_posterior > _TRIGGER_THRESHOLD:
        target = edge_propagation_value
        for edge in lattice_index.out_edges(source_skill):
            new_value = _push_up(posteriors, edge.skill_b, target, edge.weight)
            if new_value is not None:
                updates[edge.skill_b] = new_value

    elif (not is_correct) and source_posterior < _TRIGGER_THRESHOLD:
        target = 1.0 - edge_propagation_value
        for edge in lattice_index.in_edges(source_skill):
            new_value = _push_down(posteriors, edge.skill_a, target, edge.weight)
            if new_value is not None:
                updates[edge.skill_a] = new_value

    return updates


# Internal helpers ------------------------------------------------------------


def _push_up(
    posteriors: Mapping[str, float],
    target_skill: str,
    target: float,
    weight: float,
) -> Optional[float]:
    """Push a target's posterior up toward `target`, weighted.

    Returns the new posterior, or None if the target is out of scope or
    already at/above the blended value (no-overshoot rule).
    """
    if target_skill not in posteriors:
        return None
    old = posteriors[target_skill]
    blended = weight * target + (1.0 - weight) * old
    new = max(old, blended)
    return new if new != old else None


def _push_down(
    posteriors: Mapping[str, float],
    target_skill: str,
    target: float,
    weight: float,
) -> Optional[float]:
    if target_skill not in posteriors:
        return None
    old = posteriors[target_skill]
    blended = weight * target + (1.0 - weight) * old
    new = min(old, blended)
    return new if new != old else None


def _validate_propagation_inputs(
    source_skill: str,
    posteriors: Mapping[str, float],
    edge_propagation_value: float,
) -> None:
    if source_skill not in posteriors:
        raise KeyError(
            f"source_skill '{source_skill}' not in posteriors; "
            "the caller must apply the Bayes update on the source before calling propagate."
        )
    if not 0.5 < edge_propagation_value < 1.0:
        raise ValueError(
            f"edge_propagation_value must be in (0.5, 1.0), got {edge_propagation_value}"
        )
