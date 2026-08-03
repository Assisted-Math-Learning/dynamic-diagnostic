"""Tests for the in-process Stage B integration (engine.stage_b_integration)."""
import shutil
from pathlib import Path

from tests import DATA_DIR

import pytest

PROJECT = DATA_DIR
LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists() and (PROJECT / "question_parameters.csv").exists() and LOOKUP.exists()),
    reason="real project data / tenant lookup not present",
)

from fastapi.testclient import TestClient            # noqa: E402
from prometheus_client import CollectorRegistry      # noqa: E402

from engine.session import compute_verdicts          # noqa: E402
from engine.stage_b_integration import (             # noqa: E402
    parse_item, run_stage_b, DEFAULT_TABLE_DIR,
)
import aml_engine as E                                # noqa: E402  (path wired by the glue)
import aml_stageb as SB                               # noqa: E402


# --------------------------- parse_item guards ----------------------------

def test_parse_item_nondivision_six_fields():
    m = parse_item("Addition|2-digit Addition with carry|Fib||47|38")
    assert m == {"operation": "Addition", "skill_id": "2-digit Addition with carry",
                 "q_type": "Fib", "n1": 47, "n2": 38, "response_includes_remainder": None}


def test_parse_item_division_seventh_field_is_real_bool():
    m = parse_item("Division|1D/2D/3D by 1D with remainder|Fib||13|3|True")
    assert m["response_includes_remainder"] is True
    m2 = parse_item("Division|1D/2D by 1D without remainder|Fib||36|3|False")
    assert m2["response_includes_remainder"] is False


@pytest.mark.parametrize("bad", [
    "Division|s|Fib||13|3",                  # division missing seventh field
    "Addition|s|Fib||4|5|extra",             # non-division with seventh field
    "Addition|s|Fib||x|5",                   # non-integer operand
    "Division|s|Fib||13|3|maybe",            # bad seventh field
])
def test_parse_item_malformed_raises(bad):
    with pytest.raises(ValueError):
        parse_item(bad)


# ----------------------- resolver string regression -----------------------

def test_false_string_flag_does_not_flip(tmp_path):
    """The seventh field arriving as the text 'False' must resolve to no-remainder,
    not be coerced True (bool('False') is True). Acceptance: run with text 'False'."""
    tdir = tmp_path / "tables"; tdir.mkdir()
    for f in ("eligibility_table_20260628_v1.json", "eligibility_table_current.txt"):
        shutil.copy(Path(DEFAULT_TABLE_DIR) / f, tdir / f)
    responses = {"learner_id": "L", "learner_grade": 3, "items": [
        {"question_id": "d", "skill_id": "1D/2D by 1D without remainder", "operation": "division",
         "n1": 36, "n2": 3, "response": "12", "response_includes_remainder": "False", "q_type": "Fib"},
    ]}
    mastery = {"learner_id": "L", "learner_grade": 3, "skills": {
        "1D/2D by 1D without remainder": {"verdict": "uncertain", "posterior": 0.5,
            "recommendation": "take_maind", "resolved_by": "direct_evidence",
            "n_questions_asked": 1, "operation": "Division"}}}
    out = SB.build_learning_state(responses, mastery, {"tenant": "Delhi"},
                                  table_dir=str(tdir), log=False)
    assert out["errors"] == []                                   # 'False' accepted, not rejected/flipped
    assert out["skills"][0]["misconceptions"]["status"] == "classified"


# --------------------------- end-to-end on a real session ------------------

def _setup(reserve=7, seed=7):
    import scripts.smoke as smoke
    from engine.api.main import create_app
    from engine.cli import _build_engine_config_dict
    from engine.config import EngineConfig
    from engine.lattice import LatticeIndex
    from engine.question_pool import CsvQuestionPool
    from engine.storage.memory import InMemoryStorage

    skills, priors, anchors, edges, qpath = smoke.step_1_load_data(PROJECT)
    cfgd = _build_engine_config_dict(skills=skills, anchors=anchors, priors=priors)
    for b in cfgd["budgets"].values():
        b["reserve_size"] = reserve
    config = EngineConfig.model_validate(cfgd)
    storage = InMemoryStorage(); storage.save_lattice_edges(edges)
    lattice = LatticeIndex(edges)
    pool = CsvQuestionPool(str(qpath), expected_skills={s.name for s in config.skills},
                           seed=seed, lookup_path=str(LOOKUP), misconception_target=2)
    app = create_app(config=config, storage=storage, lattice_index=lattice,
                     tenant_tokens={"Delhi": "tok"}, engine_version="e2e",
                     question_pool=pool, metrics_registry=CollectorRegistry())
    return app, storage, config, lattice, pool


def _drive(app, grade, sid, raw_response_fn=None):
    client = TestClient(app); headers = {"X-Internal-Service-Token": "tok"}
    r = client.post("/api/v1/diagnostic/session/start",
                    json={"learner_id": "l", "tenant_id": "Delhi", "sub_session_id": sid,
                          "class_id": "c", "grade": grade}, headers=headers).json()
    q = r["result"]["first_question"]; n = 0
    while q is not None and n < 300:
        n += 1
        body = {"learner_id": "l", "tenant_id": "Delhi", "skill_id": q["skill_id"],
                "question_x_id": q["question_x_id"], "is_correct": (n % 3 != 0)}
        if raw_response_fn is not None:
            # Persist the learner's raw answer (B2) so Stage B can read it back
            # from the session instead of via an injected stand-in.
            body["raw_response"] = raw_response_fn(q["question_x_id"])
        res = client.post(f"/api/v1/diagnostic/session/{sid}/response",
                          json=body, headers=headers).json()["result"]
        if res["session_complete"]:
            break
        q = res["next_question"]


def test_in_process_stage_b_e2e(tmp_path):
    app, storage, config, lattice, pool = _setup()

    # A misconception-firing probe per item. It is PERSISTED via each response's
    # raw_response field (B2) rather than injected into run_stage_b: the glue's
    # default reader reads the raw answers stored on the session. No stand-in
    # remains.
    probe_cache = {}
    def probe_for(qid):
        item = pool._qxid_to_item[qid]
        m = parse_item(item)
        op = E.norm_op(m["operation"]); key = (op, m["n1"], m["n2"], m["response_includes_remainder"])
        if key not in probe_cache:
            chosen = str(m["n1"])  # fallback
            for r in sorted(E.make_probes(op, m["n1"], m["n2"], m["response_includes_remainder"]), key=str):
                if r == "":
                    continue
                cr = E.classify_one(op, m["n1"], m["n2"], str(r), learner_grade=3,
                                    system_expects_remainder=m["response_includes_remainder"])
                if cr.cascade_code not in ("CORRECT",) and cr.cascade_code not in E.INVALID_CODES:
                    chosen = str(r); break
            probe_cache[key] = chosen
        return probe_cache[key]

    _drive(app, grade=3, sid="sb-e2e", raw_response_fn=probe_for)
    session = storage.get_session("sb-e2e")
    params = config.get_engine_params(3, lattice)
    verdicts = compute_verdicts(session, params=params)

    tdir = tmp_path / "tables"; tdir.mkdir()
    for f in ("eligibility_table_20260628_v1.json", "eligibility_table_current.txt"):
        shutil.copy(Path(DEFAULT_TABLE_DIR) / f, tdir / f)

    # No raw_response_of argument: the default reads the persisted raw answers.
    ls = run_stage_b(session, verdicts, pool, table_dir=str(tdir),
                     tenant="Delhi", engine_version="e2e", calibration_version="v9-667")

    by = {s["skill_id"]: s for s in ls["skills"]}
    verdict_skills = {v.skill_id for v in verdicts}
    assert set(by) == verdict_skills, "every in-scope (verdict) skill present in the merged state"
    assert ls["provenance"]["classifier_modules"] == dict(E.MODULE_VERSIONS)
    assert ls["provenance"]["low_support_k"] == 2
    assert ls["errors"] == [], f"errors not empty: {ls['errors']}"
    statuses = {s["misconceptions"]["status"] for s in ls["skills"]}
    assert statuses <= {"classified", "no_classifiable_responses"}
    for s in ls["skills"]:
        m = s["misconceptions"]
        if m["status"] == "no_classifiable_responses":
            assert "reason" in m
        for r in m.get("ranked", []):
            assert r["low_support"] == (r["n_eligible"] < 2)
            assert 0.0 <= r["misconception_evidence_index"] <= 1.0
    # at least one skill was actually classified (the driven session answered Fib items)
    assert any(s["misconceptions"]["status"] == "classified" for s in ls["skills"])
