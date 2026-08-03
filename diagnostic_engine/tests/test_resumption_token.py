"""Phase D (mixed-mode v11 section 8): the server-pushed resumption token.

The token is returned on session/start and every session/response (and, since the
offline-batch response reuses the same result model, after every ingest too). It
carries, per answered entry, question_x_id/is_correct/item/skill/operation/
asked_at plus the resume_anchor and the unified budget used. Gated on real data.
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
    storage = InMemoryStorage(); storage.save_lattice_edges(edges)
    lattice = LatticeIndex(edges)
    pool = CsvQuestionPool(str(qpath), expected_skills={s.name for s in config.skills},
                           seed=7, lookup_path=str(LOOKUP), misconception_target=2)
    app = create_app(config=config, storage=storage, lattice_index=lattice,
                     tenant_tokens={"Delhi": TOK}, engine_version=engine.__version__,
                     question_pool=pool, metrics_registry=CollectorRegistry())
    return app, storage, config, lattice, pool


def _start(client, sid, grade=3):
    return client.post(f"{PREFIX}/session/start",
                       json={"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": sid,
                             "class_id": "c", "grade": grade}, headers=HDR).json()["result"]


def _answer(client, sid, q, correct=True, i=0):
    return client.post(f"{PREFIX}/session/{sid}/response",
                       json={"learner_id": "l", "tenant_id": "Delhi",
                             "skill_id": q["skill_id"], "question_x_id": q["question_x_id"],
                             "is_correct": correct, "raw_response": str(i)},
                       headers=HDR).json()["result"]


def test_start_token_is_empty():
    # Catalogue (v11 section 23): TC-MIX-08
    app, *_ = _build()
    client = TestClient(app)
    res = _start(client, "t1")
    tok = res["resumption_token"]
    assert tok is not None
    assert tok["resume_anchor"] is None
    assert tok["budget_used"] == 0
    assert tok["answers"] == []


def test_response_token_reflects_history():
    # Catalogue (v11 section 23): TC-MIX-08
    app, *_ = _build()
    client = TestClient(app)
    res = _start(client, "t2")
    q = res["first_question"]
    r1 = _answer(client, "t2", q, correct=True, i=0)
    tok = r1["resumption_token"]
    assert tok is not None
    # One answer so far; anchor is that question; budget_used counts it.
    assert tok["budget_used"] == 1
    assert tok["resume_anchor"] == q["question_x_id"]
    e = tok["answers"][0]
    assert e["question_x_id"] == q["question_x_id"]
    assert e["is_correct"] is True
    # The device needs item + operation (not derivable from the artifact).
    assert e["item"] is not None
    assert e["operation"] is not None
    assert e["skill_id"] == q["skill_id"]
    assert "asked_at" in e

    # Token grows and the anchor advances on the next answer.
    q2 = r1["next_question"]
    if q2 is not None:
        r2 = _answer(client, "t2", q2, correct=False, i=1)
        tok2 = r2["resumption_token"]
        if not r2["session_complete"]:
            assert tok2["budget_used"] == 2
            assert tok2["resume_anchor"] == q2["question_x_id"]
            assert [a["question_x_id"] for a in tok2["answers"]] == \
                   [q["question_x_id"], q2["question_x_id"]]


def test_offline_batch_response_refreshes_token():
    # Catalogue (v11 section 23): TC-MIX-08
    app, storage, config, lattice, pool = _build()
    client = TestClient(app)
    res = _start(client, "t3")
    q = res["first_question"]
    last = None
    for i in range(4):
        if q is None:
            break
        last = q["question_x_id"]
        r = _answer(client, "t3", q, correct=(i % 2 == 0), i=i)
        if r["session_complete"]:
            q = None
            break
        q = r["next_question"]

    params = config.get_engine_params(3, lattice)
    session = storage.get_session("t3")
    from engine.api.errors import NoQuestionForSkillError
    answers = []
    for skill in params.skills_in_scope:
        if len(answers) >= 2:
            break
        try:
            pick = pool.pick_question_for_skill(skill=skill, session=session,
                                                grade=3, tenant_id="Delhi")
        except NoQuestionForSkillError:
            continue
        answers.append({"question_x_id": pick.question_id,
                        "skill_id": pool._qxid_to_item[pick.question_id].split("|")[1],
                        "is_correct": True, "raw_response": "7",
                        "asked_at": "2026-07-22T10:0%d:00+00:00" % len(answers)})

    rb = client.post(f"{PREFIX}/session/t3/offline-batch",
                     json={"learner_id": "l", "tenant_id": "Delhi", "resume_anchor": last,
                           "tree_id": "Delhi/g3", "tree_version": 1,
                           "tree_compat_version": 1, "answers": answers},
                     headers=HDR).json()["result"]
    if not rb["session_complete"]:
        tok = rb["resumption_token"]
        assert tok is not None
        # The token now includes the offline answers and anchors on the last one.
        qids = {a["question_x_id"] for a in tok["answers"]}
        assert {a["question_x_id"] for a in answers} <= qids
        assert tok["resume_anchor"] == tok["answers"][-1]["question_x_id"]
        assert tok["budget_used"] == len(tok["answers"])


def test_token_none_on_complete():
    # Catalogue (v11 section 23): TC-MIX-08
    app, *_ = _build()
    client = TestClient(app)
    res = _start(client, "t4")
    q = res["first_question"]
    last_res = None
    for i in range(200):
        if q is None:
            break
        r = _answer(client, "t4", q, correct=(i % 2 == 0), i=i)
        last_res = r
        if r["session_complete"]:
            break
        q = r["next_question"]
    assert last_res is not None and last_res["session_complete"] is True
    # On completion there is no offline continuation, so no token.
    assert last_res["resumption_token"] is None
