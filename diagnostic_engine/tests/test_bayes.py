"""Unit tests for engine.bayes."""

import math

import pytest

from engine.bayes import likelihood, update_posterior

# Production parameter values from spec section 7.7
SLIP = 0.10
GUESS = 0.15


# Likelihood -------------------------------------------------------------------

class TestLikelihood:
    """The emission distribution P(response | mastery state)."""

    def test_correct_given_mastered(self):
        assert likelihood(is_correct=True, mastered=True, slip=SLIP, guess=GUESS) == 1.0 - SLIP

    def test_correct_given_not_mastered(self):
        assert likelihood(is_correct=True, mastered=False, slip=SLIP, guess=GUESS) == GUESS

    def test_incorrect_given_mastered(self):
        assert likelihood(is_correct=False, mastered=True, slip=SLIP, guess=GUESS) == SLIP

    def test_incorrect_given_not_mastered(self):
        assert (
            likelihood(is_correct=False, mastered=False, slip=SLIP, guess=GUESS) == 1.0 - GUESS
        )


# Posterior update direction and magnitude -------------------------------------

class TestUpdateDirection:
    """A correct response moves up, an incorrect response moves down,
    for every non-dogmatic prior."""

    @pytest.mark.parametrize("prior", [0.05, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95])
    def test_correct_increases_posterior(self, prior):
        assert update_posterior(prior, is_correct=True, slip=SLIP, guess=GUESS) > prior

    @pytest.mark.parametrize("prior", [0.05, 0.1, 0.3, 0.5, 0.7, 0.9, 0.95])
    def test_incorrect_decreases_posterior(self, prior):
        assert update_posterior(prior, is_correct=False, slip=SLIP, guess=GUESS) < prior


class TestUpdateExactValues:
    """Hand-computed values verifying the formula matches the spec."""

    def test_correct_at_midpoint(self):
        # p = 0.5, correct: (0.9 * 0.5) / (0.9 * 0.5 + 0.15 * 0.5) = 0.45 / 0.525
        result = update_posterior(0.5, is_correct=True, slip=SLIP, guess=GUESS)
        assert math.isclose(result, 0.45 / 0.525, rel_tol=1e-12)

    def test_incorrect_at_midpoint(self):
        # p = 0.5, incorrect: (0.1 * 0.5) / (0.1 * 0.5 + 0.85 * 0.5) = 0.05 / 0.475
        result = update_posterior(0.5, is_correct=False, slip=SLIP, guess=GUESS)
        assert math.isclose(result, 0.05 / 0.475, rel_tol=1e-12)

    def test_correct_at_low_prior(self):
        # p = 0.1, correct: (0.9 * 0.1) / (0.9 * 0.1 + 0.15 * 0.9) = 0.09 / 0.225
        result = update_posterior(0.1, is_correct=True, slip=SLIP, guess=GUESS)
        assert math.isclose(result, 0.09 / 0.225, rel_tol=1e-12)

    def test_incorrect_at_high_prior(self):
        # p = 0.9, incorrect: (0.1 * 0.9) / (0.1 * 0.9 + 0.85 * 0.1) = 0.09 / 0.175
        result = update_posterior(0.9, is_correct=False, slip=SLIP, guess=GUESS)
        assert math.isclose(result, 0.09 / 0.175, rel_tol=1e-12)


class TestUpdateBoundaries:
    """Boundary values 0 and 1 are dogmatic priors that no observation can move."""

    def test_prior_zero_stays_zero_on_correct(self):
        assert update_posterior(0.0, is_correct=True, slip=SLIP, guess=GUESS) == 0.0

    def test_prior_zero_stays_zero_on_incorrect(self):
        assert update_posterior(0.0, is_correct=False, slip=SLIP, guess=GUESS) == 0.0

    def test_prior_one_stays_one_on_correct(self):
        assert update_posterior(1.0, is_correct=True, slip=SLIP, guess=GUESS) == 1.0

    def test_prior_one_stays_one_on_incorrect(self):
        assert update_posterior(1.0, is_correct=False, slip=SLIP, guess=GUESS) == 1.0


class TestUpdateShape:
    """Compounding and asymmetry properties of the update."""

    def test_two_correct_compounds(self):
        p1 = update_posterior(0.5, is_correct=True, slip=SLIP, guess=GUESS)
        p2 = update_posterior(p1, is_correct=True, slip=SLIP, guess=GUESS)
        assert p2 > p1 > 0.5

    def test_two_incorrect_compounds(self):
        p1 = update_posterior(0.5, is_correct=False, slip=SLIP, guess=GUESS)
        p2 = update_posterior(p1, is_correct=False, slip=SLIP, guess=GUESS)
        assert p2 < p1 < 0.5

    def test_correct_then_incorrect_not_invertible(self):
        # Bayesian updates are not in general invertible: correct then incorrect
        # does not return you to the original prior.
        prior = 0.5
        p_after_correct = update_posterior(prior, is_correct=True, slip=SLIP, guess=GUESS)
        p_round_trip = update_posterior(p_after_correct, is_correct=False, slip=SLIP, guess=GUESS)
        assert not math.isclose(p_round_trip, prior, rel_tol=1e-6)

    def test_result_stays_in_unit_interval(self):
        # Sweep priors and confirm output stays in [0, 1].
        for i in range(1, 100):
            prior = i / 100.0
            p_correct = update_posterior(prior, is_correct=True, slip=SLIP, guess=GUESS)
            p_incorrect = update_posterior(prior, is_correct=False, slip=SLIP, guess=GUESS)
            assert 0.0 <= p_correct <= 1.0
            assert 0.0 <= p_incorrect <= 1.0


class TestUpdateReachesThresholds:
    """Sanity: starting at a midpoint prior, enough consecutive correct answers
    cross the mastery threshold (0.95) and enough consecutive incorrect answers
    cross the not-mastered threshold (0.10). This verifies the engine can
    actually resolve skills in a reasonable number of questions."""

    def test_reaches_mastery_from_half(self):
        p = 0.5
        steps = 0
        while p < 0.95 and steps < 20:
            p = update_posterior(p, is_correct=True, slip=SLIP, guess=GUESS)
            steps += 1
        assert p >= 0.95
        assert steps <= 5  # spec-consistent: 3-4 correct answers from 0.5 should suffice

    def test_reaches_not_mastered_from_half(self):
        p = 0.5
        steps = 0
        while p > 0.10 and steps < 20:
            p = update_posterior(p, is_correct=False, slip=SLIP, guess=GUESS)
            steps += 1
        assert p <= 0.10
        assert steps <= 5


# Input validation -------------------------------------------------------------

class TestValidation:
    """Invalid inputs raise ValueError with a descriptive message."""

    def test_negative_prior_raises(self):
        with pytest.raises(ValueError, match="prior"):
            update_posterior(-0.1, is_correct=True, slip=SLIP, guess=GUESS)

    def test_prior_above_one_raises(self):
        with pytest.raises(ValueError, match="prior"):
            update_posterior(1.1, is_correct=True, slip=SLIP, guess=GUESS)

    def test_slip_zero_raises(self):
        with pytest.raises(ValueError, match="slip"):
            update_posterior(0.5, is_correct=True, slip=0.0, guess=GUESS)

    def test_slip_one_raises(self):
        with pytest.raises(ValueError, match="slip"):
            update_posterior(0.5, is_correct=True, slip=1.0, guess=GUESS)

    def test_slip_negative_raises(self):
        with pytest.raises(ValueError, match="slip"):
            update_posterior(0.5, is_correct=True, slip=-0.1, guess=GUESS)

    def test_guess_zero_raises(self):
        with pytest.raises(ValueError, match="guess"):
            update_posterior(0.5, is_correct=True, slip=SLIP, guess=0.0)

    def test_guess_one_raises(self):
        with pytest.raises(ValueError, match="guess"):
            update_posterior(0.5, is_correct=True, slip=SLIP, guess=1.0)

    def test_inverted_model_raises(self):
        # slip=0.6, guess=0.5: P(correct|mastered)=0.4, P(correct|not mastered)=0.5
        # A correct response would actually be weak evidence of NOT mastery.
        with pytest.raises(ValueError, match="1 - slip"):
            update_posterior(0.5, is_correct=True, slip=0.6, guess=0.5)

    def test_production_params_pass(self):
        # Sanity: the production-config values are accepted.
        update_posterior(0.5, is_correct=True, slip=0.10, guess=0.15)
        update_posterior(0.5, is_correct=False, slip=0.10, guess=0.15)
