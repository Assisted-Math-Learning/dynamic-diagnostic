"""
Engine configuration: Pydantic models + YAML loader.

The engine config is loaded once at startup from a YAML file (path set by
the ENGINE_CONFIG_PATH env var; default /etc/engine/config.yaml per spec
section 10.3). It holds:

  - Engine-wide algorithm parameters (slip, guess, thresholds, propagation)
  - Per-grade budgets and operation orders
  - The canonical L2.5 skill list: 40 entries (39 in the Delhi scope)
  - Per-(grade, operation) anchor skills
  - Per-(grade, skill) cohort priors

The EngineConfig.get_engine_params(grade, lattice_index) method produces the
EngineParams bundle that session.start_session expects.

Grades 6, 7, 8 fall back to the G5 configuration per spec section 2 (the
EngineParams.grade field keeps the original grade for telemetry, but the
budgets / anchors / priors / scope all come from the G5 row).
"""

from pathlib import Path
from typing import Dict, List

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.lattice import LatticeIndex
from engine.routing import RoutingConfig
from engine.session import EngineParams

# Grade fallback per spec section 2: grades 6+ use the G5 configuration.
_HIGHEST_NATIVE_GRADE = 5
_LOWEST_NATIVE_GRADE = 2


# Pydantic models ------------------------------------------------------------


class AlgorithmConfig(BaseModel):
    """Engine-wide algorithm parameters (spec section 7.7)."""

    model_config = ConfigDict(extra="forbid")

    slip: float = Field(ge=0.0, le=1.0)
    guess: float = Field(ge=0.0, le=1.0)
    mastery_threshold: float = Field(gt=0.5, lt=1.0)
    not_mastered_threshold: float = Field(gt=0.0, lt=0.5)
    verification_trigger_high: float = Field(gt=0.5, lt=1.0)
    verification_trigger_low: float = Field(gt=0.0, lt=0.5)
    edge_propagation_value: float = Field(gt=0.5, lt=1.0)
    info_gain_edge_bonus: float = Field(ge=0.0, default=0.5)


class GradeBudget(BaseModel):
    """Per-grade question budgets (spec section 7.7)."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(gt=0)
    per_operation: int = Field(gt=0)
    # Questions withheld from the adaptive phase (Phase 1) for misconception
    # backfill (Phase 2) and leftover-to-mastery (Phase 3). 0 disables the
    # coverage reserve entirely: adaptive_budget == total, no backfill phase,
    # behaviour identical to before the coverage layer. Provisional value is 7
    # per grade (misconception_coverage_selection_spec section 3.5); set 0 here
    # so existing configs without it stay inert until deliberately enabled.
    reserve_size: int = Field(ge=0, default=0)
    # per_operation_cap_multiplier is Option 1 (offline tree) only; kept here
    # for completeness so a single config file serves both online and tree
    # generation. The online engine ignores it.
    per_operation_cap_multiplier: float = Field(ge=1.0, default=1.5)

    @model_validator(mode="after")
    def _per_op_does_not_exceed_total(self):
        if self.per_operation > self.total:
            raise ValueError(
                f"per_operation ({self.per_operation}) must be <= total ({self.total})"
            )
        return self


class SkillEntry(BaseModel):
    """One canonical L2.5 skill (spec Appendix C)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    content_grade: int = Field(ge=1, le=8)


class MisconceptionConfig(BaseModel):
    """Engine-wide misconception-coverage parameters (selection spec 3.5,
    verdict-rule spec). Deployment-tunable; the defaults are the shipped values.

    `target`/`conditional_extra` govern how many tagged asks the engine spends;
    `clear_threshold`/`present_threshold` are the accuracy bands for the verdict
    (>= clear -> likely_absent, < present -> likely_present, else unsure). These
    are engine-wide (not per-grade). The module constants in engine.misconception
    remain the code-level defaults when the functions are called directly.
    """

    model_config = ConfigDict(extra="forbid")

    target: int = Field(ge=1, default=2)
    conditional_extra: int = Field(ge=0, default=2)
    clear_threshold: float = Field(gt=0.5, le=1.0, default=0.75)
    present_threshold: float = Field(gt=0.0, lt=1.0, default=0.50)

    @model_validator(mode="after")
    def _present_below_clear(self):
        if self.present_threshold >= self.clear_threshold:
            raise ValueError(
                "misconception.present_threshold must be below clear_threshold"
            )
        return self


class EngineConfig(BaseModel):
    """Top-level engine configuration loaded from engine_config.yaml."""

    model_config = ConfigDict(extra="forbid")

    version: str
    algorithm: AlgorithmConfig
    budgets: Dict[int, GradeBudget]
    operation_order: Dict[int, List[str]]
    skills: List[SkillEntry]
    anchors: Dict[int, Dict[str, str]]
    priors: Dict[int, Dict[str, float]]
    misconception: "MisconceptionConfig" = Field(default_factory=lambda: MisconceptionConfig())

    @model_validator(mode="after")
    def _check_grade_coverage(self):
        budget_grades = set(self.budgets.keys())
        order_grades = set(self.operation_order.keys())
        if budget_grades != order_grades:
            raise ValueError(
                f"budgets and operation_order must cover the same grades; "
                f"budgets={sorted(budget_grades)}, "
                f"operation_order={sorted(order_grades)}"
            )
        for grade in budget_grades:
            if grade not in self.anchors:
                raise ValueError(f"grade {grade} missing from anchors")
            if grade not in self.priors:
                raise ValueError(f"grade {grade} missing from priors")
        return self

    @model_validator(mode="after")
    def _check_thresholds_consistency(self):
        a = self.algorithm
        if a.verification_trigger_high > a.mastery_threshold:
            raise ValueError(
                f"verification_trigger_high ({a.verification_trigger_high}) "
                f"must be <= mastery_threshold ({a.mastery_threshold})"
            )
        if a.verification_trigger_low < a.not_mastered_threshold:
            raise ValueError(
                f"verification_trigger_low ({a.verification_trigger_low}) "
                f"must be >= not_mastered_threshold ({a.not_mastered_threshold})"
            )
        return self

    # === EngineParams construction =========================================

    def get_engine_params(self, grade: int, lattice_index: LatticeIndex) -> EngineParams:
        """Build the EngineParams bundle for a learner at the given grade.

        Grades above _HIGHEST_NATIVE_GRADE fall back to that grade's config
        (spec section 2). The returned EngineParams.grade keeps the ORIGINAL
        grade so the Session document and downstream telemetry reflect the
        learner's true class.
        """
        if grade < _LOWEST_NATIVE_GRADE:
            raise ValueError(
                f"grade {grade} below supported range (min {_LOWEST_NATIVE_GRADE})"
            )
        effective_grade = min(grade, _HIGHEST_NATIVE_GRADE)
        if effective_grade not in self.budgets:
            raise ValueError(
                f"effective grade {effective_grade} not in config "
                f"(supported: {sorted(self.budgets.keys())})"
            )

        budget = self.budgets[effective_grade]
        op_order = list(self.operation_order[effective_grade])
        anchors = dict(self.anchors[effective_grade])
        priors = dict(self.priors[effective_grade])

        # Scope = all skills whose content_grade <= effective_grade.
        in_scope = [s for s in self.skills if s.content_grade <= effective_grade]
        skills_in_scope = [s.name for s in in_scope]
        skill_to_op = {s.name: s.operation for s in in_scope}

        routing_config = RoutingConfig(
            operation_order=op_order,
            per_operation_budget=budget.per_operation,
            total_budget=budget.total,
            mastery_threshold=self.algorithm.mastery_threshold,
            not_mastered_threshold=self.algorithm.not_mastered_threshold,
            verification_high=self.algorithm.verification_trigger_high,
            verification_low=self.algorithm.verification_trigger_low,
            info_gain_edge_bonus=self.algorithm.info_gain_edge_bonus,
        )

        return EngineParams(
            grade=grade,  # original grade (for telemetry / session.grade)
            skills_in_scope=skills_in_scope,
            skill_to_operation=skill_to_op,
            operation_anchors=anchors,
            priors=priors,
            routing_config=routing_config,
            lattice_index=lattice_index,
            slip=self.algorithm.slip,
            guess=self.algorithm.guess,
            edge_propagation_value=self.algorithm.edge_propagation_value,
            reserve_size=budget.reserve_size,
            misconception_conditional_extra=self.misconception.conditional_extra,
            misconception_clear_threshold=self.misconception.clear_threshold,
            misconception_present_threshold=self.misconception.present_threshold,
        )


# Loader ---------------------------------------------------------------------


def load_engine_config(path: str) -> EngineConfig:
    """Load and validate an EngineConfig from a YAML file.

    Raises:
        FileNotFoundError if path doesn't exist.
        pydantic.ValidationError if the YAML structure is invalid.
        yaml.YAMLError if the file is not valid YAML.
    """
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        raise ValueError(f"engine config at {path} is empty")
    return EngineConfig.model_validate(data)


# Startup checks ------------------------------------------------------------


def check_priors_coverage(config: EngineConfig) -> List[int]:
    """Return the sorted list of configured grades that have zero priors.

    A grade with no priors is one where ``config.priors[grade]`` is missing
    or empty. For each such grade, the engine silently falls back to a
    default prior of 0.5 for every skill - safe for testing but a hidden
    behavior change in production.

    Operators use this at startup to either:
      - Log a WARN per missing grade (default behavior), or
      - Fail-fast via the STRICT_PRIORS_REQUIRED env var (see
        ``engine.api.main.create_app_from_env``).
    """
    return sorted(g for g in config.budgets.keys() if not config.priors.get(g))
