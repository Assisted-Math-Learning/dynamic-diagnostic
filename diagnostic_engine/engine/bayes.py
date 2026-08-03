"""
Bayesian posterior update for the dynamic diagnostic engine.

Implements the single-skill update from the engineering spec, section 7.2.
Pure functions - no I/O, no dependencies on other engine modules.

The model in plain terms:
  - The engine carries a running estimate (the "posterior") of how likely it is
    that a learner has mastered a given skill, a number between 0 and 1.
  - After every observed response (correct or incorrect) on that skill, the
    posterior is updated using Bayes' rule with two fixed parameters:
      slip:  probability a mastered learner gets a question wrong (0.10 in v1)
      guess: probability a non-mastered learner gets a question right (0.15 in v1)
  - A correct response pushes the posterior up; an incorrect response pushes it
    down. The size of the move depends on how surprising the response was given
    the current belief.
"""

from typing import Final


def likelihood(is_correct: bool, mastered: bool, slip: float, guess: float) -> float:
    """P(observed response | true mastery state). The model's emission distribution.

    P(correct | mastered)     = 1 - slip
    P(incorrect | mastered)   = slip
    P(correct | not mastered) = guess
    P(incorrect | not mastered) = 1 - guess
    """
    if mastered:
        return (1.0 - slip) if is_correct else slip
    return guess if is_correct else (1.0 - guess)


def update_posterior(prior: float, is_correct: bool, slip: float, guess: float) -> float:
    """One-step Bayesian update.

    Returns the posterior P(mastered | response, prior).

    Formula from spec section 7.2:
        correct:   p' = (1 - slip) * p / ((1 - slip) * p + guess * (1 - p))
        incorrect: p' = slip * p       / (slip * p + (1 - guess) * (1 - p))

    Args:
        prior: starting posterior probability in [0, 1].
        is_correct: response Boolean (already scored by aml-api-service).
        slip: probability a mastered learner answers incorrectly, in (0, 1).
        guess: probability a non-mastered learner answers correctly, in (0, 1).

    Returns:
        Updated posterior in [0, 1].

    Raises:
        ValueError: if any input violates the model's assumptions (prior outside
            [0, 1], slip/guess outside (0, 1), or 1 - slip <= guess which would
            mean correct responses are not informative about mastery).
    """
    _validate_inputs(prior, slip, guess)

    p_resp_given_mastered = likelihood(is_correct, True, slip, guess)
    p_resp_given_not_mastered = likelihood(is_correct, False, slip, guess)

    numerator = p_resp_given_mastered * prior
    denominator = numerator + p_resp_given_not_mastered * (1.0 - prior)

    # Denominator is provably > 0 given the validated input ranges, so no epsilon
    # guard is needed. _validate_inputs enforces slip and guess strictly in (0, 1)
    # and 1 - slip > guess, which makes both likelihoods strictly positive.
    return numerator / denominator


# Internal helpers ------------------------------------------------------------

_PRIOR_MIN: Final[float] = 0.0
_PRIOR_MAX: Final[float] = 1.0


def _validate_inputs(prior: float, slip: float, guess: float) -> None:
    if not _PRIOR_MIN <= prior <= _PRIOR_MAX:
        raise ValueError(f"prior must be in [0, 1], got {prior}")
    if not 0.0 < slip < 1.0:
        raise ValueError(f"slip must be in (0, 1), got {slip}")
    if not 0.0 < guess < 1.0:
        raise ValueError(f"guess must be in (0, 1), got {guess}")
    if (1.0 - slip) <= guess:
        raise ValueError(
            f"model requires (1 - slip) > guess: got slip={slip}, guess={guess}. "
            f"This implies P(correct|mastered)={1 - slip} <= P(correct|not mastered)={guess}, "
            "so a correct response would not be evidence of mastery."
        )
