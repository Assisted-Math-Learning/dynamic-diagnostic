"""
MongoDB storage backend.

Uses PyMongo (synchronous) per spec section 10.1. Creates indexes on first
construction. Compatible with mongomock for unit tests.

Collection names and schema match spec section 6.1. The engine writes three
collections:
  - learner_diagnostic_sessions
  - learner_skill_verdicts
  - lattice_edges

Offline decision trees are NOT stored in MongoDB. They are served from the
shipped file artifact (artifact/<tenant>/g<grade>.json.gz) via the
OFFLINE_ARTIFACT_DIR config, resolved at request time by
engine/offline_registry.py (B1) - the engine does not read or write a
diagnostic_offline_trees collection.
"""

from datetime import datetime, timezone
from typing import List, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import ConnectionFailure

from engine.lattice import LatticeEdge
from engine.session import Session, SessionStatus, SkillVerdict
from engine.storage.documents import (
    doc_to_lattice_edge,
    doc_to_session,
    doc_to_verdict,
    lattice_edge_to_doc,
    session_to_doc,
    verdict_to_doc,
)
from engine.storage.interface import StorageBackend

# Collection names (spec section 6.1)
COL_SESSIONS = "learner_diagnostic_sessions"
COL_VERDICTS = "learner_skill_verdicts"
COL_LATTICE = "lattice_edges"

# Audit-field author
CREATED_BY = "engine"


class MongoStorage(StorageBackend):
    """PyMongo-backed storage. mongomock-compatible for tests."""

    def __init__(
        self,
        *,
        mongo_url: Optional[str] = None,
        database_name: str = "aml_engine",
        mongo_client: Optional[MongoClient] = None,
        create_indexes: bool = True,
    ):
        """Initialise the backend.

        Args:
            mongo_url: connection string. Required if mongo_client is None.
            database_name: name of the database to use.
            mongo_client: pre-built MongoClient (used for testing with mongomock).
            create_indexes: if True, create indexes per spec section 6.1
                (idempotent - safe to call repeatedly).
        """
        if mongo_client is not None:
            self._client = mongo_client
        elif mongo_url is not None:
            self._client = MongoClient(mongo_url)
        else:
            raise ValueError("either mongo_url or mongo_client must be provided")
        self._db = self._client[database_name]
        if create_indexes:
            self._create_indexes()

    def _create_indexes(self) -> None:
        """Create the indexes from spec section 6.1. Idempotent."""
        sessions = self._db[COL_SESSIONS]
        sessions.create_index([("identifier", ASCENDING)], unique=True)
        sessions.create_index([("learner_id", ASCENDING), ("started_at", DESCENDING)])
        sessions.create_index([("tenant_id", ASCENDING), ("status", ASCENDING)])
        sessions.create_index([("tenant_id", ASCENDING), ("started_at", DESCENDING)])

        verdicts = self._db[COL_VERDICTS]
        verdicts.create_index([("identifier", ASCENDING)], unique=True)
        verdicts.create_index([
            ("learner_id", ASCENDING),
            ("l2_5_skill_id", ASCENDING),
            ("created_at", DESCENDING),
        ])
        verdicts.create_index([("tenant_id", ASCENDING), ("created_at", DESCENDING)])
        verdicts.create_index([("sub_session_id", ASCENDING)])

        lattice = self._db[COL_LATTICE]
        lattice.create_index([("identifier", ASCENDING)], unique=True)
        lattice.create_index([("skill_a", ASCENDING), ("is_active", ASCENDING)])
        lattice.create_index([("skill_b", ASCENDING), ("is_active", ASCENDING)])

    # === Lattice ===

    def load_lattice_edges(self) -> List[LatticeEdge]:
        return [
            doc_to_lattice_edge(d)
            for d in self._db[COL_LATTICE].find({"is_active": True})
        ]

    def save_lattice_edges(self, edges: List[LatticeEdge]) -> None:
        coll = self._db[COL_LATTICE]
        # Replace strategy: clear and re-insert. Simple and matches the
        # `engine-cli seed-lattice` use case (apply a fresh snapshot).
        coll.delete_many({})
        if not edges:
            return
        now = _now()
        docs = []
        for edge in edges:
            doc = lattice_edge_to_doc(edge)
            doc.update({
                "created_at": now, "updated_at": now,
                "created_by": CREATED_BY, "updated_by": CREATED_BY,
            })
            docs.append(doc)
        coll.insert_many(docs)

    # === Sessions ===

    def save_session(self, session: Session) -> None:
        coll = self._db[COL_SESSIONS]
        doc = session_to_doc(session)
        now = _now()
        doc["updated_at"] = now
        doc["updated_by"] = CREATED_BY
        coll.update_one(
            {"identifier": session.sub_session_id},
            {
                "$set": doc,
                "$setOnInsert": {"created_at": now, "created_by": CREATED_BY},
            },
            upsert=True,
        )

    def get_session(self, sub_session_id: str) -> Optional[Session]:
        doc = self._db[COL_SESSIONS].find_one({"identifier": sub_session_id})
        return doc_to_session(doc) if doc is not None else None

    def session_exists(self, sub_session_id: str) -> bool:
        return self._db[COL_SESSIONS].count_documents(
            {"identifier": sub_session_id}, limit=1,
        ) > 0

    # === Verdicts ===

    def save_verdicts(self, session: Session, verdicts: List[SkillVerdict]) -> None:
        coll = self._db[COL_VERDICTS]
        # Replace strategy: delete any existing verdicts for this session,
        # then bulk-insert. Idempotent in case the cleanup job retries.
        coll.delete_many({"sub_session_id": session.sub_session_id})
        if not verdicts:
            return
        now = _now()
        docs = []
        for v in verdicts:
            doc = verdict_to_doc(v, session)
            doc.update({
                "created_at": now, "updated_at": now,
                "created_by": CREATED_BY, "updated_by": CREATED_BY,
            })
            docs.append(doc)
        coll.insert_many(docs)

    def get_verdicts(self, sub_session_id: str) -> List[SkillVerdict]:
        return [
            doc_to_verdict(d)
            for d in self._db[COL_VERDICTS].find({"sub_session_id": sub_session_id})
        ]

    # === Cleanup ===

    def find_complete_sessions_without_verdicts(
        self, *, limit: int = 100,
    ) -> List[Session]:
        sessions = self._db[COL_SESSIONS]
        verdicts = self._db[COL_VERDICTS]
        out: List[Session] = []
        for sess_doc in sessions.find({"status": SessionStatus.COMPLETE.value}):
            sid = sess_doc["identifier"]
            has = verdicts.count_documents({"sub_session_id": sid}, limit=1) > 0
            if not has:
                out.append(doc_to_session(sess_doc))
                if len(out) >= limit:
                    break
        return out

    # === Health ===

    def health_check(self) -> bool:
        try:
            self._client.admin.command("ping")
            return True
        except (ConnectionFailure, Exception):
            return False


def _now() -> datetime:
    return datetime.now(timezone.utc)
