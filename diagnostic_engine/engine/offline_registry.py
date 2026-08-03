"""
Offline decision-tree registry (B1).

Loads the shipped serialized offline artifacts (artifact/<tenant>/g<grade>.json.gz,
produced by offline_serialize.py) ONCE at startup, keyed by (tenant, grade), and
serves them by reference. The tree itself is never inlined into session/start:
the deserialized G5 tree is ~30 MB, so session/start returns only a small
OfflineTreeRef and the client fetches the tree from a separate endpoint.

Grade fallback mirrors the online engine (config.get_engine_params): grades 2-4
map to themselves; grade 5 and above (G5-G8) map to the G5 tree; below G2 has no
tree. A tenant with no shipped artifacts (every non-Delhi tenant today) has no
tree. In both cases the reference is None and the fetch endpoint returns 404.

Deserialization uses the same path offline_validate_artifact.py uses
(gzip.open -> json.loads). The served payload is a canonical JSON encoding; the
reference's size_bytes and sha256 describe exactly those bytes, so the client can
verify what it fetched.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from engine.config import _HIGHEST_NATIVE_GRADE, _LOWEST_NATIVE_GRADE
from engine.api.schemas import OfflineTreeRef

_GRADE_FILE = re.compile(r"^g(\d+)\.json\.gz$")

# Offline-serving compatibility version the engine requires (mixed-mode spec
# v11, decision 8). The serving guard checks the artifact's tree_compat_version
# against THIS, not an exact engine_version match, so a plain engine version
# bump (e.g. 0.9.0 -> 0.10.0) no longer strands the shipped trees. Bump this in
# lockstep with offline_serialize.TREE_COMPAT_VERSION when a tree-format or
# scoring/selection change makes old trees wrong.
REQUIRED_TREE_COMPAT_VERSION = 1


def resolve_grade(grade: int) -> Optional[int]:
    """Apply the online engine's grade fallback. Returns the resolved native
    grade (2-5) whose tree serves this learner, or None if below the supported
    range. G5-G8 all resolve to 5; G2-G4 resolve to themselves."""
    if grade < _LOWEST_NATIVE_GRADE:
        return None
    return min(grade, _HIGHEST_NATIVE_GRADE)


class OfflineTreeRegistry:
    """In-memory registry of serialized offline trees, loaded once."""

    def __init__(self, artifact_dir: str | Path,
                 required_compat_version: int = REQUIRED_TREE_COMPAT_VERSION):
        self._dir = Path(artifact_dir)
        self._required_compat = required_compat_version
        # (tenant, native_grade) -> {engine_version, tree_compat_version,
        #                            bytes, size_bytes, sha256}
        self._store: Dict[Tuple[str, int], Dict] = {}
        self._load()

    def _load(self) -> None:
        if not self._dir.is_dir():
            return
        for tdir in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            tenant = tdir.name
            for f in sorted(tdir.glob("g*.json.gz")):
                m = _GRADE_FILE.match(f.name)
                if not m:
                    continue
                grade = int(m.group(1))
                try:
                    with gzip.open(f, "rb") as fh:
                        doc = json.loads(fh.read())
                except Exception:
                    # A corrupt / unreadable artifact is treated as absent
                    # (graceful: offline is a fallback, not a hard dependency).
                    continue
                canonical = json.dumps(
                    doc, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                self._store[(tenant, grade)] = {
                    "engine_version": str(doc.get("engine_version", "")),
                    "tree_compat_version": doc.get("tree_compat_version"),
                    "bytes": canonical,
                    "size_bytes": len(canonical),
                    "sha256": hashlib.sha256(canonical).hexdigest(),
                }

    def loaded_keys(self):
        """(tenant, grade) pairs actually loaded (for /health, tests)."""
        return sorted(self._store.keys())

    def _entry(self, tenant: str, grade: int):
        rg = resolve_grade(grade)
        if rg is None:
            return None, None
        return rg, self._store.get((tenant, rg))

    def reference(
        self,
        tenant: str,
        grade: int,
        fetch_path: Callable[[str, int], str],
        warn: Optional[Callable[[str, int, Optional[int], int], None]] = None,
    ) -> Optional[OfflineTreeRef]:
        """Build the OfflineTreeRef for (tenant, grade), or None if there is no
        servable tree. The serving guard checks the artifact's
        tree_compat_version against the engine's required version (v11 decision
        8) - NOT an exact engine_version match, so an engine bump does not
        strand the trees. On a tree_compat_version mismatch the tree is NOT
        served: returns None and calls `warn`."""
        rg, e = self._entry(tenant, grade)
        if e is None:
            return None
        if e["tree_compat_version"] != self._required_compat:
            if warn is not None:
                warn(tenant, rg, e["tree_compat_version"], self._required_compat)
            return None
        return OfflineTreeRef(
            available=True,
            grade=rg,
            engine_version=e["engine_version"],
            tree_compat_version=e["tree_compat_version"],
            size_bytes=e["size_bytes"],
            sha256=e["sha256"],
            fetch_path=fetch_path(tenant, rg),
        )

    def tree_bytes(self, tenant: str, grade: int) -> Optional[bytes]:
        """Canonical JSON bytes of the serialized tree for (tenant, grade), or
        None if there is no servable tree OR the tree_compat_version does not
        match the engine's required version (a stale tree is never served).
        Used by the fetch endpoint; matches the reference's size_bytes / sha256
        exactly."""
        rg, e = self._entry(tenant, grade)
        if e is None:
            return None
        if e["tree_compat_version"] != self._required_compat:
            return None
        return e["bytes"]


def default_artifact_dir() -> Path:
    """Repo-relative default: the bundled artifact/ next to the engine package
    (no /mnt dependency, consistent with the offline path's existing rule)."""
    return Path(__file__).resolve().parent.parent / "artifact"
