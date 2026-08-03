"""Phase C (mixed-mode v11 section 9): the offline-batch ingest endpoint.

Append-then-full-replay: an offline segment folds into the session's one unified
history and all state is recomputed by replaying the whole history through the
promoted history scorer. Gated on real data like the other integration tests.
"""
from pathlib import Path

import pytest

from tests import DATA_DIR

PROJECT = DATA_DIR
LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists() and (PROJECT / "question_parameters.csv").exists() and LOOKUP.exists()),
    reason="real project data / tenant lookup not present",
)

import engine                                            # noqa: E402
from fastapi.testclient import TestClient                # noqa: E402
from prometheus_client import CollectorRegistry          # noqa: E402

PREFIX = "/api/v1/diagnostic"
TOK = "tok"
HDR = {"X-Internal-Service-Token": TOK}


def _build():
    import scripts.smoke as smoke
    from engine.api.main import create_app
    from engine.cli import _build_engine_config_dict
    from engine.config import EngineConfig
    from engine.lattice import LatticeIndex
    from engine.question_pool import CsvQuestionPool
    from engine.storage.memory import InMemoryStorage

    skills, priors, anchors, edges, qpath = smoke.step_1_load_data(PROJECT)
    cfgd = _build_engine_config_dict(skills=skills, anchors=anchors, priors=priors)
    config = EngineConfig.model_validate(cfgd)
    storage = InMemoryStorage()
    storage.save_lattice_edges(edges)
    lattice = LatticeIndex(edges)
    pool = CsvQuestionPool(str(qpath), expected_skills={s.name for s in config.skills},
                           seed=7, lookup_path=str(LOOKUP), misconception_target=2)
    app = create_app(config=config, storage=storage, lattice_index=lattice,
                     tenant_tokens={"Delhi": TOK}, engine_version=engine.__version__,
                     question_pool=pool, metrics_registry=CollectorRegistry())
    return app, storage, config, lattice, pool


def _drive_online(client, sid, n_online, grade=3):
    """Answer n_online questions online; return (last_question_x_id, [(qid,correct)])."""
    r = client.post(f"{PREFIX}/session/start",
                    json={"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": sid,
                          "class_id": "c", "grade": grade}, headers=HDR).json()
    q = r["result"]["first_question"]
    seq = []
    last = None
    for i in range(n_online):
        if q is None:
            break
        correct = (i % 2 == 0)
        last = q["question_x_id"]
        seq.append((last, correct))
        res = client.post(f"{PREFIX}/session/{sid}/response",
                          json={"learner_id": "l", "tenant_id": "Delhi",
                                "skill_id": q["skill_id"], "question_x_id": last,
                                "is_correct": correct, "raw_response": str(i)},
                          headers=HDR).json()["result"]
        if res["session_complete"]:
            q = None
            break
        q = res["next_question"]
    return last, seq


def _fresh_offline_answers(pool, session, params, k, grade=3):
    """Build k offline answers for fresh (unasked) items across in-scope skills."""
    from engine.api.errors import NoQuestionForSkillError
    out = []
    for skill in params.skills_in_scope:
        if len(out) >= k:
            break
        try:
            pick = pool.pick_question_for_skill(
                skill=skill, session=session, grade=grade, tenant_id="Delhi")
        except NoQuestionForSkillError:
            continue
        qid = pick.question_id
        item_skill = pool._qxid_to_item[qid].split("|")[1]
        out.append({"question_x_id": qid, "skill_id": item_skill,
                    "is_correct": True, "raw_response": "7",
                    "asked_at": "2026-07-22T10:0%d:00+00:00" % len(out)})
    return out


def _post_batch(client, sid, anchor, answers, tree_compat_version=1):
    return client.post(
        f"{PREFIX}/session/{sid}/offline-batch",
        json={"learner_id": "l", "tenant_id": "Delhi", "resume_anchor": anchor,
              "tree_id": "Delhi/g3", "tree_version": 1,
              "tree_compat_version": tree_compat_version, "answers": answers},
        headers=HDR)


def test_offline_batch_persists_and_advances():
    # Catalogue (v11 section 23): TC-MIX-09, TC-MIX-20
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, online_seq = _drive_online(client, "c1", 4)
    params = config.get_engine_params(3, lattice)
    session = storage.get_session("c1")
    answers = _fresh_offline_answers(pool, session, params, 3)
    assert len(answers) == 3

    r = _post_batch(client, "c1", anchor, answers)
    assert r.status_code == 200, r.text

    s = storage.get_session("c1")
    from engine.session import RoutingMode
    # Offline answers are persisted with routing_mode=offline_replay + raw_response.
    off = [e for e in s.question_history if e.routing_mode == RoutingMode.OFFLINE_REPLAY]
    assert len(off) == 3
    assert all(e.raw_response == "7" for e in off)
    # Budget counts them: total == online + offline.
    assert s.questions_total == len(online_seq) + 3
    assert s.routing_mode_counts[RoutingMode.OFFLINE_REPLAY] == 3
    # Ingest recorded a sync event.
    assert app.state.metrics.offline_sync_events_total.labels(
        tenant_id="Delhi", outcome="applied")._value.get() >= 1


def test_offline_batch_verdict_neutrality():
    # Catalogue (v11 section 23): TC-MIX-19
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, _ = _drive_online(client, "c2", 5)
    params = config.get_engine_params(3, lattice)
    session = storage.get_session("c2")
    answers = _fresh_offline_answers(pool, session, params, 3)
    assert _post_batch(client, "c2", anchor, answers).status_code == 200

    s = storage.get_session("c2")
    # Verdicts on the ingested session must equal a fresh full replay of the
    # unified (question_x_id, is_correct) sequence - i.e. what a pure-online
    # session on the same answers would score.
    from engine.session import compute_verdicts
    from engine.history_scorer import score_history
    _ALL = "all"
    steps = []
    for e in s.question_history:
        item = pool._qxid_to_item.get(e.question_id)
        rows = pool._item_rows.get(item, {})
        row = rows.get("3") or rows.get(_ALL)
        if row is None:
            continue
        steps.append((e.question_id, item.split("|")[1], e.is_correct,
                      row.slip, row.guess, pool.misconceptions_for_item(item) or {}))
    pure_skills, _ = score_history(steps, config, lattice, pool, 3, "Delhi")
    mixed_skills = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    assert mixed_skills == pure_skills


def test_offline_batch_idempotent_replay():
    # Catalogue (v11 section 23): TC-MIX-10
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, _ = _drive_online(client, "c3", 4)
    params = config.get_engine_params(3, lattice)
    answers = _fresh_offline_answers(pool, storage.get_session("c3"), params, 2)
    assert _post_batch(client, "c3", anchor, answers).status_code == 200
    total_after_first = storage.get_session("c3").questions_total
    # Re-submitting the identical batch is a no-op (idempotent).
    assert _post_batch(client, "c3", anchor, answers).status_code == 200
    assert storage.get_session("c3").questions_total == total_after_first


def test_offline_batch_conflict():
    # Catalogue (v11 section 23): TC-MIX-11
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, online_seq = _drive_online(client, "c4", 4)
    # Re-send an already-answered online question with the OPPOSITE correctness.
    qid, correct = online_seq[0]
    conflicting = [{"question_x_id": qid, "skill_id": "x", "is_correct": (not correct),
                    "raw_response": "9", "asked_at": "2026-07-22T10:00:00+00:00"}]
    r = _post_batch(client, "c4", anchor, conflicting)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "RESPONSE_CONFLICT"


def test_offline_batch_no_repeat_item():
    # Catalogue (v11 section 23): TC-MIX-02
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, _ = _drive_online(client, "c5", 4)
    params = config.get_engine_params(3, lattice)
    answers = _fresh_offline_answers(pool, storage.get_session("c5"), params, 2)
    off_items = {pool._qxid_to_item[a["question_x_id"]] for a in answers}
    assert _post_batch(client, "c5", anchor, answers).status_code == 200
    s = storage.get_session("c5")
    # The offline items are now in the no-repeat set.
    assert off_items <= pool._answered_items(s)


def test_offline_batch_too_large_rejected():
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, _ = _drive_online(client, "c6", 2)
    params = config.get_engine_params(3, lattice)
    budget = params.routing_config.total_budget
    # A batch larger than twice the grade budget is rejected as implausible.
    huge = [{"question_x_id": f"q_bogus_{i}", "skill_id": "x", "is_correct": True,
             "raw_response": "1", "asked_at": "2026-07-22T10:00:00+00:00"}
            for i in range(2 * budget + 1)]
    r = _post_batch(client, "c6", anchor, huge)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "OFFLINE_BATCH_TOO_LARGE"


def test_offline_batch_stale_tree_accepted_and_flagged():
    """TC-MIX-15: a batch whose tree_compat_version does not match the engine's
    required version (a device on a tree that went stale mid-session) is still
    ACCEPTED - the answers are valid observations - and the mismatch is flagged
    (v11 decision 3)."""
    import structlog
    from engine.session import RoutingMode
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, _ = _drive_online(client, "cst", 4)
    params = config.get_engine_params(3, lattice)
    answers = _fresh_offline_answers(pool, storage.get_session("cst"), params, 2)
    with structlog.testing.capture_logs() as logs:
        r = _post_batch(client, "cst", anchor, answers, tree_compat_version=2)   # mismatch
    assert r.status_code == 200, r.text
    # Answers accepted despite the stale tree.
    s = storage.get_session("cst")
    off = [e for e in s.question_history if e.routing_mode == RoutingMode.OFFLINE_REPLAY]
    assert len(off) == 2
    # The mismatch was flagged.
    assert any("stale tree" in str(e.get("event", "")).lower() for e in logs)


def test_offline_batch_omitted_question_not_recorded():
    # Catalogue (v11 section 23): TC-MIX-14
    """A question shown but not answered before the drop is simply absent from
    the batch, so it is never recorded (no phantom/blank entry), does not count
    toward budget or no-repeat, and can still be answered legitimately later -
    the earlier non-answer does not poison it."""
    from engine.session import RoutingMode
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    anchor, _ = _drive_online(client, "phan", 4)
    params = config.get_engine_params(3, lattice)
    # Two fresh items; the batch carries only the first. The second (q_omit)
    # stands for the offered-but-unanswered question and is omitted.
    answers = _fresh_offline_answers(pool, storage.get_session("phan"), params, 2)
    assert len(answers) == 2
    q_omit = answers[1]
    assert _post_batch(client, "phan", anchor, [answers[0]]).status_code == 200

    s = storage.get_session("phan")
    omit_item = pool._qxid_to_item[q_omit["question_x_id"]]
    # No entry of any kind for the omitted question; not in the no-repeat set.
    assert all(e.question_id != q_omit["question_x_id"] for e in s.question_history)
    assert omit_item not in pool._answered_items(s)
    total_after_1 = s.questions_total

    # It can be answered in a later batch and is then recorded normally.
    new_anchor = s.question_history[-1].question_id
    q_omit["asked_at"] = "2026-07-22T11:00:00+00:00"
    assert _post_batch(client, "phan", new_anchor, [q_omit]).status_code == 200
    s2 = storage.get_session("phan")
    got = [e for e in s2.question_history if e.question_id == q_omit["question_x_id"]]
    assert len(got) == 1
    assert got[0].routing_mode == RoutingMode.OFFLINE_REPLAY
    assert s2.questions_total == total_after_1 + 1
