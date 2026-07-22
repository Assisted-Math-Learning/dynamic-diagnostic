"""
Storage layer for the dynamic diagnostic engine.

Provides a pluggable persistence interface. Two backends ship with the engine:
  - memory   (default): ephemeral, for local development and tests
  - mongodb            : PyMongo-backed, for production

Select via the STORAGE_BACKEND env var, or pass `backend=...` to the factory.
"""

import os
from typing import Optional

from engine.storage.interface import StorageBackend
from engine.storage.memory import InMemoryStorage


def get_storage_backend(
    *,
    backend: Optional[str] = None,
    **kwargs,
) -> StorageBackend:
    """Factory for the configured storage backend.

    Args:
        backend: 'memory' or 'mongodb'. Defaults to the STORAGE_BACKEND env
            var, then 'memory'.
        **kwargs: backend-specific arguments (e.g. mongo_url, database_name
            for the MongoDB backend; lattice_edges for the in-memory backend).

    Env-var bridges (mongodb backend only):
        MONGODB_URL      -> mongo_url (required unless mongo_client passed)
        MONGODB_DATABASE -> database_name (default 'aml_engine')

    Explicit kwargs take precedence over env vars: passing
    `mongo_url='mongodb://...'` ignores the env var.
    """
    backend = backend or os.environ.get("STORAGE_BACKEND", "memory")
    if backend == "memory":
        return InMemoryStorage(**kwargs)
    if backend == "mongodb":
        # Lazy import so installations without PyMongo can still use the
        # in-memory backend.
        from engine.storage.mongodb import MongoStorage  # noqa: WPS433

        # Bridge env vars to MongoStorage kwargs. setdefault means an explicit
        # kwarg passed by the caller wins; the env var only fills the gap.
        kwargs.setdefault("mongo_url", os.environ.get("MONGODB_URL"))
        kwargs.setdefault(
            "database_name",
            os.environ.get("MONGODB_DATABASE", "aml_engine"),
        )
        # MongoStorage raises if both mongo_url and mongo_client are None, but
        # the message there refers to internal kwargs. Catch it here with a
        # clearer message referencing the env var the operator was meant to set.
        if kwargs.get("mongo_url") is None and kwargs.get("mongo_client") is None:
            raise ValueError(
                "STORAGE_BACKEND=mongodb requires the MONGODB_URL env var "
                "(or an explicit mongo_url / mongo_client kwarg)."
            )
        return MongoStorage(**kwargs)
    raise ValueError(f"unknown STORAGE_BACKEND: {backend!r}")


__all__ = [
    "StorageBackend",
    "InMemoryStorage",
    "get_storage_backend",
]
