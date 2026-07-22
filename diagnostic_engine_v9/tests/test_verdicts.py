"""Unit tests for engine.verdicts."""

from dataclasses import FrozenInstanceError

import pytest

from engine.verdicts import (
    ConfidenceLabel,
    Recommendation,
    Verdict,
    assign_verdict,
)

# Production threshold values from spec section 7.7
MASTERY = 0.95
NOT_MASTERED = 0.10


def verdict(posterior: float, direct_obs: int, propagation_updates: int = 0) -> Verdict:
    """Shorthand for the default-threshold call.

    propagation_updates defaults to 0 (priors-only). Tests of propagation-
    only paths should pass propagation_updates >= 1 explicitly.
    """
    return assign_verdict(
        posterior, direct_obs, MASTERY, NOT_MASTERED,
        propagation_updates=propagation_updates,
    )


# Rule 1: confident_mastered ---------------------------------------------------


class TestConfidentMastered:
    def test_clear_mastery(self):
        v = verdict(0.99, 3)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert v.recommendation == Recommendation.SKIP_MAIND

    def test_mastery_at_threshold_inclusive(self):
        # Spec table row 1 uses '>= 0.95': boundary is inclusive.
        v = verdict(0.95, 1)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert v.recommendation == Recommendation.SKIP_MAIND

    def test_single_direct_observation_sufficient(self):
        # Spec: direct_observations >= 1
        v = verdict(0.97, 1)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED


# Rule 4: confident_not_mastered ----------------------------------------------


class TestConfidentNotMastered:
    def test_clear_not_mastery(self):
        v = verdict(0.02, 2)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    def test_not_mastery_at_threshold_inclusive(self):
        # Spec table row 4 uses '<= 0.10': boundary is inclusive.
        v = verdict(0.10, 1)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC


# Rule 2: uncertain, lean mastered -> confirmation ----------------------------


class TestUncertainLeanMastered:
    """posterior in [0.5, mastery_threshold), any direct_obs."""

    @pytest.mark.parametrize("posterior", [0.5, 0.6, 0.85, 0.94, 0.9499])
    def test_lean_mastered_recommends_confirmation(self, posterior):
        v = verdict(posterior, 1)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_CONFIRMATION

    def test_lean_mastered_at_half_inclusive(self):
        # posterior == 0.5: lean threshold is inclusive on the mastered side.
        v = verdict(0.5, 1)
        assert v.recommendation == Recommendation.TAKE_MAIND_CONFIRMATION

    @pytest.mark.parametrize("posterior", [0.5, 0.7, 0.94])
    def test_lean_mastered_zero_direct_obs_still_confirmation(self, posterior):
        # Not in a 'confident zone', so the downgrade rule does NOT apply.
        # Recommendation stays confirmation even with no direct observation.
        v = verdict(posterior, 0)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_CONFIRMATION


# Rule 3: uncertain, lean not mastered -> diagnostic --------------------------


class TestUncertainLeanNotMastered:
    """posterior in (not_mastered_threshold, 0.5), any direct_obs."""

    @pytest.mark.parametrize("posterior", [0.11, 0.25, 0.49])
    def test_lean_not_mastered_recommends_diagnostic(self, posterior):
        v = verdict(posterior, 1)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    @pytest.mark.parametrize("posterior", [0.15, 0.3])
    def test_lean_not_mastered_zero_direct_obs_still_diagnostic(self, posterior):
        v = verdict(posterior, 0)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC


# Rules 2, 3, 7, 8: priors-only vs propagation-only ---------------------------


class TestPriorsOnly:
    """direct_obs == 0 AND propagation_updates == 0.

    Per spec section 7.6, this is the priors-only case: the engine never
    touched the skill, and lattice propagation never moved it either, so
    the posterior is at its initial cohort-prior value. Cohort priors are
    calibrated from real learner data, so the engine trusts them and
    issues a confident verdict (Rules 2 and 7).
    """

    @pytest.mark.parametrize("posterior", [0.95, 0.97, 0.99, 1.0])
    def test_mastery_zone_priors_only_earns_confident_mastered(self, posterior):
        # Rule 2: posterior >= mastery AND direct_obs == 0 AND propagation == 0
        v = verdict(posterior, 0, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert v.recommendation == Recommendation.SKIP_MAIND

    @pytest.mark.parametrize("posterior", [0.0, 0.02, 0.05, 0.10])
    def test_not_mastered_zone_priors_only_earns_confident_not_mastered(self, posterior):
        # Rule 7: posterior <= not_mastered AND direct_obs == 0 AND propagation == 0
        v = verdict(posterior, 0, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC


class TestPropagationOnly:
    """direct_obs == 0 AND propagation_updates >= 1.

    Per spec section 7.6, this is the propagation-only case: lattice
    propagation moved the posterior but the engine never asked a question
    directly on this skill. Lattice edges are inferred (12 hand-curated
    edges, not direct measurement), so propagation-only resolutions are
    downgraded to uncertain regardless of how confident the posterior
    looks (Rules 3 and 8).
    """

    @pytest.mark.parametrize("posterior", [0.95, 0.97, 0.99, 1.0])
    def test_mastery_zone_propagation_only_downgrades(self, posterior):
        # Rule 3: posterior >= mastery AND direct_obs == 0 AND propagation >= 1
        v = verdict(posterior, 0, propagation_updates=1)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    @pytest.mark.parametrize("posterior", [0.0, 0.02, 0.05, 0.10])
    def test_not_mastered_zone_propagation_only_downgrades(self, posterior):
        # Rule 8: posterior <= not_mastered AND direct_obs == 0 AND propagation >= 1
        v = verdict(posterior, 0, propagation_updates=1)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    @pytest.mark.parametrize("prop_updates", [1, 2, 5, 100])
    def test_propagation_count_does_not_matter_only_nonzero(self, prop_updates):
        # Any propagation_updates >= 1 triggers downgrade in confident zones.
        v = verdict(0.99, 0, propagation_updates=prop_updates)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN

    def test_propagation_only_never_returns_skip_maind(self):
        for posterior in [0.95, 0.97, 0.99, 1.0]:
            v = verdict(posterior, 0, propagation_updates=1)
            assert v.recommendation != Recommendation.SKIP_MAIND

    def test_propagation_only_never_returns_confident_not_mastered(self):
        for posterior in [0.0, 0.05, 0.10]:
            v = verdict(posterior, 0, propagation_updates=1)
            assert v.confidence_label != ConfidenceLabel.CONFIDENT_NOT_MASTERED


# Verdict structure -----------------------------------------------------------


class TestVerdictStructure:
    def test_verdict_carries_input_values(self):
        v = verdict(0.97, 3)
        assert v.posterior == 0.97
        assert v.direct_observations == 3

    def test_verdict_is_frozen(self):
        v = verdict(0.97, 3)
        with pytest.raises(FrozenInstanceError):
            v.posterior = 0.5  # type: ignore[misc]

    def test_verdict_equality(self):
        v1 = verdict(0.97, 3)
        v2 = verdict(0.97, 3)
        assert v1 == v2

    def test_enum_values_serialize_to_strings(self):
        # Spec API contract (section 5.4) requires string values in JSON.
        v = verdict(0.97, 3)
        assert v.confidence_label == "confident_mastered"
        assert v.recommendation == "skip_maind"

    def test_enum_values_are_canonical_spec_strings(self):
        # Verify all six enum string values match the spec wording exactly.
        assert ConfidenceLabel.CONFIDENT_MASTERED.value == "confident_mastered"
        assert ConfidenceLabel.UNCERTAIN.value == "uncertain"
        assert ConfidenceLabel.CONFIDENT_NOT_MASTERED.value == "confident_not_mastered"
        assert Recommendation.SKIP_MAIND.value == "skip_maind"
        assert Recommendation.TAKE_MAIND_CONFIRMATION.value == "take_maind_confirmation"
        assert Recommendation.TAKE_MAIND_DIAGNOSTIC.value == "take_maind_diagnostic"


# Custom thresholds -----------------------------------------------------------


class TestCustomThresholds:
    """If engineering changes the thresholds in v2, the math still works."""

    def test_stricter_mastery_threshold(self):
        # With mastery threshold 0.99, posterior 0.97 is NOT confident_mastered.
        v = assign_verdict(0.97, 3, mastery_threshold=0.99, not_mastered_threshold=0.10)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_CONFIRMATION

    def test_looser_not_mastered_threshold(self):
        # With not-mastered threshold 0.25, posterior 0.20 IS confident_not_mastered.
        v = assign_verdict(0.20, 2, mastery_threshold=0.95, not_mastered_threshold=0.25)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED


# Input validation -----------------------------------------------------------


class TestValidation:
    def test_negative_posterior_raises(self):
        with pytest.raises(ValueError, match="posterior"):
            verdict(-0.1, 1)

    def test_posterior_above_one_raises(self):
        with pytest.raises(ValueError, match="posterior"):
            verdict(1.1, 1)

    def test_nan_posterior_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            verdict(float("nan"), 1)

    def test_negative_direct_observations_raises(self):
        with pytest.raises(ValueError, match="direct_observations"):
            verdict(0.5, -1)

    def test_mastery_threshold_at_half_raises(self):
        with pytest.raises(ValueError, match="mastery_threshold"):
            assign_verdict(0.5, 1, mastery_threshold=0.5, not_mastered_threshold=0.10)

    def test_mastery_threshold_at_one_raises(self):
        with pytest.raises(ValueError, match="mastery_threshold"):
            assign_verdict(0.5, 1, mastery_threshold=1.0, not_mastered_threshold=0.10)

    def test_not_mastered_threshold_at_zero_raises(self):
        with pytest.raises(ValueError, match="not_mastered_threshold"):
            assign_verdict(0.5, 1, mastery_threshold=0.95, not_mastered_threshold=0.0)

    def test_not_mastered_threshold_at_half_raises(self):
        with pytest.raises(ValueError, match="not_mastered_threshold"):
            assign_verdict(0.5, 1, mastery_threshold=0.95, not_mastered_threshold=0.5)

    def test_production_parameters_pass_validation(self):
        # The actual production values from the spec should be accepted.
        assign_verdict(0.5, 1, mastery_threshold=0.95, not_mastered_threshold=0.10)


# Exhaustive coverage of the 5 spec table rows --------------------------------


class TestSpecTableExhaustive:
    """One representative test per row of the spec section 7.6 8-rule table."""

    def test_rule_1_confident_mastered_with_direct(self):
        # posterior >= 0.95, direct >= 1, any propagation
        v = verdict(0.97, 3, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert v.recommendation == Recommendation.SKIP_MAIND

    def test_rule_2_confident_mastered_priors_only(self):
        # posterior >= 0.95, direct == 0, propagation == 0
        v = verdict(0.97, 0, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert v.recommendation == Recommendation.SKIP_MAIND

    def test_rule_3_propagation_only_high_downgrades(self):
        # posterior >= 0.95, direct == 0, propagation >= 1
        v = verdict(0.97, 0, propagation_updates=1)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    def test_rule_4_uncertain_lean_mastered(self):
        # 0.5 <= posterior < 0.95
        v = verdict(0.70, 2, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_CONFIRMATION

    def test_rule_5_uncertain_lean_not_mastered(self):
        # not_mastered < posterior < 0.5
        v = verdict(0.30, 2, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    def test_rule_6_confident_not_mastered_with_direct(self):
        # posterior <= 0.10, direct >= 1
        v = verdict(0.05, 3, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    def test_rule_7_confident_not_mastered_priors_only(self):
        # posterior <= 0.10, direct == 0, propagation == 0
        v = verdict(0.05, 0, propagation_updates=0)
        assert v.confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC

    def test_rule_8_propagation_only_low_downgrades(self):
        # posterior <= 0.10, direct == 0, propagation >= 1
        v = verdict(0.05, 0, propagation_updates=1)
        assert v.confidence_label == ConfidenceLabel.UNCERTAIN
        assert v.recommendation == Recommendation.TAKE_MAIND_DIAGNOSTIC
