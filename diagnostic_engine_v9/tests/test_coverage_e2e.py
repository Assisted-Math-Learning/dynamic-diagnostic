"""End-to-end coverage-layer tests through the real API + real data.

Drives full sessions over HTTP (TestClient) against a CsvQuestionPool built
from the repo data dir + the tenant lookup, with the reserve enabled, to prove the
phase controller is actually wired into the route: Phase 1 runs under the
lowered stop, the reserve phases fire, the misconception floor is reached, and
the session completes within the grade budget. Skipped when the real data files
are not present (e.g. a fresh container without the data dir).
"""

from pathlib import Path

from tests import DATA_DIR

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

PROJECT = DATA_DIR
# Seven-field lookup required: it must match the seven-field params (both carry
# the division-only seventh field), or division items fail the resolvability
# join. See the longer note in test_misconception_ledger.py. Read the engine's
# own seven-field lookup wired into inputs/ by this branch.
LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists()
         and (PROJECT / "question_parameters.csv").exists()
         and LOOKUP.exists()),
    reason="real project data / tenant lookup not present",
)

G3_TOTAL_BUDGET = 42  # _DEFAULT_BUDGETS[3]["total"]


def _build(reserve, *, seed=7):
    import scripts.smoke as smoke
    from engine.api.main import create_app
    from engine.cli import _build_engine_config_dict
    from engine.config import EngineConfig
    from engine.lattice import LatticeIndex
    from engine.question_pool import CsvQuestionPool
    from engine.storage.memory import InMemoryStorage

    skills, priors, anchors, edges, qpath = smoke.step_1_load_data(PROJECT)
    cfgd = _build_engine_config_dict(skills=skills, anchors=anchors, priors=priors)
    for budget in cfgd["budgets"].values():
        budget["reserve_size"] = reserve
    config = EngineConfig.model_validate(cfgd)
    storage = InMemoryStorage()
    storage.save_lattice_edges(edges)
    pool = CsvQuestionPool(
        str(qpath), expected_skills={s.name for s in config.skills},
        seed=seed, lookup_path=str(LOOKUP), misconception_target=2,
    )
    app = create_app(
        config=config, storage=storage, lattice_index=LatticeIndex(edges),
        tenant_tokens={"Delhi": "tok"}, engine_version="e2e",
        question_pool=pool, metrics_registry=CollectorRegistry(),
    )
    return app, storage


def _drive(app, *, grade, correct, sid):
    client = TestClient(app)
    headers = {"X-Internal-Service-Token": "tok"}
    r = client.post(
        "/api/v1/diagnostic/session/start",
        json={"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": sid,
              "class_id": "c", "grade": grade},
        headers=headers,
    ).json()
    assert r["params"]["status"] == "SUCCESS"
    q = r["result"]["first_question"]
    n = 0
    final = None
    while q is not None and n < 300:
        n += 1
        res = client.post(
            f"/api/v1/diagnostic/session/{sid}/response",
            json={"learner_id": "l", "tenant_id": "Delhi",
                  "skill_id": q["skill_id"], "question_x_id": q["question_x_id"],
                  "is_correct": correct},
            headers=headers,
        ).json()
        assert res["params"]["status"] == "SUCCESS"
        result = res["result"]
        if result["session_complete"]:
            final = result
            break
        q = result["next_question"]
    assert final is not None, "session did not complete"
    return final, client


def test_reserve_enabled_session_fires_backfill_and_reaches_floor():
    # All-correct resolves skills quickly, so Phase 1 ends before opportunistic
    # has covered every misconception -> the reserve (Phase 2 backfill) MUST run
    # to bring each applicable misconception up to the floor.
    app, storage = _build(reserve=7)
    final, _ = _drive(app, grade=3, correct=True, sid="e2e-correct")
    s = storage.get_session("e2e-correct")

    assert final["session_complete"] is True
    assert s.status.value == "complete"
    assert s.questions_total <= G3_TOTAL_BUDGET           # within the full budget
    assert s.reserve_phase_started_at is not None         # Phase 1 ended

    reserve_consumed = s.questions_total - s.reserve_phase_started_at
    assert reserve_consumed > 0                            # reserve phase actually ran

    # Coverage contract: every applicable misconception reaches the floor (2).
    applicable = s.misconception_applicable
    assert len(applicable) == 8                            # Delhi G3
    below = {m: s.misconception_asked[m] for m in applicable
             if s.misconception_asked[m] < 2}
    assert below == {}, f"misconceptions below floor: {below}"

    # Verdicts are still produced normally alongside coverage.
    assert len(final["verdicts"]) > 0


def test_misconception_signals_ride_on_the_complete_response():
    app, storage = _build(reserve=7)
    final, client = _drive(app, grade=3, correct=True, sid="e2e-sig")

    sigs = final["misconception_signals"]
    assert sigs is not None and len(sigs) == 11          # all 11 emitted
    valid = {"not_applicable", "likely_present", "likely_absent", "unsure"}
    assert all(s["state"] in valid for s in sigs)
    for s in sigs:
        assert s["wrong"] == s["asked"] - s["correct"]   # invariant

    s = storage.get_session("e2e-sig")
    applicable = s.misconception_applicable
    by_name = {x["misconception"]: x for x in sigs}
    # Applicable ones are never not_applicable; the rest are.
    for m in by_name:
        if m in applicable:
            assert by_name[m]["state"] != "not_applicable"
        else:
            assert by_name[m]["state"] == "not_applicable"

    # The same signal rides on get_verdicts (derived from the persisted session).
    gv = client.get(
        "/api/v1/diagnostic/session/e2e-sig/verdicts",
        headers={"X-Internal-Service-Token": "tok"},
    ).json()["result"]
    assert gv["misconception_signals"] is not None
    assert len(gv["misconception_signals"]) == 11


def test_reserve_zero_is_inert_end_to_end():
    # reserve_size=0 -> controller inert: Phase 1 runs the full budget and no
    # reserve question is ever asked (marker == final count, nothing consumed).
    app, storage = _build(reserve=0)
    final, _ = _drive(app, grade=3, correct=True, sid="e2e-r0")
    s = storage.get_session("e2e-r0")

    assert final["session_complete"] is True
    assert s.status.value == "complete"
    assert s.reserve_phase_started_at == s.questions_total  # nothing past Phase 1
    assert s.questions_total <= G3_TOTAL_BUDGET


def test_replay_is_idempotent_under_coverage():
    # Re-POSTing the same answer returns the same pending next-question and does
    # not advance the session (the controller is not re-run on replay).
    app, storage = _build(reserve=7)
    client = TestClient(app)
    headers = {"X-Internal-Service-Token": "tok"}
    r = client.post(
        "/api/v1/diagnostic/session/start",
        json={"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": "e2e-replay",
              "class_id": "c", "grade": 3},
        headers=headers,
    ).json()
    q = r["result"]["first_question"]
    body = {"learner_id": "l", "tenant_id": "Delhi", "skill_id": q["skill_id"],
            "question_x_id": q["question_x_id"], "is_correct": True}

    first = client.post("/api/v1/diagnostic/session/e2e-replay/response",
                        json=body, headers=headers).json()["result"]
    count_after_first = storage.get_session("e2e-replay").questions_total
    replay = client.post("/api/v1/diagnostic/session/e2e-replay/response",
                         json=body, headers=headers).json()["result"]
    count_after_replay = storage.get_session("e2e-replay").questions_total

    assert first["next_question"] == replay["next_question"]  # same pending q
    assert count_after_first == count_after_replay            # no double-advance
