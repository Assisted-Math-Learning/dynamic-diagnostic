"""Integration tests for B1: the offline_tree reference on session/start and
the offline-tree fetch endpoint, exercised against the REAL shipped Delhi
artifacts. Gated on real project data + tenant lookup being present, like the
Stage B integration test. The app is built at engine.__version__ so the
version guard matches the artifacts (0.9.0)."""
import hashlib
import json
from pathlib import Path

import pytest

from tests import DATA_DIR

PROJECT = DATA_DIR
LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists() and (PROJECT / "question_parameters.csv").exists() and LOOKUP.exists()),
    reason="real project data / tenant lookup not present",
)

import engine                                          # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402
from prometheus_client import CollectorRegistry        # noqa: E402

PREFIX = "/api/v1/diagnostic"
DELHI_TOKEN = "tok"
KARN_TOKEN = "tok2"


def _build_app():
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
        b["reserve_size"] = 7
    config = EngineConfig.model_validate(cfgd)
    storage = InMemoryStorage()
    storage.save_lattice_edges(edges)
    lattice = LatticeIndex(edges)
    pool = CsvQuestionPool(
        str(qpath), expected_skills={s.name for s in config.skills},
        seed=7, lookup_path=str(LOOKUP), misconception_target=2,
    )
    # engine_version MUST match the shipped artifacts (0.9.0) so the version
    # guard serves them rather than treating them as stale.
    app = create_app(
        config=config, storage=storage, lattice_index=lattice,
        tenant_tokens={"Delhi": DELHI_TOKEN, "Karnataka": KARN_TOKEN},
        engine_version=engine.__version__, question_pool=pool,
        metrics_registry=CollectorRegistry(),
    )
    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_build_app())


def _start(client, tenant, token, grade, sid):
    r = client.post(
        f"{PREFIX}/session/start",
        json={"learner_id": "l", "tenant_id": tenant, "sub_session_id": sid,
              "class_id": "c", "grade": grade},
        headers={"X-Internal-Service-Token": token},
    )
    return r


@pytest.mark.parametrize("grade", [2, 3, 4, 5])
def test_delhi_session_start_has_offline_tree_ref(client, grade):
    r = _start(client, "Delhi", DELHI_TOKEN, grade, f"b1-delhi-{grade}")
    assert r.status_code == 200
    ref = r.json()["result"]["offline_tree"]
    assert ref is not None, f"Delhi G{grade} should carry an offline_tree reference"
    assert ref["available"] is True
    assert ref["grade"] == grade
    assert ref["engine_version"] == engine.__version__     # 0.10.0
    assert ref["tree_compat_version"] == 1
    assert ref["size_bytes"] > 0
    assert ref["fetch_path"] == f"{PREFIX}/offline-tree/Delhi/{grade}"
    assert len(ref["sha256"]) == 64


def test_g7_session_start_resolves_to_g5_tree(client):
    # ADDED REQUIREMENT: G5-G8 fall back to the G5 tree (mirrors the online
    # engine's grade handling). A G7 Delhi request references the G5 tree.
    r = _start(client, "Delhi", DELHI_TOKEN, 7, "b1-delhi-7")
    assert r.status_code == 200
    ref = r.json()["result"]["offline_tree"]
    assert ref is not None
    assert ref["grade"] == 5
    assert ref["engine_version"] == engine.__version__     # 0.10.0
    assert ref["tree_compat_version"] == 1
    assert ref["fetch_path"] == f"{PREFIX}/offline-tree/Delhi/5"


def test_non_delhi_tenant_offline_tree_null_and_200(client):
    # A tenant with no shipped trees must not break its online session.
    r = _start(client, "Karnataka", KARN_TOKEN, 3, "b1-karn-3")
    assert r.status_code == 200
    assert r.json()["result"]["offline_tree"] is None


def test_fetch_offline_tree_roundtrip_matches_reference(client):
    r = _start(client, "Delhi", DELHI_TOKEN, 5, "b1-fetch-5")
    ref = r.json()["result"]["offline_tree"]
    got = client.get(ref["fetch_path"], headers={"X-Internal-Service-Token": DELHI_TOKEN})
    assert got.status_code == 200
    body = got.content
    assert len(body) == ref["size_bytes"]
    assert hashlib.sha256(body).hexdigest() == ref["sha256"]
    doc = json.loads(body)
    assert doc["engine_version"] == engine.__version__     # 0.10.0
    assert doc["tree_compat_version"] == 1
    assert doc["tenant"] == "Delhi"
    assert doc["grade"] == 5
    # v11: the artifact now carries an items array parallel to questions.
    add = doc["trees"]["Addition"]
    assert len(add["items"]) == len(add["questions"])


def test_fetch_offline_tree_404_for_missing(client):
    # Non-Delhi tenant: no tree -> 404 NO_TREE_FOR_GRADE.
    r1 = client.get(f"{PREFIX}/offline-tree/Karnataka/3",
                    headers={"X-Internal-Service-Token": KARN_TOKEN})
    assert r1.status_code == 404
    assert r1.json()["error"]["code"] == "NO_TREE_FOR_GRADE"
    # Below G2 resolves to no native grade -> 404.
    r2 = client.get(f"{PREFIX}/offline-tree/Delhi/1",
                    headers={"X-Internal-Service-Token": DELHI_TOKEN})
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "NO_TREE_FOR_GRADE"
