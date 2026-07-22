"""Unit tests for engine.lattice."""

import math
from dataclasses import FrozenInstanceError

import pytest

from engine.lattice import LatticeEdge, LatticeIndex, propagate

# Edge propagation value from spec section 7.7
EPV = 0.90


def make_edge(
    skill_a: str,
    skill_b: str,
    *,
    operation_a: str = "Addition",
    operation_b: str = "Subtraction",
    weight: float = 1.0,
    p_b_given_a: float = 0.9,
    p_b_given_not_a: float = 0.3,
) -> LatticeEdge:
    """Test helper for building LatticeEdge with sensible defaults."""
    return LatticeEdge(
        skill_a=skill_a,
        skill_b=skill_b,
        operation_a=operation_a,
        operation_b=operation_b,
        p_b_given_a=p_b_given_a,
        p_b_given_not_a=p_b_given_not_a,
        weight=weight,
    )


# LatticeEdge ------------------------------------------------------------------


class TestLatticeEdgeConstruction:
    def test_valid_edge_constructs(self):
        edge = make_edge("A", "B")
        assert edge.skill_a == "A"
        assert edge.skill_b == "B"
        assert edge.weight == 1.0

    def test_edge_is_frozen(self):
        edge = make_edge("A", "B")
        with pytest.raises(FrozenInstanceError):
            edge.skill_a = "X"  # type: ignore[misc]

    def test_empty_skill_a_raises(self):
        with pytest.raises(ValueError):
            make_edge("", "B")

    def test_empty_skill_b_raises(self):
        with pytest.raises(ValueError):
            make_edge("A", "")

    def test_self_loop_raises(self):
        with pytest.raises(ValueError, match="self-loops"):
            make_edge("A", "A")

    def test_p_b_given_a_above_one_raises(self):
        with pytest.raises(ValueError, match="p_b_given_a"):
            make_edge("A", "B", p_b_given_a=1.5)

    def test_p_b_given_a_negative_raises(self):
        with pytest.raises(ValueError, match="p_b_given_a"):
            make_edge("A", "B", p_b_given_a=-0.1)

    def test_p_b_given_not_a_above_one_raises(self):
        with pytest.raises(ValueError, match="p_b_given_not_a"):
            make_edge("A", "B", p_b_given_not_a=1.5)

    def test_weight_zero_raises(self):
        with pytest.raises(ValueError, match="weight"):
            make_edge("A", "B", weight=0.0)

    def test_weight_above_one_raises(self):
        with pytest.raises(ValueError, match="weight"):
            make_edge("A", "B", weight=1.5)

    def test_weight_at_one_allowed(self):
        # Boundary value: weight = 1.0 is valid (multi-view edge)
        edge = make_edge("A", "B", weight=1.0)
        assert edge.weight == 1.0


# LatticeIndex -----------------------------------------------------------------


class TestLatticeIndex:
    def test_empty_index(self):
        idx = LatticeIndex([])
        assert idx.edges == ()
        assert idx.out_edges("A") == []
        assert idx.in_edges("B") == []
        assert len(idx) == 0

    def test_single_edge_lookups(self):
        edge = make_edge("A", "B")
        idx = LatticeIndex([edge])
        assert idx.out_edges("A") == [edge]
        assert idx.in_edges("B") == [edge]
        assert idx.out_edges("B") == []
        assert idx.in_edges("A") == []
        assert len(idx) == 1

    def test_multiple_edges_same_source(self):
        e1 = make_edge("A", "B")
        e2 = make_edge("A", "C")
        idx = LatticeIndex([e1, e2])
        outs = idx.out_edges("A")
        assert len(outs) == 2
        assert e1 in outs and e2 in outs

    def test_multiple_edges_same_target(self):
        e1 = make_edge("A", "C")
        e2 = make_edge("B", "C")
        idx = LatticeIndex([e1, e2])
        ins = idx.in_edges("C")
        assert len(ins) == 2
        assert e1 in ins and e2 in ins

    def test_out_edges_returns_a_copy(self):
        # External mutation should not affect the index's internal state.
        edge = make_edge("A", "B")
        idx = LatticeIndex([edge])
        outs = idx.out_edges("A")
        outs.append(make_edge("X", "Y"))
        assert len(idx.out_edges("A")) == 1


# Forward propagation ----------------------------------------------------------


class TestPropagateForward:
    """Correct response with posterior > 0.5: push targets of A -> B up."""

    def test_weight_one_pushes_to_target_exactly(self):
        idx = LatticeIndex([make_edge("A", "B", weight=1.0)])
        posteriors = {"A": 0.8, "B": 0.4}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        # weight=1.0: blended = 1.0 * 0.9 + 0 * 0.4 = 0.9
        assert updates == {"B": 0.9}

    def test_weight_half_pushes_midway(self):
        idx = LatticeIndex([make_edge("A", "B", weight=0.5)])
        posteriors = {"A": 0.8, "B": 0.4}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        # weight=0.5: blended = 0.5 * 0.9 + 0.5 * 0.4 = 0.65
        assert math.isclose(updates["B"], 0.65, rel_tol=1e-12)

    def test_no_fire_when_posterior_at_threshold(self):
        # posterior(A) == 0.5 exactly: trigger uses strict > 0.5, so no fire.
        idx = LatticeIndex([make_edge("A", "B")])
        posteriors = {"A": 0.5, "B": 0.4}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_no_fire_when_correct_but_posterior_still_low(self):
        # E.g., very low prior, one correct answer not enough to cross 0.5.
        idx = LatticeIndex([make_edge("A", "B")])
        posteriors = {"A": 0.3, "B": 0.4}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_no_overshoot_when_target_already_higher(self):
        # B's posterior already 0.95 > target 0.9. Leave alone.
        idx = LatticeIndex([make_edge("A", "B", weight=1.0)])
        posteriors = {"A": 0.8, "B": 0.95}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_no_overshoot_with_partial_weight(self):
        # weight=0.5, B=0.95, target=0.9 -> blended=0.5*0.9 + 0.5*0.95=0.925 < 0.95
        # max(0.95, 0.925) = 0.95, no change.
        idx = LatticeIndex([make_edge("A", "B", weight=0.5)])
        posteriors = {"A": 0.8, "B": 0.95}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_target_outside_scope_skipped(self):
        idx = LatticeIndex([make_edge("A", "B"), make_edge("A", "C")])
        posteriors = {"A": 0.8, "B": 0.4}  # C is not in this learner's scope
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {"B": 0.9}
        assert "C" not in updates

    def test_multiple_outgoing_edges_all_fire(self):
        idx = LatticeIndex([
            make_edge("A", "B", weight=1.0),
            make_edge("A", "C", weight=1.0),
        ])
        posteriors = {"A": 0.8, "B": 0.4, "C": 0.3}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {"B": 0.9, "C": 0.9}


# Backward propagation ---------------------------------------------------------


class TestPropagateBackward:
    """Incorrect response with posterior < 0.5: push prereqs W -> A down."""

    def test_weight_one_pushes_to_target_exactly(self):
        idx = LatticeIndex([make_edge("W", "A", weight=1.0)])
        posteriors = {"A": 0.2, "W": 0.6}
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        # target = 1 - 0.9 ~= 0.1 (IEEE 754 makes it 0.09999...; use isclose)
        assert set(updates) == {"W"}
        assert math.isclose(updates["W"], 0.1, rel_tol=1e-12)

    def test_weight_half_pushes_midway(self):
        idx = LatticeIndex([make_edge("W", "A", weight=0.5)])
        posteriors = {"A": 0.2, "W": 0.6}
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        # blended = 0.5 * 0.1 + 0.5 * 0.6 = 0.35
        assert math.isclose(updates["W"], 0.35, rel_tol=1e-12)

    def test_no_fire_when_posterior_at_threshold(self):
        idx = LatticeIndex([make_edge("W", "A")])
        posteriors = {"A": 0.5, "W": 0.6}
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_no_fire_when_incorrect_but_posterior_still_high(self):
        # One incorrect answer not enough to push posterior below 0.5.
        idx = LatticeIndex([make_edge("W", "A")])
        posteriors = {"A": 0.7, "W": 0.6}
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_no_overshoot_when_target_already_lower(self):
        idx = LatticeIndex([make_edge("W", "A", weight=1.0)])
        posteriors = {"A": 0.2, "W": 0.05}  # W already below 0.1 target
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_multiple_incoming_edges_all_fire(self):
        idx = LatticeIndex([
            make_edge("W1", "A", weight=1.0),
            make_edge("W2", "A", weight=1.0),
        ])
        posteriors = {"A": 0.2, "W1": 0.6, "W2": 0.7}
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert set(updates) == {"W1", "W2"}
        assert math.isclose(updates["W1"], 0.1, rel_tol=1e-12)
        assert math.isclose(updates["W2"], 0.1, rel_tol=1e-12)


# Direction-cross-talk and edge cases -----------------------------------------


class TestPropagateMixed:
    def test_correct_does_not_propagate_backward(self):
        # W -> A edge exists, but trigger is is_correct=True; no fire.
        idx = LatticeIndex([make_edge("W", "A")])
        posteriors = {"A": 0.8, "W": 0.6}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_incorrect_does_not_propagate_forward(self):
        idx = LatticeIndex([make_edge("A", "B")])
        posteriors = {"A": 0.2, "B": 0.4}
        updates = propagate(
            "A", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_source_skill_never_in_updates(self):
        # If a self-loop somehow existed, it should not appear in updates.
        # (LatticeEdge prevents construction; this checks the consumer.)
        idx = LatticeIndex([make_edge("A", "B")])
        posteriors = {"A": 0.8, "B": 0.4}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert "A" not in updates

    def test_empty_lattice_no_updates(self):
        idx = LatticeIndex([])
        posteriors = {"A": 0.8}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {}

    def test_forward_and_backward_edges_coexist(self):
        # A has both an outgoing edge (A -> X) and an incoming edge (W -> A).
        # Correct response: only forward should fire.
        idx = LatticeIndex([make_edge("A", "X"), make_edge("W", "A")])
        posteriors = {"A": 0.8, "X": 0.4, "W": 0.6}
        updates = propagate(
            "A", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert "X" in updates
        assert "W" not in updates


# Input validation -------------------------------------------------------------


class TestPropagateValidation:
    def test_missing_source_raises(self):
        idx = LatticeIndex([])
        with pytest.raises(KeyError, match="source_skill"):
            propagate(
                "missing", is_correct=True, posteriors={"A": 0.5},
                lattice_index=idx, edge_propagation_value=EPV,
            )

    def test_epv_above_one_raises(self):
        idx = LatticeIndex([])
        with pytest.raises(ValueError, match="edge_propagation_value"):
            propagate(
                "A", is_correct=True, posteriors={"A": 0.8},
                lattice_index=idx, edge_propagation_value=1.5,
            )

    def test_epv_at_half_raises(self):
        # 0.5 is not informative: pushing toward 0.5 is not propagation.
        idx = LatticeIndex([])
        with pytest.raises(ValueError, match="edge_propagation_value"):
            propagate(
                "A", is_correct=True, posteriors={"A": 0.8},
                lattice_index=idx, edge_propagation_value=0.5,
            )

    def test_epv_at_one_raises(self):
        # 1.0 is impossible (would imply certain mastery from propagation).
        idx = LatticeIndex([])
        with pytest.raises(ValueError, match="edge_propagation_value"):
            propagate(
                "A", is_correct=True, posteriors={"A": 0.8},
                lattice_index=idx, edge_propagation_value=1.0,
            )


# Realistic chains (anchored to real skills from the v1 lattice) ---------------


class TestRealisticChains:
    """Two-skill scenarios matching real edges from lattice_edges_final.xlsx.

    Real lattice convention: arrow points from the harder skill to the easier
    skill. The edge `2D x 1D -> Tables 1 to 9` reads "mastery of 2D x 1D
    predicts mastery of Tables 1 to 9", which is the natural prerequisite
    direction.
    """

    def test_forward_within_multiplication(self):
        # Got 2D x 1D right -> they almost certainly know their tables.
        idx = LatticeIndex([
            make_edge(
                "2D x 1D", "Tables 1 to 9",
                operation_a="Multiplication", operation_b="Multiplication",
                weight=1.0,
            )
        ])
        posteriors = {"2D x 1D": 0.95, "Tables 1 to 9": 0.4}
        updates = propagate(
            "2D x 1D", is_correct=True, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert updates == {"Tables 1 to 9": 0.9}

    def test_backward_within_multiplication(self):
        # Got Tables 1 to 9 wrong -> they almost certainly cannot do 2D x 1D.
        idx = LatticeIndex([
            make_edge(
                "2D x 1D", "Tables 1 to 9",
                operation_a="Multiplication", operation_b="Multiplication",
                weight=1.0,
            )
        ])
        posteriors = {"2D x 1D": 0.6, "Tables 1 to 9": 0.05}
        updates = propagate(
            "Tables 1 to 9", is_correct=False, posteriors=posteriors,
            lattice_index=idx, edge_propagation_value=EPV,
        )
        assert set(updates) == {"2D x 1D"}
        assert math.isclose(updates["2D x 1D"], 0.1, rel_tol=1e-12)
