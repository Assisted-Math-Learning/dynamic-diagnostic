"""Unit tests for engine.cleanup."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from engine.cleanup import CleanupResult, run_cleanup
from engine.config import EngineConfig, load_engine_config
from engine.lattice import LatticeIndex
from engine.session import (
    RoutingMode,
    Session,
    SessionStatus,
    SkillVerdict,
)
from engine.storage.memory import InMemoryStorage
from engine.verdicts import ConfidenceLabel, Recommendation

TEST_FIXTURE = Path(__file__).parent / "fixtures" / "engine_config_test.yaml"


@pytest.fixture
def config() -> EngineConfig:
    return load_engine_config(str(TEST_FIXTURE))


@pytest.fixture
def lattice() -> LatticeIndex:
    return LatticeIndex([])


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


def _make_complete_session(
    *,
    sub_session_id: str,
    grade: int = 3,
    skill: str = "Tables 1 to 9",
    posterior: float = 0.97,
) -> Session:
    """Build a Session in COMPLETE status with one mastered skill."""
    return Session(
        sub_session_id=sub_session_id,
        learner_id="l1",
        tenant_id="t1",
        class_id="c1",
        grade=grade,
        status=SessionStatus.COMPLETE,
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        engine_version="0.1.0",
        posteriors={skill: posterior},
        direct_obs_count={skill: 3},
        questions_per_operation={},
        question_history=[],
        routing_mode_counts={RoutingMode.ONLINE: 3},
    )


class TestRunCleanup:
    def test_no_sessions_returns_zero_counts(self, storage, config, lattice):
        """Empty storage -> CleanupResult with all zeros."""
        result = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert result.sessions_examined == 0
        assert result.sessions_recovered == 0
        assert result.sessions_failed == 0
        assert result.all_successful is True

    def test_active_sessions_are_ignored(self, storage, config, lattice):
        """A session in ACTIVE status is not eligible for cleanup."""
        sess = _make_complete_session(sub_session_id="ss-active")
        sess.status = SessionStatus.ACTIVE
        storage.save_session(sess)
        result = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert result.sessions_examined == 0
        # No verdicts written because the session was never examined.
        assert storage.get_verdicts("ss-active") == []

    def test_complete_session_with_verdicts_already_persisted_is_ignored(
        self, storage, config, lattice,
    ):
        """A complete session whose verdicts already exist is not re-recovered."""
        sess = _make_complete_session(sub_session_id="ss-done")
        storage.save_session(sess)
        # Pre-existing verdict from the live run.
        storage.save_verdicts(sess, [SkillVerdict(
            skill_id="Tables 1 to 9",
            operation="Multiplication",
            posterior=0.97,
            direct_observations=3,
            propagation_updates=0,
            confidence_label=ConfidenceLabel.CONFIDENT_MASTERED,
            recommendation=Recommendation.SKIP_MAIND,
        )])
        result = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert result.sessions_examined == 0
        # Pre-existing verdict still present, unchanged.
        verdicts = storage.get_verdicts("ss-done")
        assert len(verdicts) == 1

    def test_complete_session_without_verdicts_gets_recovered(
        self, storage, config, lattice,
    ):
        """The core case: COMPLETE session, no verdicts -> verdicts written."""
        sess = _make_complete_session(sub_session_id="ss-partial")
        storage.save_session(sess)
        assert storage.get_verdicts("ss-partial") == []

        result = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert result.sessions_examined == 1
        assert result.sessions_recovered == 1
        assert result.sessions_failed == 0
        assert result.all_successful is True

        verdicts = storage.get_verdicts("ss-partial")
        # One verdict per skill in scope for grade 3
        assert len(verdicts) > 0
        # The skill we set to 0.97 should be confident_mastered
        skill_verdict = next(
            v for v in verdicts if v.skill_id == "Tables 1 to 9"
        )
        assert skill_verdict.confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert skill_verdict.recommendation == Recommendation.SKIP_MAIND

    def test_idempotent_second_run(self, storage, config, lattice):
        """Running cleanup again after recovery finds nothing to do."""
        sess = _make_complete_session(sub_session_id="ss-partial")
        storage.save_session(sess)
        first = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert first.sessions_recovered == 1
        second = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert second.sessions_examined == 0
        assert second.sessions_recovered == 0

    def test_per_session_failure_is_isolated(self, storage, config, lattice):
        """A failure on one session doesn't stop the rest from being recovered."""
        good = _make_complete_session(sub_session_id="ss-good", grade=3)
        # Set grade to 99 - get_engine_params will fail because there's no
        # config for grade 99, simulating any per-session compute failure.
        bad = _make_complete_session(sub_session_id="ss-bad", grade=3)
        bad.grade = 99  # bypasses any validation; storage stores it
        storage.save_session(good)
        storage.save_session(bad)

        result = run_cleanup(
            storage=storage, config=config, lattice_index=lattice,
        )
        assert result.sessions_examined == 2
        assert result.sessions_recovered == 1
        assert result.sessions_failed == 1
        assert result.all_successful is False
        # The good one got verdicts; the bad one did not
        assert storage.get_verdicts("ss-good") != []
        assert storage.get_verdicts("ss-bad") == []

    def test_limit_caps_sessions_per_run(self, storage, config, lattice):
        """--limit caps how many sessions a single run processes."""
        for i in range(5):
            sess = _make_complete_session(sub_session_id=f"ss-{i}")
            storage.save_session(sess)
        result = run_cleanup(
            storage=storage, config=config, lattice_index=lattice, limit=2,
        )
        assert result.sessions_examined == 2
        assert result.sessions_recovered == 2

        # Remaining 3 are picked up on next run
        result2 = run_cleanup(
            storage=storage, config=config, lattice_index=lattice, limit=100,
        )
        assert result2.sessions_examined == 3


class TestCleanupResult:
    def test_all_successful_when_no_failures(self):
        r = CleanupResult(sessions_examined=5, sessions_recovered=5, sessions_failed=0)
        assert r.all_successful is True

    def test_not_successful_when_any_failure(self):
        r = CleanupResult(sessions_examined=5, sessions_recovered=4, sessions_failed=1)
        assert r.all_successful is False

    def test_all_successful_on_empty(self):
        r = CleanupResult(sessions_examined=0, sessions_recovered=0, sessions_failed=0)
        assert r.all_successful is True


class TestCleanupMetrics:
    """run_cleanup increments the spec section 9.1 cleanup counters when given
    an EngineMetrics (fix: previously defined-but-never-incremented)."""

    def _metrics(self):
        from prometheus_client import CollectorRegistry
        from engine.observability.metrics import register_metrics
        registry = CollectorRegistry()
        return registry, register_metrics(registry)

    def _counter_value(self, registry, name, labels=None):
        v = registry.get_sample_value(name, labels or {})
        return v if v is not None else 0.0

    def test_runs_total_increments_success_on_clean_run(self, storage, config, lattice):
        sess = _make_complete_session(sub_session_id="ss-1")
        storage.save_session(sess)
        registry, metrics = self._metrics()
        run_cleanup(storage=storage, config=config, lattice_index=lattice, metrics=metrics)
        # outcome="success" because all examined sessions recovered
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_runs_total", {"outcome": "success"}
        ) == 1.0
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_runs_total", {"outcome": "error"}
        ) == 0.0

    def test_recovered_sessions_counter_reflects_count(self, storage, config, lattice):
        for i in range(3):
            storage.save_session(_make_complete_session(sub_session_id=f"ss-{i}"))
        registry, metrics = self._metrics()
        run_cleanup(storage=storage, config=config, lattice_index=lattice, metrics=metrics)
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_recovered_sessions_total"
        ) == 3.0

    def test_runs_total_increments_error_when_a_session_fails(self, storage, config, lattice):
        good = _make_complete_session(sub_session_id="ss-good")
        bad = _make_complete_session(sub_session_id="ss-bad")
        bad.grade = 99  # no config for grade 99 -> per-session failure
        storage.save_session(good)
        storage.save_session(bad)
        registry, metrics = self._metrics()
        run_cleanup(storage=storage, config=config, lattice_index=lattice, metrics=metrics)
        # outcome="error" because at least one session failed
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_runs_total", {"outcome": "error"}
        ) == 1.0
        # the one good session still counts as recovered
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_recovered_sessions_total"
        ) == 1.0

    def test_no_metrics_object_is_a_noop(self, storage, config, lattice):
        """Passing no metrics (the default) must not raise."""
        storage.save_session(_make_complete_session(sub_session_id="ss-1"))
        # Should complete without error and without touching any registry.
        result = run_cleanup(storage=storage, config=config, lattice_index=lattice)
        assert result.sessions_recovered == 1

    def test_empty_run_increments_success_with_zero_recovered(self, storage, config, lattice):
        registry, metrics = self._metrics()
        run_cleanup(storage=storage, config=config, lattice_index=lattice, metrics=metrics)
        # No sessions found is still a successful run.
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_runs_total", {"outcome": "success"}
        ) == 1.0
        # Recovered counter never incremented (stays at 0 / absent).
        assert self._counter_value(
            registry, "diagnostic_cleanup_job_recovered_sessions_total"
        ) == 0.0


class TestCleanupPushgateway:
    """The CLI pushes the cleanup registry to a Pushgateway when configured."""

    def test_push_skipped_when_env_unset(self, monkeypatch):
        from prometheus_client import CollectorRegistry
        from engine.cli import _push_cleanup_metrics
        monkeypatch.delenv("PROMETHEUS_PUSHGATEWAY_URL", raising=False)
        # Should simply return without attempting a push (no exception).
        _push_cleanup_metrics(CollectorRegistry())

    def test_push_called_when_env_set(self, monkeypatch):
        import engine.cli as cli_mod
        from prometheus_client import CollectorRegistry
        monkeypatch.setenv("PROMETHEUS_PUSHGATEWAY_URL", "pushgw.test:9091")
        calls = {}

        def _fake_push(gateway, job, registry):
            calls["gateway"] = gateway
            calls["job"] = job

        # push_to_gateway is imported inside the function from prometheus_client
        monkeypatch.setattr("prometheus_client.push_to_gateway", _fake_push)
        cli_mod._push_cleanup_metrics(CollectorRegistry())
        assert calls["gateway"] == "pushgw.test:9091"
        assert calls["job"] == "engine_cleanup"

    def test_push_failure_does_not_raise(self, monkeypatch):
        import engine.cli as cli_mod
        from prometheus_client import CollectorRegistry
        monkeypatch.setenv("PROMETHEUS_PUSHGATEWAY_URL", "unreachable:9091")

        def _boom(gateway, job, registry):
            raise ConnectionError("gateway unreachable")

        monkeypatch.setattr("prometheus_client.push_to_gateway", _boom)
        # Must swallow the error (cleanup work already done); no raise.
        cli_mod._push_cleanup_metrics(CollectorRegistry())
