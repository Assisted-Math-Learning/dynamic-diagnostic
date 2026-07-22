"""
In-memory storage backend.

Ephemeral: all data is lost when the process restarts. Used as the default
backend for local development, the CLI, and unit tests. Production uses
the MongoDB backend.

Stores Session and SkillVerdict objects directly without serialisation;
deep-copies on read and write so callers cannot mutate stored state by
accident (matches the round-trip semantics of the MongoDB backend).
"""

import copy
import threading
from typing import Dict, List, Optional

from engine.lattice import LatticeEdge
from engine.session import Session, SessionStatus, SkillVerdict
from engine.storage.interface import StorageBackend


class InMemoryStorage(StorageBackend):
    """Thread-safe in-memory storage."""

    def __init__(self, lattice_edges: Optional[List[LatticeEdge]] = None):
        self._lock = threading.Lock()
        self._lattice_edges: List[LatticeEdge] = list(lattice_edges or [])
        self._sessions: Dict[str, Session] = {}
        self._verdicts: Dict[str, List[SkillVerdict]] = {}

    # === Lattice ===

    def load_lattice_edges(self) -> List[LatticeEdge]:
        with self._lock:
            return list(self._lattice_edges)

    def save_lattice_edges(self, edges: List[LatticeEdge]) -> None:
        with self._lock:
            self._lattice_edges = list(edges)

    # === Sessions ===

    def save_session(self, session: Session) -> None:
        with self._lock:
            self._sessions[session.sub_session_id] = copy.deepcopy(session)

    def get_session(self, sub_session_id: str) -> Optional[Session]:
        with self._lock:
            sess = self._sessions.get(sub_session_id)
            return copy.deepcopy(sess) if sess is not None else None

    def session_exists(self, sub_session_id: str) -> bool:
        with self._lock:
            return sub_session_id in self._sessions

    # === Verdicts ===

    def save_verdicts(self, session: Session, verdicts: List[SkillVerdict]) -> None:
        with self._lock:
            self._verdicts[session.sub_session_id] = [copy.deepcopy(v) for v in verdicts]

    def get_verdicts(self, sub_session_id: str) -> List[SkillVerdict]:
        with self._lock:
            return [copy.deepcopy(v) for v in self._verdicts.get(sub_session_id, [])]

    # === Cleanup ===

    def find_complete_sessions_without_verdicts(
        self, *, limit: int = 100,
    ) -> List[Session]:
        with self._lock:
            out: List[Session] = []
            for sess in self._sessions.values():
                if (
                    sess.status == SessionStatus.COMPLETE
                    and not self._verdicts.get(sess.sub_session_id)
                ):
                    out.append(copy.deepcopy(sess))
                    if len(out) >= limit:
                        break
            return out

    # === Health ===

    def health_check(self) -> bool:
        return True
