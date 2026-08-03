"""
Verdict assignment for the dynamic diagnostic engine.

At session end, every skill in the learner's scope gets a verdict. The
mapping from (posterior, direct_observations, propagation_updates) to
(confidence_label, recommendation) comes from spec section 7.6:

  Rule 1: posterior >= mastery  AND direct_obs >= 1
          -> confident_mastered + skip_maind
  Rule 2: posterior >= mastery  AND direct_obs == 0 AND propagation == 0
          -> confident_mastered + skip_maind            (priors-only)
  Rule 3: posterior >= mastery  AND direct_obs == 0 AND propagation >= 1
          -> uncertain (downgraded) + take_maind_diagnostic
  Rule 4: 0.5 <= posterior < mastery (any direct / propagation)
          -> uncertain + take_maind_confirmation
  Rule 5: not_mastered < posterior < 0.5 (any direct / propagation)
          -> uncertain + take_maind_diagnostic
  Rule 6: posterior <= not_mastered AND direct_obs >= 1
          -> confident_not_mastered + take_maind_diagnostic
  Rule 7: posterior <= not_mastered AND direct_obs == 0 AND propagation == 0
          -> confident_not_mastered + take_maind_diagnostic  (priors-only)
  Rule 8: posterior <= not_mastered AND direct_obs == 0 AND propagation >= 1
          -> uncertain (downgraded) + take_maind_diagnostic

The priors-only / propagation-only distinction (Rules 2/7 vs 3/8) is the
key change from earlier versions of this spec. Priors are calibrated from
the Delhi diagnostic response cohort (n_DL >= 130 per skill, ~1,300+ per
skill for G3-G5; Testing Summary section 4); the lattice has 12
hand-curated edges (Testing Summary section 9). The empirical evidence
says priors are reliable enough to trust without verification, but
lattice propagation is not. So priors-only resolutions earn confident
verdicts; propagation-only resolutions are sent to MainD for direct
verification.

Pure functions, no I/O, no dependencies on other engine modules.
"""

import math
from dataclasses import dataclass
from enum import Enum


class ConfidenceLabel(str, Enum):
    """The per-skill confidence label. Spec section 5.4 / 7.6."""

    CONFIDENT_MASTERED = "confident_mastered"
    UNCERTAIN = "uncertain"
    CONFIDENT_NOT_MASTERED = "confident_not_mastered"


class Recommendation(str, Enum):
    """The downstream recommendation for the AML practice router. Spec section 7.6."""

    SKIP_MAIND = "skip_maind"
    TAKE_MAIND_CONFIRMATION = "take_maind_confirmation"
    TAKE_MAIND_DIAGNOSTIC = "take_maind_diagnostic"


@dataclass(frozen=True)
class Verdict:
    """One skill's verdict at session end.

    The session/storage layer attaches skill_id and engine_version when
    building the API response and writing to learner_skill_verdicts.
    """

    posterior: float
    direct_observations: int
    propagation_updates: int
    confidence_label: ConfidenceLabel
    recommendation: Recommendation


# Internal constants derived from the spec table; not pulled into config yet
# because they describe the verdict mapping itself, not the engine's
# configurable parameters. See spec section 7.6.
_MIN_DIRECT_OBSERVATIONS_FOR_CONFIDENCE = 1
_LEANING_THRESHOLD = 0.5  # posterior >= 0.5 leans toward mastery, < 0.5 leans away


def assign_verdict(
    posterior: float,
    direct_observations: int,
    mastery_threshold: float,
    not_mastered_threshold: float,
    propagation_updates: int = 0,
) -> Verdict:
    """Map per-skill state to a verdict per spec section 7.6 (8 rules).

    Args:
        posterior: final posterior probability for the skill, in [0, 1].
        direct_observations: count of questions asked directly on this skill.
            Must be >= 0.
        mastery_threshold: posterior at or above this is the mastery zone
            (0.95 in v1). Must be in (0.5, 1).
        not_mastered_threshold: posterior at or below this is the not-mastered
            zone (0.10 in v1). Must be in (0, 0.5).
        propagation_updates: count of times this skill's posterior was moved
            by lattice propagation from a different skill's observation.
            Defaults to 0 for callers that haven't been upgraded yet. Must
            be >= 0.

    Returns:
        A Verdict with the confidence label, the recommendation, and the
        observation counters (carried through for downstream telemetry).

    Raises:
        ValueError: on invalid input (NaN, out-of-range values, etc).
    """
    _validate_inputs(
        posterior, direct_observations, mastery_threshold,
        not_mastered_threshold, propagation_updates,
    )

    in_mastery_zone = posterior >= mastery_threshold
    in_not_mastered_zone = posterior <= not_mastered_threshold
    has_direct_evidence = direct_observations >= _MIN_DIRECT_OBSERVATIONS_FOR_CONFIDENCE
    has_propagation = propagation_updates >= 1
    priors_only = (not has_direct_evidence) and (not has_propagation)

    # Rules 1 and 2: confident_mastered. Either direct evidence at a high
    # posterior, or a high posterior that the engine never touched at all
    # (priors-only, trusted because the cohort prior is calibrated).
    if in_mastery_zone and (has_direct_evidence or priors_only):
        return Verdict(
            posterior=posterior,
            direct_observations=direct_observations,
            propagation_updates=propagation_updates,
            confidence_label=ConfidenceLabel.CONFIDENT_MASTERED,
            recommendation=Recommendation.SKIP_MAIND,
        )

    # Rules 6 and 7: confident_not_mastered. Same shape as above, low end.
    if in_not_mastered_zone and (has_direct_evidence or priors_only):
        return Verdict(
            posterior=posterior,
            direct_observations=direct_observations,
            propagation_updates=propagation_updates,
            confidence_label=ConfidenceLabel.CONFIDENT_NOT_MASTERED,
            recommendation=Recommendation.TAKE_MAIND_DIAGNOSTIC,
        )

    # Everything below is `uncertain`. Pick the recommendation.

    # Rules 3 and 8: propagation-only resolution in a confident zone.
    # Lattice edges are approximate; downgrade and send to full MainD.
    propagation_only_in_confident_zone = (
        (in_mastery_zone or in_not_mastered_zone) and not has_direct_evidence
    )
    if propagation_only_in_confident_zone:
        recommendation = Recommendation.TAKE_MAIND_DIAGNOSTIC
    # Rule 4: in [0.5, mastery), leaning mastered, send to MainD for
    # confirmation rather than full diagnostic (cheaper, faster).
    elif posterior >= _LEANING_THRESHOLD:
        recommendation = Recommendation.TAKE_MAIND_CONFIRMATION
    # Rule 5: in (not_mastered, 0.5), leaning not-mastered, full diagnostic.
    else:
        recommendation = Recommendation.TAKE_MAIND_DIAGNOSTIC

    return Verdict(
        posterior=posterior,
        direct_observations=direct_observations,
        propagation_updates=propagation_updates,
        confidence_label=ConfidenceLabel.UNCERTAIN,
        recommendation=recommendation,
    )


# Internal -------------------------------------------------------------------


def _validate_inputs(
    posterior: float,
    direct_observations: int,
    mastery_threshold: float,
    not_mastered_threshold: float,
    propagation_updates: int,
) -> None:
    if math.isnan(posterior):
        raise ValueError("posterior is NaN")
    if not 0.0 <= posterior <= 1.0:
        raise ValueError(f"posterior must be in [0, 1], got {posterior}")
    if direct_observations < 0:
        raise ValueError(f"direct_observations must be >= 0, got {direct_observations}")
    if propagation_updates < 0:
        raise ValueError(
            f"propagation_updates must be >= 0, got {propagation_updates}"
        )
    if not 0.5 < mastery_threshold < 1.0:
        raise ValueError(
            f"mastery_threshold must be in (0.5, 1.0), got {mastery_threshold}"
        )
    if not 0.0 < not_mastered_threshold < 0.5:
        raise ValueError(
            f"not_mastered_threshold must be in (0, 0.5), got {not_mastered_threshold}"
        )
