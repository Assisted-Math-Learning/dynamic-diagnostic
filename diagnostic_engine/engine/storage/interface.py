"""
Abstract storage interface for the dynamic diagnostic engine.

Two implementations live alongside this module:
  - memory.py:  ephemeral in-memory store (default, for local dev and tests)
  - mongodb.py: PyMongo-backed store (production)

Both implement the same StorageBackend ABC so the API layer can swap between
them with a single env var (STORAGE_BACKEND).
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from engine.lattice import LatticeEdge
from engine.session import Session, SkillVerdict


class StorageBackend(ABC):
    """Persistence interface for the engine."""

    # === Lattice (read-only config; written once via the seed CLI) ===

    @abstractmethod
    def load_lattice_edges(self) -> List[LatticeEdge]:
        """Return all active lattice edges. Called once at engine startup."""

    @abstractmethod
    def save_lattice_edges(self, edges: List[LatticeEdge]) -> None:
        """Replace the lattice with the given edges. Used by the seed-lattice CLI."""

    # === Session lifecycle ===

    @abstractmethod
    def save_session(self, session: Session) -> None:
        """Insert or upsert a session document keyed by sub_session_id."""

    @abstractmethod
    def get_session(self, sub_session_id: str) -> Optional[Session]:
        """Fetch a session by sub_session_id. None if not found.

        Returns an independent copy: mutations to the returned object MUST NOT
        affect the storage state. The caller is expected to call save_session
        to persist changes.
        """

    @abstractmethod
    def session_exists(self, sub_session_id: str) -> bool:
        """Check whether a session exists. Cheaper than get_session."""

    # === Verdicts ===

    @abstractmethod
    def save_verdicts(self, session: Session, verdicts: List[SkillVerdict]) -> None:
        """Persist per-skill verdicts for a session.

        Replace-strategy: any existing verdicts for the same sub_session_id are
        replaced. This makes the operation idempotent in case the cleanup job
        runs after a partial write.
        """

    @abstractmethod
    def get_verdicts(self, sub_session_id: str) -> List[SkillVerdict]:
        """Fetch verdicts for a session. Empty list if none written yet."""

    # === Cleanup support (spec section 8.4) ===

    @abstractmethod
    def find_complete_sessions_without_verdicts(
        self, *, limit: int = 100,
    ) -> List[Session]:
        """Find complete sessions whose verdicts have not been persisted.

        Used by the cleanup background job to recover from partial writes
        (session marked complete but verdict insert crashed before completing).
        """

    # === Health ===

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the backend is reachable."""
