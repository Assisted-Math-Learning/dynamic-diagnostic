"""Tests for storage backends.

The same behavioural tests run against both the in-memory backend and the
MongoDB backend (using mongomock as a stand-in for a real MongoDB instance).
Parameterising the fixture catches behavioural drift between implementations.
"""

from datetime import datetime, timezone

import mongomock
import pytest

from engine.lattice import LatticeEdge
from engine.routing import Purpose
from engine.session import (
    QuestionHistoryEntry,
    RoutingMode,
    Session,
    SessionStatus,
    SkillVerdict,
)
from engine.storage.interface import StorageBackend
from engine.storage.memory import InMemoryStorage
from engine.storage.mongodb import MongoStorage
from engine.verdicts import ConfidenceLabel, Recommendation


# Parametrise across both backends -------------------------------------------


@pytest.fixture(params=["memory", "mongodb"])
def storage(request) -> StorageBackend:
    if request.param == "memory":
        return InMemoryStorage()
    if request.param == "mongodb":
        # Fresh in-memory MongoDB per test (via mongomock).
        return MongoStorage(
            mongo_client=mongomock.MongoClient(),
            database_name="test_engine",
            create_indexes=True,
        )
    raise ValueError(f"unknown backend: {request.param}")


# Fixture builders -----------------------------------------------------------


def make_session(
    sub_session_id: str = "ss-1",
    status: SessionStatus = SessionStatus.ACTIVE,
) -> Session:
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    return Session(
        sub_session_id=sub_session_id,
        learner_id="learner-1",
        tenant_id="tenant-1",
        class_id="class-1",
        grade=3,
        status=status,
        started_at=now,
        ended_at=None,
        engine_version="0.1.0-test",
        posteriors={"skill_a": 0.7, "skill_b": 0.3},
        direct_obs_count={"skill_a": 1, "skill_b": 0},
        questions_per_operation={"Addition": 1},
        question_history=[
            QuestionHistoryEntry(
                sequence=1, question_id="q1", skill_id="skill_a",
                is_correct=True, asked_at=now,
                posterior_before=0.5, posterior_after=0.7,
                purpose=Purpose.ANCHOR, routing_mode=RoutingMode.ONLINE,
            )
        ],
        routing_mode_counts={RoutingMode.ONLINE: 1, RoutingMode.OFFLINE_REPLAY: 0},
    )


def make_verdict(skill_id: str = "skill_a") -> SkillVerdict:
    return SkillVerdict(
        skill_id=skill_id,
        operation="Addition",
        posterior=0.97,
        direct_observations=3,
        propagation_updates=0,
        confidence_label=ConfidenceLabel.CONFIDENT_MASTERED,
        recommendation=Recommendation.SKIP_MAIND,
    )


def make_edge(skill_a: str = "A", skill_b: str = "B") -> LatticeEdge:
    return LatticeEdge(
        skill_a=skill_a, skill_b=skill_b,
        operation_a="Addition", operation_b="Addition",
        p_b_given_a=0.9, p_b_given_not_a=0.3, weight=1.0,
    )


# Tests ----------------------------------------------------------------------


class TestSessionRoundTrip:
    def test_save_and_get(self, storage: StorageBackend):
        sess = make_session()
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        assert fetched is not None
        assert fetched.sub_session_id == "ss-1"
        assert fetched.learner_id == "learner-1"
        assert fetched.tenant_id == "tenant-1"
        assert fetched.grade == 3
        assert fetched.status == SessionStatus.ACTIVE
        assert fetched.posteriors == {"skill_a": 0.7, "skill_b": 0.3}
        assert fetched.direct_obs_count == {"skill_a": 1, "skill_b": 0}
        assert fetched.questions_per_operation == {"Addition": 1}
        assert fetched.routing_mode_counts == {
            RoutingMode.ONLINE: 1, RoutingMode.OFFLINE_REPLAY: 0,
        }

    def test_question_history_round_trip(self, storage: StorageBackend):
        sess = make_session()
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        assert len(fetched.question_history) == 1
        entry = fetched.question_history[0]
        assert entry.sequence == 1
        assert entry.question_id == "q1"
        assert entry.skill_id == "skill_a"
        assert entry.is_correct is True
        assert entry.purpose == Purpose.ANCHOR
        assert entry.routing_mode == RoutingMode.ONLINE
        assert entry.posterior_before == 0.5
        assert entry.posterior_after == 0.7

    def test_get_missing_returns_none(self, storage: StorageBackend):
        assert storage.get_session("nonexistent") is None

    def test_session_exists(self, storage: StorageBackend):
        assert storage.session_exists("ss-1") is False
        storage.save_session(make_session())
        assert storage.session_exists("ss-1") is True

    def test_save_overwrites(self, storage: StorageBackend):
        sess = make_session()
        storage.save_session(sess)
        sess.status = SessionStatus.COMPLETE
        sess.ended_at = datetime(2026, 5, 26, 13, 0, 0, tzinfo=timezone.utc)
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        assert fetched.status == SessionStatus.COMPLETE
        assert fetched.ended_at is not None

    def test_get_returns_independent_copy(self, storage: StorageBackend):
        # Mutating the returned object must not affect storage state.
        storage.save_session(make_session())
        first = storage.get_session("ss-1")
        first.posteriors["skill_a"] = 0.99
        first.status = SessionStatus.COMPLETE
        second = storage.get_session("ss-1")
        assert second.posteriors["skill_a"] == 0.7
        assert second.status == SessionStatus.ACTIVE

    def test_save_is_immune_to_external_mutation(self, storage: StorageBackend):
        # The in-memory backend deep-copies on save; the MongoDB backend
        # serialises. Either way, mutating the input after save_session must
        # not affect storage state.
        sess = make_session()
        storage.save_session(sess)
        sess.posteriors["skill_a"] = 0.99
        fetched = storage.get_session("ss-1")
        assert fetched.posteriors["skill_a"] == 0.7

    def test_pending_question_round_trip(self, storage: StorageBackend):
        """Spec section 7.7 per-item overrides require pending_* to round-trip through storage."""
        sess = make_session()
        sess.pending_question_id = "q-next"
        sess.pending_question_slip_override = 0.07
        sess.pending_question_guess_override = 0.11
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        assert fetched.pending_question_id == "q-next"
        assert fetched.pending_question_slip_override == 0.07
        assert fetched.pending_question_guess_override == 0.11

    def test_pending_question_absent_round_trips_as_none(self, storage: StorageBackend):
        """A session with no pending_* state should round-trip cleanly (all None)."""
        sess = make_session()
        # pending_* default to None on a fresh make_session()
        assert sess.pending_question_id is None
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        assert fetched.pending_question_id is None
        assert fetched.pending_question_slip_override is None
        assert fetched.pending_question_guess_override is None

    def test_propagation_updates_count_round_trip(self, storage: StorageBackend):
        """Spec section 6.1: per-skill propagation_updates is required on
        the posteriors nested sub-document. Used by spec section 7.6 to
        separate priors-only from propagation-only resolutions."""
        sess = make_session()
        sess.propagation_updates_count = {"skill_a": 2, "skill_b": 1}
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        assert fetched.propagation_updates_count["skill_a"] == 2
        assert fetched.propagation_updates_count["skill_b"] == 1

    def test_propagation_updates_count_empty_defaults_to_zero(self, storage: StorageBackend):
        """Skills with no propagation events should not appear in the counter
        (or round-trip as 0). compute_verdicts uses .get(skill, 0)."""
        sess = make_session()
        # make_session leaves propagation_updates_count empty by default.
        assert sess.propagation_updates_count == {}
        storage.save_session(sess)
        fetched = storage.get_session("ss-1")
        # Skills present in posteriors but with no propagation events get
        # 0 from the nested sub-doc.
        for skill in fetched.posteriors:
            assert fetched.propagation_updates_count.get(skill, 0) == 0

    def test_last_updated_at_uses_question_history_per_skill(self, storage: StorageBackend):
        """Spec section 6.1 last_updated_at per skill walks question_history,
        not session.started_at (fix-pack #10)."""
        from engine.storage.documents import session_to_doc

        sess = make_session()
        # Use a deterministic clock so we can assert exact values.
        ask_a = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ask_b = datetime(2026, 1, 15, 10, 5, 0, tzinfo=timezone.utc)
        sess.question_history = [
            QuestionHistoryEntry(
                sequence=1, skill_id="skill_a", question_id="q1",
                is_correct=True, asked_at=ask_a,
                posterior_before=0.5, posterior_after=0.857,
                purpose=Purpose.ANCHOR, routing_mode=RoutingMode.ONLINE,
            ),
            QuestionHistoryEntry(
                sequence=2, skill_id="skill_b", question_id="q2",
                is_correct=False, asked_at=ask_b,
                posterior_before=0.5, posterior_after=0.143,
                purpose=Purpose.ANCHOR, routing_mode=RoutingMode.ONLINE,
            ),
        ]
        doc = session_to_doc(sess)
        # skill_a's last_updated_at matches its most recent ask time
        assert doc["posteriors"]["skill_a"]["last_updated_at"] == ask_a
        # skill_b's likewise
        assert doc["posteriors"]["skill_b"]["last_updated_at"] == ask_b

    def test_last_updated_at_falls_back_to_started_at_for_never_asked(self, storage: StorageBackend):
        """Skills never directly asked use session.started_at as last_updated_at."""
        from engine.storage.documents import session_to_doc

        sess = make_session()
        # Strip any pre-populated history so no skill is "directly asked".
        sess.question_history = []
        doc = session_to_doc(sess)
        for skill in sess.posteriors:
            assert doc["posteriors"][skill]["last_updated_at"] == sess.started_at

    def test_last_updated_at_uses_most_recent_when_skill_asked_twice(self, storage: StorageBackend):
        """If a skill appears multiple times in question_history, last_updated_at
        is the timestamp of the MOST RECENT ask."""
        from engine.storage.documents import session_to_doc

        sess = make_session()
        first = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        second = datetime(2026, 1, 15, 10, 10, 0, tzinfo=timezone.utc)
        sess.question_history = [
            QuestionHistoryEntry(
                sequence=1, skill_id="skill_a", question_id="q1",
                is_correct=True, asked_at=first,
                posterior_before=0.5, posterior_after=0.857,
                purpose=Purpose.ANCHOR, routing_mode=RoutingMode.ONLINE,
            ),
            QuestionHistoryEntry(
                sequence=2, skill_id="skill_a", question_id="q2",
                is_correct=True, asked_at=second,
                posterior_before=0.857, posterior_after=0.97,
                purpose=Purpose.VERIFICATION, routing_mode=RoutingMode.ONLINE,
            ),
        ]
        doc = session_to_doc(sess)
        assert doc["posteriors"]["skill_a"]["last_updated_at"] == second


class TestVerdictRoundTrip:
    def test_save_and_get(self, storage: StorageBackend):
        sess = make_session()
        storage.save_session(sess)
        verdicts = [
            make_verdict("skill_a"),
            SkillVerdict(
                skill_id="skill_b", operation="Addition",
                posterior=0.05, direct_observations=2,
                propagation_updates=0,
                confidence_label=ConfidenceLabel.CONFIDENT_NOT_MASTERED,
                recommendation=Recommendation.TAKE_MAIND_DIAGNOSTIC,
            ),
        ]
        storage.save_verdicts(sess, verdicts)
        fetched = storage.get_verdicts("ss-1")
        assert len(fetched) == 2
        by_skill = {v.skill_id: v for v in fetched}
        assert by_skill["skill_a"].confidence_label == ConfidenceLabel.CONFIDENT_MASTERED
        assert by_skill["skill_a"].recommendation == Recommendation.SKIP_MAIND
        assert by_skill["skill_a"].operation == "Addition"
        assert by_skill["skill_b"].confidence_label == ConfidenceLabel.CONFIDENT_NOT_MASTERED

    def test_get_missing_returns_empty(self, storage: StorageBackend):
        assert storage.get_verdicts("nonexistent") == []

    def test_save_verdicts_is_idempotent_replace(self, storage: StorageBackend):
        # Calling save_verdicts twice should not duplicate rows.
        sess = make_session()
        storage.save_session(sess)
        storage.save_verdicts(sess, [make_verdict("skill_a")])
        storage.save_verdicts(sess, [make_verdict("skill_a"), make_verdict("skill_b")])
        fetched = storage.get_verdicts("ss-1")
        assert len(fetched) == 2

    def test_empty_verdicts_save_is_noop(self, storage: StorageBackend):
        sess = make_session()
        storage.save_session(sess)
        storage.save_verdicts(sess, [])
        assert storage.get_verdicts("ss-1") == []


class TestLatticeEdges:
    def test_save_and_load(self, storage: StorageBackend):
        storage.save_lattice_edges([make_edge("A", "B"), make_edge("B", "C")])
        loaded = storage.load_lattice_edges()
        assert len(loaded) == 2
        by_a = {e.skill_a: e for e in loaded}
        assert by_a["A"].skill_b == "B"
        assert by_a["B"].skill_b == "C"

    def test_save_replaces_existing(self, storage: StorageBackend):
        storage.save_lattice_edges([make_edge("A", "B")])
        storage.save_lattice_edges([make_edge("X", "Y")])
        loaded = storage.load_lattice_edges()
        assert len(loaded) == 1
        assert loaded[0].skill_a == "X"

    def test_load_empty(self, storage: StorageBackend):
        assert storage.load_lattice_edges() == []

    def test_edge_attributes_preserved(self, storage: StorageBackend):
        edge = LatticeEdge(
            skill_a="A", skill_b="B",
            operation_a="Multiplication", operation_b="Addition",
            p_b_given_a=0.77, p_b_given_not_a=0.33, weight=0.5,
        )
        storage.save_lattice_edges([edge])
        loaded = storage.load_lattice_edges()
        assert len(loaded) == 1
        e = loaded[0]
        assert e.operation_a == "Multiplication"
        assert e.operation_b == "Addition"
        assert e.p_b_given_a == 0.77
        assert e.p_b_given_not_a == 0.33
        assert e.weight == 0.5


class TestCleanupQuery:
    def test_returns_complete_without_verdicts(self, storage: StorageBackend):
        # A: complete, no verdicts -> should be returned
        a = make_session("ss-A", SessionStatus.COMPLETE)
        storage.save_session(a)
        # B: complete, has verdicts -> should NOT be returned
        b = make_session("ss-B", SessionStatus.COMPLETE)
        storage.save_session(b)
        storage.save_verdicts(b, [make_verdict()])
        # C: active -> should NOT be returned
        c = make_session("ss-C", SessionStatus.ACTIVE)
        storage.save_session(c)
        # D: abandoned -> should NOT be returned (only COMPLETE is recoverable)
        d = make_session("ss-D", SessionStatus.ABANDONED)
        storage.save_session(d)

        found = storage.find_complete_sessions_without_verdicts()
        found_ids = {s.sub_session_id for s in found}
        assert "ss-A" in found_ids
        assert "ss-B" not in found_ids
        assert "ss-C" not in found_ids
        assert "ss-D" not in found_ids

    def test_limit_is_honored(self, storage: StorageBackend):
        for i in range(5):
            sess = make_session(f"ss-{i}", SessionStatus.COMPLETE)
            storage.save_session(sess)
        found = storage.find_complete_sessions_without_verdicts(limit=3)
        assert len(found) == 3

    def test_no_complete_sessions_returns_empty(self, storage: StorageBackend):
        storage.save_session(make_session("ss-active", SessionStatus.ACTIVE))
        assert storage.find_complete_sessions_without_verdicts() == []


class TestHealthCheck:
    def test_passes_for_reachable_backend(self, storage: StorageBackend):
        assert storage.health_check() is True


# Factory --------------------------------------------------------------------


class TestStorageFactory:
    def test_default_returns_memory(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        from engine.storage import get_storage_backend

        s = get_storage_backend()
        assert isinstance(s, InMemoryStorage)

    def test_explicit_memory(self):
        from engine.storage import get_storage_backend

        s = get_storage_backend(backend="memory")
        assert isinstance(s, InMemoryStorage)

    def test_explicit_mongodb_with_client(self):
        from engine.storage import get_storage_backend

        s = get_storage_backend(
            backend="mongodb",
            mongo_client=mongomock.MongoClient(),
            database_name="test",
        )
        assert isinstance(s, MongoStorage)

    def test_env_var_picked_up(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        from engine.storage import get_storage_backend

        s = get_storage_backend()
        assert isinstance(s, InMemoryStorage)

    def test_unknown_backend_raises(self):
        from engine.storage import get_storage_backend

        with pytest.raises(ValueError, match="unknown STORAGE_BACKEND"):
            get_storage_backend(backend="postgres")

    # === Env-var bridge (fix-pack change #1) ================================
    #
    # Spec section 10.3 and the README document MONGODB_URL and
    # MONGODB_DATABASE as env vars the engine reads. Before this fix, the
    # storage factory ignored them, causing STORAGE_BACKEND=mongodb to fail
    # at startup with "either mongo_url or mongo_client must be provided".
    # These tests exercise the env-var bridge.

    def test_mongodb_backend_picks_up_env_vars(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """STORAGE_BACKEND=mongodb + MONGODB_URL + MONGODB_DATABASE => constructs MongoStorage."""
        # Patch MongoClient inside mongodb.py so the connection is in-memory
        # (mongomock) and the test doesn't try to dial a real server.
        monkeypatch.setattr(
            "engine.storage.mongodb.MongoClient", mongomock.MongoClient,
        )
        monkeypatch.setenv("STORAGE_BACKEND", "mongodb")
        monkeypatch.setenv("MONGODB_URL", "mongodb://test-host:27017")
        monkeypatch.setenv("MONGODB_DATABASE", "test_db_from_env")

        from engine.storage import get_storage_backend
        s = get_storage_backend()
        assert isinstance(s, MongoStorage)
        # The env-var database_name made it through the bridge into MongoStorage
        assert s._db.name == "test_db_from_env"

    def test_mongodb_backend_defaults_database_name_when_unset(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """If MONGODB_DATABASE is unset but MONGODB_URL is set, default to 'aml_engine'."""
        monkeypatch.setattr(
            "engine.storage.mongodb.MongoClient", mongomock.MongoClient,
        )
        monkeypatch.setenv("STORAGE_BACKEND", "mongodb")
        monkeypatch.setenv("MONGODB_URL", "mongodb://test-host:27017")
        monkeypatch.delenv("MONGODB_DATABASE", raising=False)

        from engine.storage import get_storage_backend
        s = get_storage_backend()
        assert s._db.name == "aml_engine"

    def test_mongodb_backend_missing_url_raises_clean_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """STORAGE_BACKEND=mongodb with no MONGODB_URL must raise a clear, operator-friendly error."""
        monkeypatch.setenv("STORAGE_BACKEND", "mongodb")
        monkeypatch.delenv("MONGODB_URL", raising=False)

        from engine.storage import get_storage_backend
        with pytest.raises(ValueError, match="MONGODB_URL"):
            get_storage_backend()

    def test_explicit_mongo_url_kwarg_overrides_env_var(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """An explicit mongo_url kwarg wins over MONGODB_URL env var."""
        monkeypatch.setattr(
            "engine.storage.mongodb.MongoClient", mongomock.MongoClient,
        )
        monkeypatch.setenv("STORAGE_BACKEND", "mongodb")
        monkeypatch.setenv("MONGODB_URL", "mongodb://from-env:27017")
        monkeypatch.setenv("MONGODB_DATABASE", "from_env_db")

        from engine.storage import get_storage_backend
        s = get_storage_backend(
            backend="mongodb",
            mongo_client=mongomock.MongoClient(),  # explicit client wins
            database_name="explicit_db",            # explicit name wins
        )
        # Confirm explicit kwargs were used, not env vars
        assert s._db.name == "explicit_db"
