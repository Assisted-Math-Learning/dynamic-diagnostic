"""Unit tests for engine.offline_registry (B1, updated for mixed-mode v11).

No real data dependency: fabricates tiny artifact files so the grade fallback,
the tree_compat_version serving guard, the reference shape, and byte/hash
integrity are all exercised fast.
"""
import gzip
import hashlib
import json

import pytest

from engine.offline_registry import (
    OfflineTreeRegistry,
    REQUIRED_TREE_COMPAT_VERSION,
    default_artifact_dir,
    resolve_grade,
)


def _write_artifact(root, tenant, grade, tree_compat_version=1, engine_version="0.10.0"):
    d = root / tenant
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "tenant": tenant,
        "grade": grade,
        "engine_version": engine_version,
        "tree_compat_version": tree_compat_version,
        "trees": {"root": {"skill": "s", "children": {}}},
    }
    with gzip.open(d / f"g{grade}.json.gz", "wb") as fh:
        fh.write(json.dumps(doc).encode("utf-8"))


@pytest.fixture
def registry(tmp_path):
    # Delhi has G2 and G5 only; a fallback (G7) must resolve to G5. Artifacts
    # carry tree_compat_version=1, matching the engine's required version.
    _write_artifact(tmp_path, "Delhi", 2)
    _write_artifact(tmp_path, "Delhi", 5)
    return OfflineTreeRegistry(tmp_path)


def _fetch_path(t, g):
    return f"/api/v1/diagnostic/offline-tree/{t}/{g}"


def test_required_compat_version_default_is_one():
    assert REQUIRED_TREE_COMPAT_VERSION == 1


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
    ref = registry.reference("Delhi", 2, _fetch_path)
    assert ref is not None
    assert ref.available is True
    assert ref.grade == 2
    assert ref.engine_version == "0.10.0"
    assert ref.tree_compat_version == 1
    assert ref.size_bytes > 0
    assert len(ref.sha256) == 64
    assert ref.fetch_path == "/api/v1/diagnostic/offline-tree/Delhi/2"


def test_g7_reference_resolves_to_g5(registry):
    ref = registry.reference("Delhi", 7, _fetch_path)
    assert ref is not None
    assert ref.grade == 5
    assert ref.tree_compat_version == 1
    assert ref.fetch_path.endswith("/offline-tree/Delhi/5")


def test_reference_none_when_no_tree_for_grade(registry):
    # G3 has no artifact and no fallback target below it.
    assert registry.reference("Delhi", 3, _fetch_path) is None
    # Below G2 -> None.
    assert registry.reference("Delhi", 1, _fetch_path) is None


def test_reference_none_for_unknown_tenant(registry):
    assert registry.reference("Karnataka", 3, _fetch_path) is None


def test_compat_drift_returns_none_and_warns(tmp_path):
    # Artifacts stamped tree_compat_version=1, but the engine requires 2:
    # a stale tree must NOT be served.
    _write_artifact(tmp_path, "Delhi", 5, tree_compat_version=1)
    reg = OfflineTreeRegistry(tmp_path, required_compat_version=2)
    seen = []
    ref = reg.reference(
        "Delhi", 5, _fetch_path,
        warn=lambda t, g, av, rv: seen.append((t, g, av, rv)),
    )
    assert ref is None
    assert seen == [("Delhi", 5, 1, 2)]      # (tenant, grade, artifact_tcv, required)


def test_tree_bytes_matches_reference(registry):
    ref = registry.reference("Delhi", 5, _fetch_path)
    body = registry.tree_bytes("Delhi", 5)
    assert body is not None
    assert len(body) == ref.size_bytes
    assert hashlib.sha256(body).hexdigest() == ref.sha256
    # The bytes are the serialized tree doc.
    assert json.loads(body)["tree_compat_version"] == 1


def test_tree_bytes_none_on_compat_drift(tmp_path):
    _write_artifact(tmp_path, "Delhi", 5, tree_compat_version=1)
    reg = OfflineTreeRegistry(tmp_path, required_compat_version=2)
    assert reg.tree_bytes("Delhi", 5) is None


def test_tree_bytes_none_for_missing(registry):
    assert registry.tree_bytes("Delhi", 3) is None
    assert registry.tree_bytes("Karnataka", 5) is None


def test_missing_dir_is_graceful(tmp_path):
    reg = OfflineTreeRegistry(tmp_path / "does-not-exist")
    assert reg.loaded_keys() == []
    assert reg.reference("Delhi", 3, _fetch_path) is None


def test_default_artifact_dir_is_repo_relative():
    d = default_artifact_dir()
    assert d.name == "artifact"
    assert "/mnt/" not in str(d)
