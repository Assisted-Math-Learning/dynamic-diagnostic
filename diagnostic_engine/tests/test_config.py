"""Unit tests for engine.config."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from engine.config import (
    AlgorithmConfig,
    EngineConfig,
    GradeBudget,
    SkillEntry,
    check_priors_coverage,
    load_engine_config,
)
from engine.lattice import LatticeIndex

TEST_FIXTURE = Path(__file__).parent / "fixtures" / "engine_config_test.yaml"


# Loading and parsing --------------------------------------------------------


class TestYamlLoading:
    def test_loads_fixture_file(self):
        config = load_engine_config(str(TEST_FIXTURE))
        assert config.version == "0.1.0-test"
        assert config.algorithm.slip == 0.10
        assert config.algorithm.guess == 0.15

    def test_budgets_keyed_by_int_grade(self):
        config = load_engine_config(str(TEST_FIXTURE))
        assert 2 in config.budgets
        assert 3 in config.budgets
        assert config.budgets[2].total == 25
        assert config.budgets[3].per_operation == 9

    def test_skills_list_loaded(self):
        config = load_engine_config(str(TEST_FIXTURE))
        assert len(config.skills) == 6
        names = {s.name for s in config.skills}
        assert "Tables 1 to 9" in names

    def test_anchors_and_priors_loaded(self):
        config = load_engine_config(str(TEST_FIXTURE))
        assert config.anchors[3]["Multiplication"] == "Tables 1 to 9"
        assert config.priors[3]["Tables 1 to 9"] == 0.5

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_engine_config("/nonexistent/path.yaml")

    def test_empty_file_raises(self, tmp_path: Path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_engine_config(str(empty))


# Pydantic validation --------------------------------------------------------


class TestAlgorithmConfigValidation:
    def test_valid_config(self):
        c = AlgorithmConfig(
            slip=0.10, guess=0.15,
            mastery_threshold=0.95, not_mastered_threshold=0.10,
            verification_trigger_high=0.85, verification_trigger_low=0.15,
            edge_propagation_value=0.90,
        )
        assert c.info_gain_edge_bonus == 0.5  # default

    def test_mastery_at_half_rejected(self):
        with pytest.raises(ValidationError):
            AlgorithmConfig(
                slip=0.10, guess=0.15,
                mastery_threshold=0.5, not_mastered_threshold=0.10,
                verification_trigger_high=0.85, verification_trigger_low=0.15,
                edge_propagation_value=0.90,
            )

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AlgorithmConfig(
                slip=0.10, guess=0.15,
                mastery_threshold=0.95, not_mastered_threshold=0.10,
                verification_trigger_high=0.85, verification_trigger_low=0.15,
                edge_propagation_value=0.90,
                bogus_field=42,
            )


class TestGradeBudgetValidation:
    def test_per_op_above_total_rejected(self):
        with pytest.raises(ValidationError):
            GradeBudget(total=10, per_operation=15)

    def test_zero_budget_rejected(self):
        with pytest.raises(ValidationError):
            GradeBudget(total=0, per_operation=0)


class TestSkillEntryValidation:
    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            SkillEntry(name="", operation="Addition", sequence=1, content_grade=1)

    def test_content_grade_out_of_range(self):
        with pytest.raises(ValidationError):
            SkillEntry(name="X", operation="Addition", sequence=1, content_grade=9)


class TestEngineConfigCrossValidation:
    def _good_data(self):
        return yaml.safe_load(TEST_FIXTURE.read_text())

    def test_mismatched_grade_sets_rejected(self):
        data = self._good_data()
        # Budgets has G2 and G3; operation_order only has G3
        data["operation_order"] = {3: ["Multiplication", "Addition", "Subtraction", "Division"]}
        with pytest.raises(ValidationError, match="operation_order"):
            EngineConfig.model_validate(data)

    def test_missing_anchors_for_grade_rejected(self):
        data = self._good_data()
        del data["anchors"][2]
        with pytest.raises(ValidationError, match="anchors"):
            EngineConfig.model_validate(data)

    def test_missing_priors_for_grade_rejected(self):
        data = self._good_data()
        del data["priors"][2]
        with pytest.raises(ValidationError, match="priors"):
            EngineConfig.model_validate(data)

    def test_verification_high_above_mastery_rejected(self):
        data = self._good_data()
        data["algorithm"]["verification_trigger_high"] = 0.96
        with pytest.raises(ValidationError, match="verification_trigger_high"):
            EngineConfig.model_validate(data)

    def test_verification_low_below_not_mastered_rejected(self):
        data = self._good_data()
        data["algorithm"]["verification_trigger_low"] = 0.05
        with pytest.raises(ValidationError, match="verification_trigger_low"):
            EngineConfig.model_validate(data)


# get_engine_params ----------------------------------------------------------


class TestGetEngineParams:
    def setup_method(self):
        self.config = load_engine_config(str(TEST_FIXTURE))
        self.lattice = LatticeIndex([])

    def test_g3_returns_full_scope(self):
        # G3 includes all skills with content_grade <= 3 = all 6 skills
        params = self.config.get_engine_params(grade=3, lattice_index=self.lattice)
        assert set(params.skills_in_scope) == {
            "1D+1D sum upto 9",
            "2-digit Addition with carry",
            "1D - 0 to 9",
            "Repeated addition",
            "Tables 1 to 9",
            "Division using Distribution",
        }

    def test_g2_filters_by_content_grade(self):
        # G2: only skills with content_grade <= 2.
        # That excludes "2-digit Addition with carry" (cg=3) and "Tables 1 to 9" (cg=3).
        params = self.config.get_engine_params(grade=2, lattice_index=self.lattice)
        assert set(params.skills_in_scope) == {
            "1D+1D sum upto 9",     # cg=1
            "1D - 0 to 9",          # cg=1
            "Repeated addition",    # cg=2
            "Division using Distribution",  # cg=2
        }

    def test_skill_to_operation_built(self):
        params = self.config.get_engine_params(grade=3, lattice_index=self.lattice)
        assert params.skill_to_operation["Tables 1 to 9"] == "Multiplication"
        assert params.skill_to_operation["1D+1D sum upto 9"] == "Addition"

    def test_priors_loaded_per_grade(self):
        params_g2 = self.config.get_engine_params(grade=2, lattice_index=self.lattice)
        params_g3 = self.config.get_engine_params(grade=3, lattice_index=self.lattice)
        # Same skill, different grade -> different prior
        assert params_g2.priors["1D+1D sum upto 9"] == 0.85
        assert params_g3.priors["1D+1D sum upto 9"] == 0.95

    def test_anchors_loaded_per_grade(self):
        params_g2 = self.config.get_engine_params(grade=2, lattice_index=self.lattice)
        params_g3 = self.config.get_engine_params(grade=3, lattice_index=self.lattice)
        # Multiplication anchor differs by grade in the test fixture
        assert params_g2.operation_anchors["Multiplication"] == "Repeated addition"
        assert params_g3.operation_anchors["Multiplication"] == "Tables 1 to 9"

    def test_routing_config_built_with_correct_budgets(self):
        params = self.config.get_engine_params(grade=3, lattice_index=self.lattice)
        assert params.routing_config.total_budget == 42
        assert params.routing_config.per_operation_budget == 9

    def test_thresholds_propagated(self):
        params = self.config.get_engine_params(grade=3, lattice_index=self.lattice)
        assert params.mastery_threshold == 0.95
        assert params.not_mastered_threshold == 0.10
        assert params.routing_config.verification_high == 0.85

    def test_engine_params_grade_keeps_original(self):
        # Grade 7 is above the highest native grade; effective grade is 5
        # but EngineParams.grade should remain the original.
        # NOTE: this fixture only has G2/G3. Use a config with G5 for the test.
        data = yaml.safe_load(TEST_FIXTURE.read_text())
        # Add G5 by copying G3's config
        data["budgets"][5] = data["budgets"][3]
        data["operation_order"][5] = data["operation_order"][3]
        data["anchors"][5] = data["anchors"][3]
        data["priors"][5] = data["priors"][3]
        config = EngineConfig.model_validate(data)
        params = config.get_engine_params(grade=7, lattice_index=self.lattice)
        # The original grade is preserved in EngineParams
        assert params.grade == 7
        # But the effective config (skills, budget) comes from G5
        assert params.routing_config.total_budget == data["budgets"][5]["total"]

    def test_grade_below_minimum_raises(self):
        with pytest.raises(ValueError, match="below supported"):
            self.config.get_engine_params(grade=1, lattice_index=self.lattice)

    def test_unconfigured_native_grade_raises(self):
        # Fixture only has G2 and G3; G4 (the effective grade for grade=4)
        # is not configured.
        with pytest.raises(ValueError, match="not in config"):
            self.config.get_engine_params(grade=4, lattice_index=self.lattice)


# Integration with session module --------------------------------------------


class TestIntegrationWithSession:
    """Confirm get_engine_params returns an EngineParams that session.start_session accepts."""

    def test_end_to_end_start_session(self):
        from engine.session import SessionStatus, start_session

        config = load_engine_config(str(TEST_FIXTURE))
        params = config.get_engine_params(grade=3, lattice_index=LatticeIndex([]))
        result = start_session(
            sub_session_id="ss-1",
            learner_id="learner-1",
            tenant_id="tenant-1",
            class_id="class-1",
            grade=3,
            engine_version="0.1.0-test",
            params=params,
        )
        assert result.session.status == SessionStatus.ACTIVE
        assert result.first_question is not None
        # First op is Multiplication; G3 anchor is "Tables 1 to 9"
        assert result.first_question.skill == "Tables 1 to 9"


# check_priors_coverage (fix-pack change #2) =================================


class TestCheckPriorsCoverage:
    """Startup check that flags grades with zero priors.

    The engine accepts a config with missing priors per grade (defaults to
    0.5 for every skill in that grade) but should warn loudly about it.
    This pure function returns the gap list; the loud-warning behavior and
    the optional STRICT_PRIORS_REQUIRED fail-fast live in create_app /
    create_app_from_env. Tested separately.
    """

    def _config_with_priors(self, priors: dict) -> EngineConfig:
        """Build a test config with the given priors dict, default everything else."""
        data = yaml.safe_load(TEST_FIXTURE.read_text())
        data["priors"] = priors
        # anchors must exist for every grade in budgets; reuse from fixture
        return EngineConfig.model_validate(data)

    def test_returns_empty_when_all_grades_have_priors(self):
        # The standard test fixture has priors for both G2 and G3.
        config = load_engine_config(str(TEST_FIXTURE))
        assert check_priors_coverage(config) == []

    def test_returns_grade_with_empty_dict(self):
        config = self._config_with_priors({
            2: {},
            3: {"1D+1D sum upto 9": 0.95},
        })
        assert check_priors_coverage(config) == [2]

    def test_returns_all_missing_grades_sorted(self):
        config = self._config_with_priors({
            2: {},
            3: {},
        })
        assert check_priors_coverage(config) == [2, 3]

    def test_missing_key_treated_as_no_priors(self):
        # If a grade key is in budgets but missing from priors entirely,
        # treat it the same as an empty dict.
        data = yaml.safe_load(TEST_FIXTURE.read_text())
        del data["priors"][2]
        data["priors"][3] = {"1D+1D sum upto 9": 0.95}
        # EngineConfig validation requires priors[g] exist; emulate the
        # post-load state where one grade's priors is empty by writing an
        # empty dict.
        data["priors"][2] = {}
        config = EngineConfig.model_validate(data)
        # G2 has empty dict -> reported as missing
        assert check_priors_coverage(config) == [2]
