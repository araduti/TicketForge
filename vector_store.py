"""
TicketForge — Vector Store Abstraction

Provides a pluggable vector store interface with two backends:
  - InMemoryVectorStore (default) — keeps embeddings in a dict, no persistence
  - PersistentVectorStore — uses a SQLite table to persist embeddings across restarts

The active backend is selected via VECTOR_STORE_BACKEND in config.
"""
from __future__ import annotations

import abc
import json
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger(__name__)


class VectorStore(abc.ABC):
    """Abstract interface for a key-value vector store."""

    @abc.abstractmethod
    async def upsert(self, key: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        """Store or update a vector with associated metadata."""

    @abc.abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a vector by key."""

    @abc.abstractmethod
    async def search(self, query_vector: list[float], *, top_k: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        """
        Return the top-k most similar vectors.

        Each result dict contains:
          - key: str
          - score: float (cosine similarity)
          - metadata: dict
        """

    @abc.abstractmethod
    async def count(self) -> int:
        """Return the total number of stored vectors."""

    @abc.abstractmethod
    async def clear(self) -> None:
        """Remove all stored vectors."""

    @property
    @abc.abstractmethod
    def backend_name(self) -> str:
        """Human-readable backend name."""


# ── In-memory implementation ─────────────────────────────────────────────────

class InMemoryVectorStore(VectorStore):
    """Fast in-memory vector store — no persistence across restarts."""

    def __init__(self) -> None:
        self._vectors: dict[str, tuple[np.ndarray, dict[str, Any]]] = {}

    async def upsert(self, key: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        self._vectors[key] = (np.array(vector, dtype=np.float32), metadata or {})

    async def delete(self, key: str) -> None:
        self._vectors.pop(key, None)

    async def search(self, query_vector: list[float], *, top_k: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        if not self._vectors:
            return []

        query = np.array(query_vector, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        results: list[dict[str, Any]] = []
        for key, (vec, meta) in self._vectors.items():
            vec_norm = np.linalg.norm(vec)
            if vec_norm == 0:
                continue
            score = float(np.dot(query, vec) / (query_norm * vec_norm))
            if score >= min_score:
                results.append({"key": key, "score": score, "metadata": meta})

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    async def count(self) -> int:
        return len(self._vectors)

    async def clear(self) -> None:
        self._vectors.clear()

    @property
    def backend_name(self) -> str:
        return "in_memory"


# ── Persistent (SQLite-backed) implementation ────────────────────────────────

class PersistentVectorStore(VectorStore):
    """
    SQLite-backed vector store — embeddings survive restarts.

    Stores vectors as JSON-serialised float arrays in a dedicated table.
    Cosine similarity search is performed in Python after loading candidate vectors.
    """

    def __init__(self, db: Any) -> None:  # db: aiosqlite.Connection
        self._db = db

    async def initialise(self) -> None:
        """Create the backing table if it does not exist."""
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS vector_store (
                key TEXT PRIMARY KEY,
                vector TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await self._db.commit()
        log.info("vector_store.initialised", backend="persistent")

    async def upsert(self, key: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        vec_json = json.dumps(vector)
        meta_json = json.dumps(metadata or {})
        await self._db.execute(
            "INSERT OR REPLACE INTO vector_store (key, vector, metadata) VALUES (?, ?, ?)",
            (key, vec_json, meta_json),
        )
        await self._db.commit()

    async def delete(self, key: str) -> None:
        await self._db.execute("DELETE FROM vector_store WHERE key = ?", (key,))
        await self._db.commit()

    async def search(self, query_vector: list[float], *, top_k: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        query = np.array(query_vector, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        results: list[dict[str, Any]] = []
        async with self._db.execute("SELECT key, vector, metadata FROM vector_store") as cursor:
            async for row in cursor:
                vec = np.array(json.loads(row[1]), dtype=np.float32)
                vec_norm = np.linalg.norm(vec)
                if vec_norm == 0:
                    continue
                score = float(np.dot(query, vec) / (query_norm * vec_norm))
                if score >= min_score:
                    meta = json.loads(row[2])
                    results.append({"key": row[0], "score": score, "metadata": meta})

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    async def count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM vector_store") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def clear(self) -> None:
        await self._db.execute("DELETE FROM vector_store")
        await self._db.commit()

    @property
    def backend_name(self) -> str:
        return "persistent"


# ── Factory ──────────────────────────────────────────────────────────────────

async def create_vector_store(backend: str, *, db: Any = None) -> VectorStore:
    """
    Create the appropriate vector store backend.

    Args:
        backend: 'in_memory' or 'persistent'
        db: aiosqlite.Connection (required for persistent backend)
    """
    if backend == "persistent":
        if db is None:
            log.warning("vector_store.no_db", msg="Persistent backend requested but no DB connection; falling back to in-memory")
            store = InMemoryVectorStore()
        else:
            store = PersistentVectorStore(db)
            await store.initialise()
        log.info("vector_store.created", backend=store.backend_name)
        return store

    store = InMemoryVectorStore()
    log.info("vector_store.created", backend="in_memory")
    return store
