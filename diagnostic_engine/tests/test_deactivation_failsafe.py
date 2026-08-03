"""Deactivation Failsafe (spec sections 4-6, tests table section 9).

The switched-off list and the transient decline change only which questions are
OFFERED, never how an answer is scored. Gated on real data. (The offline device
skip rule, section 6b, is covered by the shared-vector test's unavailable cases.)
"""
from datetime import datetime, timezone
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
    config = EngineConfig.model_validate(
        _build_engine_config_dict(skills=skills, anchors=anchors, priors=priors))
    storage = InMemoryStorage(); storage.save_lattice_edges(edges)
    lattice = LatticeIndex(edges)
    pool = CsvQuestionPool(str(qpath), expected_skills={s.name for s in config.skills},
                           seed=7, lookup_path=str(LOOKUP), misconception_target=2)
    app = create_app(config=config, storage=storage, lattice_index=lattice,
                     tenant_tokens={"Delhi": TOK}, engine_version=engine.__version__,
                     question_pool=pool, metrics_registry=CollectorRegistry())
    return app, storage, config, lattice, pool


def _start(client, sid, switched_off=None, grade=3):
    body = {"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": sid,
            "class_id": "c", "grade": grade}
    if switched_off is not None:
        body["switched_off_question_x_ids"] = switched_off
    return client.post(f"{PREFIX}/session/start", json=body, headers=HDR).json()["result"]


def _answer(client, sid, q, correct=True, i=0, switched_off=None):
    body = {"learner_id": "l", "tenant_id": "Delhi", "skill_id": q["skill_id"],
            "question_x_id": q["question_x_id"], "is_correct": correct, "raw_response": str(i)}
    if switched_off is not None:
        body["switched_off_question_x_ids"] = switched_off
    return client.post(f"{PREFIX}/session/{sid}/response", json=body, headers=HDR).json()["result"]


def _offered(client, sid, first, n, switched_off_each=None):
    """Collect up to n offered question_x_ids by answering through the session."""
    seen = []
    q = first
    for i in range(n):
        if q is None:
            break
        seen.append(q["question_x_id"])
        r = _answer(client, sid, q, correct=(i % 2 == 0), i=i, switched_off=switched_off_each)
        if r["session_complete"]:
            break
        q = r["next_question"]
    return seen


def test_switched_off_never_offered_and_item_not_offered():
    # Baseline: the first several questions the engine offers with nothing off.
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    base = _offered(c, "b", _start(c, "b")["first_question"], 6)
    assert len(base) >= 3
    # Switch those off at start; they must never be offered, and neither must the
    # items they belong to (one variant per tenant, so the item is fully off).
    r = _start(c, "s", switched_off=base)
    off_items = {pool._qxid_to_item[x] for x in base}
    fq = r["first_question"]
    assert fq is None or fq["question_x_id"] not in base
    seen = _offered(c, "s", fq, 10)
    assert not (set(seen) & set(base))                       # none of the switched-off offered
    assert not ({pool._qxid_to_item[x] for x in seen} & off_items)  # nor their items


def test_verdict_neutrality_with_switched_off():
    from offline_scorer import run_online_capture
    from engine.session import RoutingMode, compute_verdicts, record_response, start_session
    config, lattice, pool = _build()[2:]
    params = config.get_engine_params(3, lattice)
    steps, on_skills, _ = run_online_capture(config, lattice, pool, 3, "Delhi", 2)

    def _score(switched_off):
        s = start_session(sub_session_id="v", learner_id="l", tenant_id="Delhi",
                          class_id="c", grade=3, engine_version="t", params=params).session
        s.misconception_applicable = pool.applicable_misconceptions(
            "Delhi", 3, params.skills_in_scope)
        s.switched_off_question_x_ids = set(switched_off)
        for (qid, sk, correct, slip, guess, tags) in steps:
            s.pending_question_misconceptions = tags
            record_response(s, skill_id=sk, question_id=qid, is_correct=correct, params=params,
                            slip_override=slip, guess_override=guess,
                            routing_mode=RoutingMode.ONLINE, defer_next=True)
        return {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}

    # The same recorded answers score identically whether or not some of those
    # very questions are on the switched-off list (switched-off governs offering,
    # not scoring).
    assert _score([]) == _score([q[0] for q in steps]) == on_skills


def test_replace_append_clear():
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    base = _offered(c, "b2", _start(c, "b2")["first_question"], 3)
    a, b = base[0], base[1]

    # replace: start with [a] off, then a submit passing [b] overwrites it.
    q = _start(c, "r2", switched_off=[a])["first_question"]
    _answer(c, "r2", q, switched_off=[b])
    st = storage.get_session("r2")
    assert st.switched_off_question_x_ids == {b}             # replace overwrote

    # append: [a] then append [b] -> both.
    q = _start(c, "ap", switched_off=[a])["first_question"]
    c.post(f"{PREFIX}/session/ap/response",
           json={"learner_id": "l", "tenant_id": "Delhi", "skill_id": q["skill_id"],
                 "question_x_id": q["question_x_id"], "is_correct": True, "raw_response": "0",
                 "switched_off_question_x_ids": [b], "switched_off_mode": "append"}, headers=HDR)
    assert storage.get_session("ap").switched_off_question_x_ids == {a, b}

    # clear: [a] then replace with [] -> empty.
    q = _start(c, "cl", switched_off=[a])["first_question"]
    _answer(c, "cl", q, switched_off=[])
    assert storage.get_session("cl").switched_off_question_x_ids == set()


def test_switched_off_persists_without_re_passing():
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    base = _offered(c, "b3", _start(c, "b3")["first_question"], 4)
    off = base[:3]
    r = _start(c, "p", switched_off=off)
    # Answer several turns WITHOUT re-passing the list; it must still apply.
    seen = _offered(c, "p", r["first_question"], 8)      # no switched_off_each
    assert not (set(seen) & set(off))
    assert storage.get_session("p").switched_off_question_x_ids == set(off)


def test_give_me_another_records_nothing():
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    q0 = _start(c, "g")["first_question"]["question_x_id"]
    r = c.post(f"{PREFIX}/session/g/replace-question",
               json={"learner_id": "l", "tenant_id": "Delhi", "question_x_id": q0}, headers=HDR)
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["next_question"]["question_x_id"] != q0       # a different question
    assert res["questions_asked_so_far"] == 0                # nothing recorded, no budget
    s = storage.get_session("g")
    assert all(e.question_id != q0 for e in s.question_history)
    assert q0 in s.declined_question_x_ids
    assert q0 not in s.switched_off_question_x_ids           # not merged into switched-off
    # Declining again still resolves (idempotent transient set).
    assert c.post(f"{PREFIX}/session/g/replace-question",
                  json={"learner_id": "l", "tenant_id": "Delhi", "question_x_id": q0},
                  headers=HDR).status_code == 200


def test_give_me_another_no_alternative_completes():
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    q0 = _start(c, "baseq")["first_question"]["question_x_id"]   # baseline first question
    all_delhi = {xid for (t, _i), xid in pool._tenant_item_xid.items() if t == "Delhi"}
    # Everything switched off EXCEPT q0, so q0 is the only offerable question.
    r = _start(c, "none", switched_off=list(all_delhi - {q0}))
    assert r["first_question"]["question_x_id"] == q0
    # Declining the only alternative leaves selection exhausted, so replace-question
    # falls cleanly to session-complete (spec section 5, no new terminal behaviour).
    res = c.post(f"{PREFIX}/session/none/replace-question",
                 json={"learner_id": "l", "tenant_id": "Delhi", "question_x_id": q0},
                 headers=HDR).json()["result"]
    assert res["session_complete"] is True


def test_ingest_accepts_answer_to_switched_off_question():
    from engine.session import RoutingMode
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    # Drive a couple online, then sync an offline answer to a question that is on
    # the switched-off list: it must still be recorded and scored (switched-off
    # governs future offering, not the validity of an answer already given).
    r0 = _start(c, "ia")
    q = r0["first_question"]
    anchor = q["question_x_id"]
    r = _answer(c, "ia", q, correct=True, i=0)
    anchor = q["question_x_id"]
    params = config.get_engine_params(3, lattice)
    # a fresh item to sync
    from engine.api.errors import NoQuestionForSkillError
    sess = storage.get_session("ia")
    off_qid = None
    for skill in params.skills_in_scope:
        try:
            off_qid = pool.pick_question_for_skill(skill=skill, session=sess, grade=3,
                                                   tenant_id="Delhi").question_id
            break
        except NoQuestionForSkillError:
            continue
    assert off_qid is not None
    body = {"learner_id": "l", "tenant_id": "Delhi", "resume_anchor": anchor,
            "tree_id": "Delhi/g3", "tree_version": 1, "tree_compat_version": 1,
            "switched_off_question_x_ids": [off_qid],       # off, yet synced below
            "answers": [{"question_x_id": off_qid, "skill_id": pool._qxid_to_item[off_qid].split("|")[1],
                         "is_correct": True, "raw_response": "7",
                         "asked_at": "2026-07-26T10:00:00+00:00"}]}
    rb = c.post(f"{PREFIX}/session/ia/offline-batch", json=body, headers=HDR)
    assert rb.status_code == 200
    s = storage.get_session("ia")
    got = [e for e in s.question_history if e.question_id == off_qid]
    assert len(got) == 1 and got[0].routing_mode == RoutingMode.OFFLINE_REPLAY
    assert off_qid in s.switched_off_question_x_ids         # now off for future offering


def test_tree_build_excludes_switched_off_unchanged_compat():
    import offline_tree_perop as P
    config, lattice, pool = _build()[2:]
    ctrl = P.PerOpBuilder(config, lattice, pool, 3, "Addition", tenant="Delhi",
                          allowance=4).build()
    assert ctrl.questions, "control tree should have questions"
    victim = ctrl.questions[len(ctrl.questions) // 2]        # a qid present in the tree
    off = P.PerOpBuilder(config, lattice, pool, 3, "Addition", tenant="Delhi",
                         allowance=4, switched_off={victim}).build()
    assert victim in ctrl.questions
    assert victim not in off.questions                       # excluded from the built tree
    # tree_compat_version is a serializer constant, unchanged by a switched-off
    # change (decision 8) - the serialize module still stamps 1.
    import offline_serialize
    assert offline_serialize.TREE_COMPAT_VERSION == 1


def test_all_off_session_start_returns_catchable_4xx():
    """All questions switched off at session start is a client-input condition
    (the caller's list covers everything available), so the start fails with a
    specific, catchable 422 NO_USABLE_QUESTION - not a silent all-uncertain
    complete, and not a generic 500."""
    app, storage, config, lattice, pool = _build()
    c = TestClient(app)
    all_delhi = list({xid for (t, _i), xid in pool._tenant_item_xid.items() if t == "Delhi"})
    r = c.post(f"{PREFIX}/session/start",
               json={"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": "alloff",
                     "class_id": "c", "grade": 3, "switched_off_question_x_ids": all_delhi},
               headers=HDR)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "NO_USABLE_QUESTION"
