"""Unit tests for engine.routing."""

import math
from typing import Mapping, Sequence

import pytest

from engine.lattice import LatticeEdge, LatticeIndex
from engine.routing import (
    Purpose,
    QuestionChoice,
    RoutingConfig,
    RoutingState,
    info_gain_score,
    pick_next_question,
)


# Fixtures / helpers ----------------------------------------------------------


def make_config(
    operation_order: Sequence[str] = ("Multiplication", "Addition", "Subtraction", "Division"),
    per_operation_budget: int = 9,
    total_budget: int = 42,
    mastery_threshold: float = 0.95,
    not_mastered_threshold: float = 0.10,
    verification_high: float = 0.85,
    verification_low: float = 0.15,
    info_gain_edge_bonus: float = 0.5,
) -> RoutingConfig:
    return RoutingConfig(
        operation_order=list(operation_order),
        per_operation_budget=per_operation_budget,
        total_budget=total_budget,
        mastery_threshold=mastery_threshold,
        not_mastered_threshold=not_mastered_threshold,
        verification_high=verification_high,
        verification_low=verification_low,
        info_gain_edge_bonus=info_gain_edge_bonus,
    )


def make_state(
    skills_in_scope: Sequence[str],
    skill_to_operation: Mapping[str, str],
    operation_anchors: Mapping[str, str],
    posteriors: Mapping[str, float] = None,
    direct_obs_count: Mapping[str, int] = None,
    questions_total: int = 0,
    questions_per_operation: Mapping[str, int] = None,
) -> RoutingState:
    posteriors = dict(posteriors) if posteriors is not None else {s: 0.5 for s in skills_in_scope}
    direct_obs_count = (
        dict(direct_obs_count) if direct_obs_count is not None
        else {s: 0 for s in skills_in_scope}
    )
    questions_per_operation = dict(questions_per_operation) if questions_per_operation else {}
    return RoutingState(
        skills_in_scope=list(skills_in_scope),
        skill_to_operation=dict(skill_to_operation),
        operation_anchors=dict(operation_anchors),
        posteriors=posteriors,
        direct_obs_count=direct_obs_count,
        questions_total=questions_total,
        questions_per_operation=questions_per_operation,
    )


def empty_lattice() -> LatticeIndex:
    return LatticeIndex([])


def make_edge(a: str, b: str, weight: float = 1.0) -> LatticeEdge:
    return LatticeEdge(
        skill_a=a, skill_b=b,
        operation_a="Op", operation_b="Op",
        p_b_given_a=0.9, p_b_given_not_a=0.3, weight=weight,
    )


# RoutingConfig validation ----------------------------------------------------


class TestRoutingConfigValidation:
    def test_valid_config_constructs(self):
        c = make_config()
        assert c.total_budget == 42
        assert c.operation_order[0] == "Multiplication"

    def test_per_op_budget_zero_raises(self):
        with pytest.raises(ValueError, match="per_operation_budget"):
            make_config(per_operation_budget=0)

    def test_total_budget_zero_raises(self):
        with pytest.raises(ValueError, match="total_budget"):
            make_config(total_budget=0)

    def test_per_op_above_total_raises(self):
        with pytest.raises(ValueError, match="per_operation_budget"):
            make_config(per_operation_budget=50, total_budget=10)

    def test_mastery_threshold_below_half_raises(self):
        with pytest.raises(ValueError, match="mastery_threshold"):
            make_config(mastery_threshold=0.4)

    def test_not_mastered_threshold_at_half_raises(self):
        with pytest.raises(ValueError, match="not_mastered_threshold"):
            make_config(not_mastered_threshold=0.5)

    def test_verification_high_above_mastery_raises(self):
        with pytest.raises(ValueError, match="verification_high"):
            make_config(verification_high=0.96, mastery_threshold=0.95)

    def test_verification_low_below_not_mastered_raises(self):
        with pytest.raises(ValueError, match="verification_low"):
            make_config(verification_low=0.05, not_mastered_threshold=0.10)

    def test_negative_edge_bonus_raises(self):
        with pytest.raises(ValueError, match="info_gain_edge_bonus"):
            make_config(info_gain_edge_bonus=-0.1)

    def test_zero_edge_bonus_allowed(self):
        # Setting edge bonus to 0 effectively disables the bonus; allowed.
        c = make_config(info_gain_edge_bonus=0.0)
        assert c.info_gain_edge_bonus == 0.0


# info_gain_score -------------------------------------------------------------


class TestInfoGainScore:
    def test_no_edges_score_equals_entropy(self):
        # H(0.5) = 1.0; with no edges, score = 1.0 * (1 + 0.5 * 0) = 1.0
        assert math.isclose(
            info_gain_score(0.5, "X", empty_lattice(), edge_bonus=0.5),
            1.0, rel_tol=1e-12,
        )

    def test_extreme_posterior_zero_entropy(self):
        assert info_gain_score(0.0, "X", empty_lattice(), edge_bonus=0.5) == 0.0
        assert info_gain_score(1.0, "X", empty_lattice(), edge_bonus=0.5) == 0.0

    def test_one_edge_multiplies_entropy(self):
        # One out-edge, no in-edges: bonus factor = 1 + 0.5 * 1 = 1.5
        idx = LatticeIndex([make_edge("X", "Y")])
        score = info_gain_score(0.5, "X", idx, edge_bonus=0.5)
        assert math.isclose(score, 1.5, rel_tol=1e-12)

    def test_in_and_out_edges_both_counted(self):
        # X has 1 out (X -> Y) and 1 in (Z -> X): total 2 edges.
        # Bonus factor = 1 + 0.5 * 2 = 2.0
        idx = LatticeIndex([make_edge("X", "Y"), make_edge("Z", "X")])
        score = info_gain_score(0.5, "X", idx, edge_bonus=0.5)
        assert math.isclose(score, 2.0, rel_tol=1e-12)

    def test_higher_entropy_higher_score(self):
        idx = empty_lattice()
        assert (
            info_gain_score(0.5, "X", idx, edge_bonus=0.5)
            > info_gain_score(0.9, "X", idx, edge_bonus=0.5)
        )

    def test_more_edges_higher_score_at_equal_entropy(self):
        idx_none = LatticeIndex([])
        idx_two = LatticeIndex([make_edge("X", "A"), make_edge("X", "B")])
        s_none = info_gain_score(0.5, "X", idx_none, edge_bonus=0.5)
        s_two = info_gain_score(0.5, "X", idx_two, edge_bonus=0.5)
        assert s_two > s_none

    def test_edge_bonus_zero_disables_lattice_effect(self):
        # With edge_bonus = 0, score is just entropy regardless of edges.
        idx_two = LatticeIndex([make_edge("X", "A"), make_edge("X", "B")])
        s = info_gain_score(0.5, "X", idx_two, edge_bonus=0.0)
        assert math.isclose(s, 1.0, rel_tol=1e-12)


# Anchor-first ----------------------------------------------------------------


class TestAnchorFirst:
    def test_first_question_is_anchor(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice is not None
        assert choice.skill == "A1"
        assert choice.purpose == Purpose.ANCHOR
        assert choice.operation == "Addition"

    def test_anchor_not_asked_after_first_op_question(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.85, "A2": 0.5},
            direct_obs_count={"A1": 1, "A2": 0},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice is not None
        assert choice.purpose != Purpose.ANCHOR

    def test_anchor_not_in_scope_falls_through_to_info_gain(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A99_NOT_IN_SCOPE"},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice is not None
        assert choice.purpose != Purpose.ANCHOR
        assert choice.skill in ("A1", "A2")


# Verification trigger --------------------------------------------------------


class TestVerificationTrigger:
    def test_high_zone_zero_direct_obs_triggers_verification(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.5, "A2": 0.88},
            direct_obs_count={"A1": 1, "A2": 0},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.skill == "A2"
        assert choice.purpose == Purpose.VERIFICATION

    def test_low_zone_zero_direct_obs_triggers_verification(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.5, "A2": 0.12},
            direct_obs_count={"A1": 1, "A2": 0},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.skill == "A2"
        assert choice.purpose == Purpose.VERIFICATION

    def test_extreme_zone_with_direct_obs_does_not_trigger(self):
        # Direct obs already exists; verification not triggered.
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.5, "A2": 0.88},
            direct_obs_count={"A1": 1, "A2": 1},
            questions_per_operation={"Addition": 2},
            questions_total=2,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.purpose != Purpose.VERIFICATION

    def test_resolved_skill_not_a_verification_candidate(self):
        # Posterior 0.97 is resolved; not eligible for verification.
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.5, "A2": 0.97},
            direct_obs_count={"A1": 1, "A2": 0},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.skill == "A1"
        assert choice.purpose != Purpose.VERIFICATION

    def test_multiple_verification_candidates_alphabetical(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A_z", "A_a", "A_anchor"],
            skill_to_operation={s: "Addition" for s in ["A_z", "A_a", "A_anchor"]},
            operation_anchors={"Addition": "A_anchor"},
            posteriors={"A_anchor": 0.5, "A_z": 0.88, "A_a": 0.88},
            direct_obs_count={"A_anchor": 1, "A_z": 0, "A_a": 0},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        choice = pick_next_question(state, config, empty_lattice())
        # Both A_z and A_a are verification candidates; A_a wins alphabetical tiebreak
        assert choice.skill == "A_a"
        assert choice.purpose == Purpose.VERIFICATION


# Info-gain picking ----------------------------------------------------------


class TestInfoGainPicking:
    def test_highest_entropy_picked(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "X_NOT_IN_SCOPE"},
            posteriors={"A1": 0.5, "A2": 0.8},
            direct_obs_count={"A1": 1, "A2": 1},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.skill == "A1"
        assert choice.purpose == Purpose.INFO_GAIN

    def test_alphabetical_tiebreak_on_equal_score(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["zebra", "alpha"],
            skill_to_operation={"zebra": "Addition", "alpha": "Addition"},
            operation_anchors={"Addition": "X_NOT_IN_SCOPE"},
            posteriors={"zebra": 0.5, "alpha": 0.5},
            direct_obs_count={"zebra": 1, "alpha": 1},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.skill == "alpha"

    def test_edge_bonus_promotes_lattice_connected_skill(self):
        # Both skills have identical posterior; A1 has lattice edges, A2 does not.
        idx = LatticeIndex([
            make_edge("A1", "downstream"),
            make_edge("upstream", "A1"),
        ])
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "X_NOT_IN_SCOPE"},
            posteriors={"A1": 0.5, "A2": 0.5},
            direct_obs_count={"A1": 1, "A2": 1},
        )
        choice = pick_next_question(state, config, idx)
        assert choice.skill == "A1"

    def test_info_gain_never_picks_resolved_skill(self):
        # A1 unresolved (low entropy), A2 resolved (>= 0.95). A1 wins.
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "X_NOT_IN_SCOPE"},
            posteriors={"A1": 0.85, "A2": 0.99},  # A2 resolved
            direct_obs_count={"A1": 1, "A2": 1},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.skill == "A1"


# Budget enforcement ---------------------------------------------------------


class TestBudgetEnforcement:
    def test_total_budget_exhausted_returns_none(self):
        config = make_config(
            operation_order=["Addition"], per_operation_budget=3, total_budget=5
        )
        state = make_state(
            skills_in_scope=["A1"],
            skill_to_operation={"A1": "Addition"},
            operation_anchors={"Addition": "A1"},
            questions_total=5,
        )
        assert pick_next_question(state, config, empty_lattice()) is None

    def test_per_op_budget_advances_to_next_op(self):
        config = make_config(
            operation_order=["Addition", "Subtraction"],
            per_operation_budget=2,
            total_budget=10,
        )
        state = make_state(
            skills_in_scope=["A1", "S1"],
            skill_to_operation={"A1": "Addition", "S1": "Subtraction"},
            operation_anchors={"Addition": "A1", "Subtraction": "S1"},
            posteriors={"A1": 0.5, "S1": 0.5},
            direct_obs_count={"A1": 2, "S1": 0},
            questions_per_operation={"Addition": 2},
            questions_total=2,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice is not None
        assert choice.operation == "Subtraction"
        assert choice.purpose == Purpose.ANCHOR  # first question of Subtraction
        assert choice.skill == "S1"

    def test_all_ops_complete_returns_none(self):
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1"],
            skill_to_operation={"A1": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.99},  # resolved
            direct_obs_count={"A1": 1},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        assert pick_next_question(state, config, empty_lattice()) is None


# Operation order ------------------------------------------------------------


class TestOperationOrder:
    def test_first_op_in_order_is_chosen(self):
        config = make_config(
            operation_order=["Multiplication", "Addition", "Subtraction", "Division"]
        )
        state = make_state(
            skills_in_scope=["A1", "M1", "S1", "D1"],
            skill_to_operation={
                "A1": "Addition", "M1": "Multiplication",
                "S1": "Subtraction", "D1": "Division",
            },
            operation_anchors={
                "Addition": "A1", "Multiplication": "M1",
                "Subtraction": "S1", "Division": "D1",
            },
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.operation == "Multiplication"
        assert choice.skill == "M1"
        assert choice.purpose == Purpose.ANCHOR

    def test_op_with_no_skills_in_scope_is_skipped(self):
        # Operation order lists Multiplication first, but learner has no Mult skills.
        config = make_config(operation_order=["Multiplication", "Addition"])
        state = make_state(
            skills_in_scope=["A1"],
            skill_to_operation={"A1": "Addition"},
            operation_anchors={"Multiplication": "X", "Addition": "A1"},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.operation == "Addition"

    def test_g5_division_first(self):
        config = make_config(
            operation_order=["Division", "Addition", "Subtraction", "Multiplication"]
        )
        state = make_state(
            skills_in_scope=["A1", "D1"],
            skill_to_operation={"A1": "Addition", "D1": "Division"},
            operation_anchors={"Addition": "A1", "Division": "D1"},
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.operation == "Division"

    def test_completed_op_does_not_block_later_ops(self):
        # Addition done; pick next op.
        config = make_config(operation_order=["Addition", "Subtraction"])
        state = make_state(
            skills_in_scope=["A1", "S1"],
            skill_to_operation={"A1": "Addition", "S1": "Subtraction"},
            operation_anchors={"Addition": "A1", "Subtraction": "S1"},
            posteriors={"A1": 0.99, "S1": 0.5},
            direct_obs_count={"A1": 1, "S1": 0},
            questions_per_operation={"Addition": 1},
            questions_total=1,
        )
        choice = pick_next_question(state, config, empty_lattice())
        assert choice.operation == "Subtraction"
        assert choice.purpose == Purpose.ANCHOR


# Empty and degenerate cases -------------------------------------------------


class TestEmptyAndEdgeCases:
    def test_empty_scope_returns_none(self):
        config = make_config()
        state = make_state(
            skills_in_scope=[],
            skill_to_operation={},
            operation_anchors={},
        )
        assert pick_next_question(state, config, empty_lattice()) is None

    def test_all_skills_resolved_at_start_returns_none(self):
        # A learner whose priors are extreme enough to be resolved without any test.
        config = make_config(operation_order=["Addition"])
        state = make_state(
            skills_in_scope=["A1", "A2"],
            skill_to_operation={"A1": "Addition", "A2": "Addition"},
            operation_anchors={"Addition": "A1"},
            posteriors={"A1": 0.99, "A2": 0.05},
            direct_obs_count={"A1": 0, "A2": 0},  # never tested but already 'resolved'
        )
        # Note: the operation is complete (all skills resolved), so routing returns None.
        # The verdict layer will apply the downgrade rule for these (direct_obs == 0).
        assert pick_next_question(state, config, empty_lattice()) is None


# End-to-end-flavour walkthrough ---------------------------------------------


class TestRealisticWalkthrough:
    """Drive a session through several pick_next_question calls.

    Locks in that the multi-step interaction between anchor / verification /
    info-gain / budget all compose correctly.
    """

    def test_g3_multiplication_first_three_calls(self):
        config = make_config(
            operation_order=["Multiplication"],
            per_operation_budget=9,
            total_budget=42,
        )
        skills = ["Repeated addition", "Tables 1 to 9", "2D x 1D"]
        skill_to_op = {s: "Multiplication" for s in skills}
        anchors = {"Multiplication": "Tables 1 to 9"}

        state = make_state(
            skills_in_scope=skills,
            skill_to_operation=skill_to_op,
            operation_anchors=anchors,
            posteriors={s: 0.5 for s in skills},
            direct_obs_count={s: 0 for s in skills},
        )

        # Call 1: anchor.
        c1 = pick_next_question(state, config, empty_lattice())
        assert c1 is not None
        assert c1.skill == "Tables 1 to 9"
        assert c1.purpose == Purpose.ANCHOR

        # Simulate: anchor asked, answered correctly. Bayes update on 0.5 -> 0.857.
        state.posteriors["Tables 1 to 9"] = 0.857
        state.direct_obs_count["Tables 1 to 9"] = 1
        state.questions_total = 1
        state.questions_per_operation["Multiplication"] = 1

        # Call 2: info-gain. Both "Repeated addition" and "2D x 1D" have entropy 1.0.
        # Alphabetical tiebreak: "2D x 1D" beats "Repeated addition" because '2' < 'R' in ASCII.
        c2 = pick_next_question(state, config, empty_lattice())
        assert c2 is not None
        assert c2.purpose == Purpose.INFO_GAIN
        assert c2.skill == "2D x 1D"

        # Simulate: asked, incorrect. Bayes update on 0.5 -> 0.105.
        state.posteriors["2D x 1D"] = 0.105
        state.direct_obs_count["2D x 1D"] = 1
        state.questions_total = 2
        state.questions_per_operation["Multiplication"] = 2

        # Call 3: now "Repeated addition" is the only unresolved at posterior 0.5.
        # "Tables 1 to 9" at 0.857, "2D x 1D" at 0.105 - both still unresolved
        # (0.857 < 0.95 and 0.105 > 0.10). The unresolved with highest entropy is "Repeated addition".
        c3 = pick_next_question(state, config, empty_lattice())
        assert c3 is not None
        assert c3.purpose == Purpose.INFO_GAIN
        assert c3.skill == "Repeated addition"
