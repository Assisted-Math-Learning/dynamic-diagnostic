"""Unit tests for engine.offline_registry (B1).

No real data dependency: fabricates tiny artifact files so the grade fallback,
version guard, reference shape, and byte/hash integrity are all exercised fast.
"""
import gzip
import hashlib
import json

import pytest

from engine.offline_registry import (
    OfflineTreeRegistry,
    default_artifact_dir,
    resolve_grade,
)


def _write_artifact(root, tenant, grade, engine_version="0.9.0"):
    d = root / tenant
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "tenant": tenant,
        "grade": grade,
        "engine_version": engine_version,
        "trees": {"root": {"skill": "s", "children": {}}},
    }
    with gzip.open(d / f"g{grade}.json.gz", "wb") as fh:
        fh.write(json.dumps(doc).encode("utf-8"))


@pytest.fixture
def registry(tmp_path):
    # Delhi has G2 and G5 only; a fallback (G7) must resolve to G5.
    _write_artifact(tmp_path, "Delhi", 2)
    _write_artifact(tmp_path, "Delhi", 5)
    return OfflineTreeRegistry(tmp_path)


def _fetch_path(t, g):
    return f"/api/v1/diagnostic/offline-tree/{t}/{g}"


def test_resolve_grade_fallback():
    assert resolve_grade(1) is None          # below G2 -> no tree
    assert resolve_grade(2) == 2
    assert resolve_grade(4) == 4
    assert resolve_grade(5) == 5
    assert resolve_grade(6) == 5             # G6-G8 -> G5
    assert resolve_grade(7) == 5
    assert resolve_grade(8) == 5


def test_loaded_keys(registry):
    assert registry.loaded_keys() == [("Delhi", 2), ("Delhi", 5)]


def test_reference_matching_version_fields(registry):
    ref = registry.reference("Delhi", 2, "0.9.0", _fetch_path)
    assert ref is not None
    assert ref.available is True
    assert ref.grade == 2
    assert ref.engine_version == "0.9.0"
    assert ref.size_bytes > 0
    assert len(ref.sha256) == 64
    assert ref.fetch_path == "/api/v1/diagnostic/offline-tree/Delhi/2"


def test_g7_reference_resolves_to_g5(registry):
    ref = registry.reference("Delhi", 7, "0.9.0", _fetch_path)
    assert ref is not None
    assert ref.grade == 5
    assert ref.engine_version == "0.9.0"
    assert ref.fetch_path.endswith("/offline-tree/Delhi/5")


def test_reference_none_when_no_tree_for_grade(registry):
    # G3 has no artifact and no fallback target below it.
    assert registry.reference("Delhi", 3, "0.9.0", _fetch_path) is None
    # Below G2 -> None.
    assert registry.reference("Delhi", 1, "0.9.0", _fetch_path) is None


def test_reference_none_for_unknown_tenant(registry):
    assert registry.reference("Karnataka", 3, "0.9.0", _fetch_path) is None


def test_version_drift_returns_none_and_warns(registry):
    seen = []
    ref = registry.reference(
        "Delhi", 5, "9.9.9", _fetch_path,
        warn=lambda t, g, av, rv: seen.append((t, g, av, rv)),
    )
    assert ref is None                       # a stale tree is never served
    assert seen == [("Delhi", 5, "0.9.0", "9.9.9")]


def test_tree_bytes_matches_reference(registry):
    ref = registry.reference("Delhi", 5, "0.9.0", _fetch_path)
    body = registry.tree_bytes("Delhi", 5, "0.9.0")
    assert body is not None
    assert len(body) == ref.size_bytes
    assert hashlib.sha256(body).hexdigest() == ref.sha256
    # The bytes are the serialized tree doc.
    assert json.loads(body)["engine_version"] == "0.9.0"


def test_tree_bytes_none_on_version_drift(registry):
    assert registry.tree_bytes("Delhi", 5, "9.9.9") is None


def test_tree_bytes_none_for_missing(registry):
    assert registry.tree_bytes("Delhi", 3, "0.9.0") is None
    assert registry.tree_bytes("Karnataka", 5, "0.9.0") is None


def test_missing_dir_is_graceful(tmp_path):
    reg = OfflineTreeRegistry(tmp_path / "does-not-exist")
    assert reg.loaded_keys() == []
    assert reg.reference("Delhi", 3, "0.9.0", _fetch_path) is None


def test_default_artifact_dir_is_repo_relative():
    d = default_artifact_dir()
    assert d.name == "artifact"
    assert "/mnt/" not in str(d)
