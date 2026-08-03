"""Checkpoint 1 of the misconception-coverage layer: the session ledger,
applicability computation, answer-time counter updates, and storage round-trip.

At this checkpoint the ledger is *populated but not acted on* (no opportunistic
pick, no backfill), so these tests only assert that state is tracked correctly
and persists; selection behaviour is unchanged (guarded by the rest of the suite
and the smoke).
"""

from pathlib import Path

from tests import DATA_DIR

import pytest

from engine.misconception import MISCONCEPTIONS, MISCONCEPTION_SET
from engine.question_pool import CsvQuestionPool
from engine.session import record_response

from tests.test_question_pool import row, write_csv, write_lookup, make_session

# Reuse the storage round-trip helpers if present; import lazily in the test.


# --- the canonical list ----------------------------------------------------


def test_misconceptions_are_eleven_unique():
    assert len(MISCONCEPTIONS) == 11
    assert len(MISCONCEPTION_SET) == 11
    assert set(MISCONCEPTIONS) == MISCONCEPTION_SET


# --- applicability (synthetic) ---------------------------------------------


class TestApplicability:
    def _pool(self, tmp_path, lookup_rows):
        params = write_csv(tmp_path / "p.csv", [
            row("A|q1", "qp1", "SkillA", "all", 0.80),
            row("A|q2", "qp2", "SkillA", "all", 0.80),
            row("B|q1", "qp3", "SkillB", "all", 0.80),
        ])
        lookup = write_lookup(tmp_path / "lk.csv", lookup_rows)
        return CsvQuestionPool(params, lookup_path=lookup, seed=1)

    def test_applicable_is_union_of_served_tags(self, tmp_path):
        pool = self._pool(tmp_path, [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_minus_x": 1},
            {"tenant": "Delhi", "item": "B|q1", "question_x_id": "d3", "x_into_x": 1},
        ])
        app = pool.applicable_misconceptions("Delhi", 5, ["SkillA", "SkillB"])
        assert app == {"x_plus_0", "x_minus_x", "x_into_x"}

    def test_out_of_scope_skill_excluded(self, tmp_path):
        pool = self._pool(tmp_path, [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
            {"tenant": "Delhi", "item": "B|q1", "question_x_id": "d3", "x_into_x": 1},
        ])
        # Only SkillA in scope -> B's x_into_x is not applicable.
        app = pool.applicable_misconceptions("Delhi", 5, ["SkillA"])
        assert app == {"x_plus_0"}

    def test_tenant_availability_excludes_other_tenants_items(self, tmp_path):
        pool = self._pool(tmp_path, [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
            {"tenant": "Karnataka", "item": "A|q2", "question_x_id": "k2", "x_minus_x": 1},
        ])
        # Delhi cannot serve A|q2, so x_minus_x is not applicable for Delhi.
        assert pool.applicable_misconceptions("Delhi", 5, ["SkillA"]) == {"x_plus_0"}
        assert pool.applicable_misconceptions("Karnataka", 5, ["SkillA"]) == {"x_minus_x"}

    def test_grade_resolvability_excludes_unresolvable_items(self, tmp_path):
        # A|q1 has a grade-3-only row; at grade 2 it does not resolve.
        params = write_csv(tmp_path / "p.csv", [
            row("A|q1", "qp1", "SkillA", "3", 0.80),
            row("A|q2", "qp2", "SkillA", "all", 0.80),
        ])
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_minus_x": 1},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        # At grade 2: A|q1 (grade-3 only) unresolvable -> x_plus_0 not applicable.
        assert pool.applicable_misconceptions("Delhi", 2, ["SkillA"]) == {"x_minus_x"}
        # At grade 3: both resolve.
        assert pool.applicable_misconceptions("Delhi", 3, ["SkillA"]) == {
            "x_plus_0", "x_minus_x"}

    def test_legacy_mode_returns_empty(self, tmp_path):
        params = write_csv(tmp_path / "p.csv", [row("A|q1", "qp1", "SkillA", "all", 0.8)])
        pool = CsvQuestionPool(params, seed=1)  # no lookup
        assert pool.applicable_misconceptions("Delhi", 5, ["SkillA"]) == set()


# --- applicability (real data: the audit's 7/8/11/11) ----------------------

# The lookup MUST share the seven-field key format of the params file: both
# carry the division-only seventh field (response_includes_remainder). A
# six-field lookup read against seven-field params silently fails the item-key
# join in CsvQuestionPool._resolve_row for every division item, so the four
# division misconceptions drop and applicability is under-counted (the
# {2:6,3:7,4:7,5:7} artifact). Read the engine's own seven-field lookup that
# this branch wires into inputs/, never a stale external copy.
_REAL_LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"
_REAL_PARAMS = DATA_DIR / "question_parameters.csv"


@pytest.mark.skipif(
    not (_REAL_LOOKUP.exists() and _REAL_PARAMS.exists()),
    reason="real calibration lookup / params not present in this environment",
)
def test_real_data_applicability_matches_audit():
    """Against the real pool + config, the per-grade applicable counts must match
    the coverage audit: G2=7, G3=8, G4=11, G5=11, and G2 tenant-invariant."""
    import sys
    sys.path.insert(0, "scripts")
    import smoke  # noqa: E402

    skills, priors, anchors, edges, _ = smoke.step_1_load_data(DATA_DIR)
    config = smoke.step_2_build_config(skills, priors, anchors)
    pool = CsvQuestionPool(str(_REAL_PARAMS), lookup_path=str(_REAL_LOOKUP), seed=1)

    def scope(grade):
        return [s.name for s in config.skills if s.content_grade <= grade]

    counts = {
        g: len(pool.applicable_misconceptions("Delhi", g, scope(g)))
        for g in (2, 3, 4, 5)
    }
    assert counts == {2: 7, 3: 8, 4: 11, 5: 11}, counts
    # G2 is tenant-invariant.
    for tenant in ("Delhi", "Karnataka", "Telangana", "Private"):
        assert len(pool.applicable_misconceptions(tenant, 2, scope(2))) == 7


@pytest.mark.skipif(
    not (_REAL_LOOKUP.exists() and _REAL_PARAMS.exists()),
    reason="real calibration lookup / params not present in this environment",
)
def test_real_data_end_to_end_ledger_populates():
    """Route glue: a real Delhi G3 session sets the applicable set at start and
    moves the asked/correct counters at answer-time, persisted across requests."""
    import sys
    sys.path.insert(0, "scripts")
    import smoke  # noqa: E402
    from engine.api.main import create_app
    from engine.storage.memory import InMemoryStorage
    from engine.lattice import LatticeIndex
    from fastapi.testclient import TestClient

    smoke.TENANT_ID = "Delhi"
    skills, priors, anchors, edges, qpath = smoke.step_1_load_data(DATA_DIR)
    config = smoke.step_2_build_config(skills, priors, anchors)
    storage = InMemoryStorage()
    storage.save_lattice_edges(edges)
    pool = CsvQuestionPool(str(qpath), expected_skills={s.name for s in config.skills},
                           seed=42, lookup_path=str(_REAL_LOOKUP))
    app = create_app(config=config, storage=storage, lattice_index=LatticeIndex(edges),
                     tenant_tokens={"Delhi": smoke.TOKEN}, engine_version="t",
                     question_pool=pool)
    client = TestClient(app)
    h = {"X-Internal-Service-Token": smoke.TOKEN}
    res = client.post("/api/v1/diagnostic/session/start", json={
        "learner_id": "L", "tenant_id": "Delhi", "sub_session_id": "S",
        "class_id": "C", "grade": 3}, headers=h).json()["result"]
    q, i = res["first_question"], 0
    while q is not None and i < 80:
        i += 1
        body = client.post("/api/v1/diagnostic/session/S/response", json={
            "learner_id": "L", "tenant_id": "Delhi", "skill_id": q["skill_id"],
            "question_x_id": q["question_x_id"], "is_correct": (i % 2 == 0)},
            headers=h).json()["result"]
        q = None if body["session_complete"] else body["next_question"]
    sess = storage.get_session("S")
    assert len(sess.misconception_applicable) == 8
    assert sum(sess.misconception_asked.values()) > 0
    # correct never exceeds asked, per tag
    for tag in MISCONCEPTIONS:
        assert sess.misconception_correct[tag] <= sess.misconception_asked[tag]


# --- answer-time ledger update ---------------------------------------------


class TestLedgerUpdate:
    def _params_and_session(self):
        from engine.session import start_session
        from tests.test_session import make_params

        params = make_params(grade=3)
        res = start_session(
            sub_session_id="s", learner_id="l", tenant_id="Delhi", class_id="c",
            grade=3, engine_version="t", params=params,
        )
        return params, res.session

    def test_counts_asked_and_correct_for_tagged_question(self, tmp_path):
        params, session = self._params_and_session()
        skill = params.skills_in_scope[0]
        session.pending_question_id = "qX"
        session.pending_question_misconceptions = {"x_plus_0": 1, "x_plus_x": 0}
        record_response(
            session=session, params=params, skill_id=skill,
            question_id="qX", is_correct=True,
        )
        assert session.misconception_asked["x_plus_0"] == 1
        assert session.misconception_correct["x_plus_0"] == 1
        # a tag with value 0 on the question is never counted
        assert session.misconception_asked["x_plus_x"] == 0
        # pending tags cleared after applying
        assert session.pending_question_misconceptions is None

    def test_wrong_answer_counts_asked_not_correct(self, tmp_path):
        params, session = self._params_and_session()
        skill = params.skills_in_scope[0]
        session.pending_question_id = "qX"
        session.pending_question_misconceptions = {"x_minus_x": 1}
        record_response(
            session=session, params=params, skill_id=skill,
            question_id="qX", is_correct=False,
        )
        assert session.misconception_asked["x_minus_x"] == 1
        assert session.misconception_correct["x_minus_x"] == 0

    def test_no_tags_no_update(self, tmp_path):
        params, session = self._params_and_session()
        skill = params.skills_in_scope[0]
        session.pending_question_id = "qX"
        session.pending_question_misconceptions = None  # legacy / untagged
        record_response(
            session=session, params=params, skill_id=skill,
            question_id="qX", is_correct=True,
        )
        assert all(v == 0 for v in session.misconception_asked.values())

    def test_replay_does_not_double_count(self, tmp_path):
        params, session = self._params_and_session()
        skill = params.skills_in_scope[0]
        session.pending_question_id = "qX"
        session.pending_question_misconceptions = {"x_plus_0": 1}
        record_response(session=session, params=params, skill_id=skill,
                        question_id="qX", is_correct=True)
        # Same question_id + same is_correct = idempotent replay; no second count.
        record_response(session=session, params=params, skill_id=skill,
                        question_id="qX", is_correct=True)
        assert session.misconception_asked["x_plus_0"] == 1
        assert session.misconception_correct["x_plus_0"] == 1


# --- storage round-trip ----------------------------------------------------


def test_ledger_survives_storage_round_trip():
    from engine.storage.documents import session_to_doc, doc_to_session
    from engine.session import start_session
    from tests.test_session import make_params

    params = make_params(grade=3)
    session = start_session(
        sub_session_id="s", learner_id="l", tenant_id="Delhi", class_id="c",
        grade=3, engine_version="t", params=params,
    ).session
    session.misconception_applicable = {"x_plus_0", "x_minus_x"}
    session.misconception_asked["x_plus_0"] = 2
    session.misconception_correct["x_plus_0"] = 1
    # Pending tags are always stashed together with a pending question id (the
    # route sets them together); mirror that so the nested pending_question doc
    # is written.
    session.pending_question_id = "qX"
    session.pending_question_misconceptions = {"x_plus_0": 1, "x_into_x": 0}

    back = doc_to_session(session_to_doc(session))
    assert back.misconception_applicable == {"x_plus_0", "x_minus_x"}
    assert back.misconception_asked["x_plus_0"] == 2
    assert back.misconception_correct["x_plus_0"] == 1
    assert back.pending_question_misconceptions == {"x_plus_0": 1, "x_into_x": 0}


def test_old_document_without_ledger_deserializes_to_empty():
    from engine.storage.documents import doc_to_session, session_to_doc
    from engine.session import start_session
    from tests.test_session import make_params

    params = make_params(grade=3)
    session = start_session(
        sub_session_id="s", learner_id="l", tenant_id="Delhi", class_id="c",
        grade=3, engine_version="t", params=params,
    ).session
    doc = session_to_doc(session)
    # Simulate a pre-feature document.
    doc.pop("misconception_asked", None)
    doc.pop("misconception_correct", None)
    doc.pop("misconception_applicable", None)
    back = doc_to_session(doc)
    assert back.misconception_applicable == set()
    assert back.misconception_asked == {}
    assert back.misconception_correct == {}
