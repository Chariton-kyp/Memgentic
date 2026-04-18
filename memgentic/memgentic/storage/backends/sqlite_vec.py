"""sqlite-vec vector backend — opt-in, zero-config, multi-process safe.

Co-locates vectors with the existing SQLite metadata database by loading the
``sqlite_vec`` runtime extension into an aiosqlite connection. A single
``vec_memories`` virtual table stores the embedding; payload fields are
joined from the existing ``memories`` table on id.

Why opt in? SQLite WAL mode handles multi-writer concurrency (daemon + MCP
server + API) without the file-lock conflicts we saw in Qdrant local-file
mode. No separate process, no extra binary — sqlite-vec ships pre-built
wheels for Win/Mac/Linux under a permissive MIT/Apache-2.0 dual license.
"""

from __future__ import annotations

import json
import struct
from typing import Any

import aiosqlite
import structlog

from memgentic.config import MemgenticSettings
from memgentic.exceptions import StorageError
from memgentic.models import Memory, SessionConfig

logger = structlog.get_logger()


def _pack_float32(vec: list[float]) -> bytes:
    """Pack a list of floats into little-endian float32 bytes (sqlite-vec wire format)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _memory_to_payload(memory: Memory) -> dict[str, Any]:
    """Match the Qdrant payload shape exactly for drop-in compatibility."""
    return {
        "content": memory.content,
        "content_type": memory.content_type.value,
        "platform": memory.source.platform.value,
        "platform_version": memory.source.platform_version,
        "session_id": memory.source.session_id,
        "session_title": memory.source.session_title,
        "topics": memory.topics,
        "entities": memory.entities,
        "confidence": memory.confidence,
        "status": memory.status.value,
        "created_at": memory.created_at.isoformat(),
        "user_id": memory.user_id,
    }


class SqliteVecBackend:
    """Vector backend using the sqlite-vec extension co-located with metadata.

    Storage layout:

    - ``vec_memories`` — ``vec0`` virtual table with ``id TEXT PRIMARY KEY`` and
      ``embedding FLOAT[<dim>]``.
    - ``vec_memories_payload`` — regular table storing a JSON payload per id.
      (We keep a payload table inside the same DB rather than JOINing against
      the ``memories`` metadata table because the payload shape is stable and
      matches the Qdrant one — callers don't need a metadata store to search.)
    """

    VEC_TABLE = "vec_memories"
    PAYLOAD_TABLE = "vec_memories_payload"
    PIN_TABLE = "vec_embedding_pin"

    def __init__(self, settings: MemgenticSettings) -> None:
        self._settings = settings
        self._conn: aiosqlite.Connection | None = None

    # --- lifecycle ------------------------------------------------------

    async def initialize(self) -> None:
        """Open connection, load sqlite-vec extension, ensure schema."""
        try:
            import sqlite_vec  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - exercised via skip in tests
            raise StorageError(
                "sqlite-vec is not installed. Install with: "
                "uv add memgentic[sqlite-vec]  (or pip install sqlite-vec)"
            ) from exc

        path = self._settings.sqlite_path
        path.parent.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(str(path))
        # aiosqlite runs the underlying sqlite3 connection in a dedicated thread;
        # the extension must be loaded from that same thread. Use _execute to
        # marshal the sqlite_vec.load call onto it.
        await conn.enable_load_extension(True)
        await conn._execute(sqlite_vec.load, conn._conn)  # type: ignore[attr-defined]
        await conn.enable_load_extension(False)

        # Concurrency-friendly PRAGMAs — match MetadataStore.initialize
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")

        # Sanity check the extension loaded
        async with conn.execute("SELECT vec_version()") as cur:
            row = await cur.fetchone()
            if not row:
                raise StorageError("sqlite-vec loaded but vec_version() returned nothing")
            logger.info("sqlite_vec.loaded", version=row[0])

        dim = self._settings.embedding_dimensions
        await conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.VEC_TABLE} "
            f"USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{dim}])"
        )
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.PAYLOAD_TABLE} ("
            "  id TEXT PRIMARY KEY,"
            "  content TEXT,"
            "  content_type TEXT,"
            "  platform TEXT,"
            "  platform_version TEXT,"
            "  session_id TEXT,"
            "  session_title TEXT,"
            "  topics_json TEXT,"
            "  entities_json TEXT,"
            "  confidence REAL,"
            "  status TEXT,"
            "  created_at TEXT,"
            "  user_id TEXT"
            ")"
        )
        # Embedding-model safety pin (matches the intent of the Qdrant PR #19 pin)
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.PIN_TABLE} ("
            "  id INTEGER PRIMARY KEY CHECK (id = 1),"
            "  provider TEXT NOT NULL,"
            "  model TEXT NOT NULL,"
            "  dimensions INTEGER NOT NULL"
            ")"
        )
        # Indexes for filter predicates
        for col in ("platform", "content_type", "status", "user_id", "confidence"):
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.PAYLOAD_TABLE}_{col} "
                f"ON {self.PAYLOAD_TABLE}({col})"
            )
        await conn.commit()

        self._conn = conn
        await self._verify_embedding_compatibility()
        logger.info(
            "sqlite_vec.initialized",
            path=str(path),
            dimensions=dim,
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # --- embedding-model safety pin -------------------------------------

    async def _verify_embedding_compatibility(self) -> None:
        """On first init, pin the active embedding model. On later inits, verify."""
        assert self._conn is not None
        async with self._conn.execute(
            f"SELECT provider, model, dimensions FROM {self.PIN_TABLE} WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()

        expected_provider = self._settings.embedding_provider.value
        expected_model = self._settings.embedding_model
        expected_dim = self._settings.embedding_dimensions

        if row is None:
            await self._conn.execute(
                f"INSERT INTO {self.PIN_TABLE} (id, provider, model, dimensions) "
                "VALUES (1, ?, ?, ?)",
                (expected_provider, expected_model, expected_dim),
            )
            await self._conn.commit()
            logger.info(
                "sqlite_vec.embedding_pinned",
                provider=expected_provider,
                model=expected_model,
                dimensions=expected_dim,
            )
            return

        provider, model, dim = row
        if (provider, model, int(dim)) != (expected_provider, expected_model, expected_dim):
            raise StorageError(
                "Embedding configuration mismatch for sqlite-vec store. "
                f"Store was pinned to provider={provider} model={model} dim={dim}, "
                f"but current settings are provider={expected_provider} "
                f"model={expected_model} dim={expected_dim}. "
                "Run `memgentic re-embed` after changing embedding models."
            )

    # --- writes ---------------------------------------------------------

    async def upsert_memory(self, memory: Memory, embedding: list[float]) -> None:
        if self._conn is None:
            raise StorageError("SqliteVecBackend not initialized — call initialize() first")
        await self._upsert_one(memory, embedding)
        await self._conn.commit()

    async def upsert_memories_batch(
        self, memories: list[Memory], embeddings: list[list[float]]
    ) -> None:
        if self._conn is None:
            raise StorageError("SqliteVecBackend not initialized — call initialize() first")
        if len(memories) != len(embeddings):
            raise StorageError(
                f"Memories/embeddings count mismatch: {len(memories)} vs {len(embeddings)}"
            )
        for mem, emb in zip(memories, embeddings, strict=False):
            await self._upsert_one(mem, emb)
        await self._conn.commit()
        logger.info("sqlite_vec.batch_upserted", count=len(memories))

    async def _upsert_one(self, memory: Memory, embedding: list[float]) -> None:
        assert self._conn is not None
        if len(embedding) != self._settings.embedding_dimensions:
            raise StorageError(
                f"Embedding dim {len(embedding)} != configured "
                f"{self._settings.embedding_dimensions}"
            )
        packed = _pack_float32(embedding)
        # vec0 virtual tables use INSERT OR REPLACE for upsert semantics
        await self._conn.execute(
            f"INSERT OR REPLACE INTO {self.VEC_TABLE} (id, embedding) VALUES (?, ?)",
            (memory.id, packed),
        )
        payload = _memory_to_payload(memory)
        await self._conn.execute(
            f"INSERT OR REPLACE INTO {self.PAYLOAD_TABLE} ("
            "  id, content, content_type, platform, platform_version,"
            "  session_id, session_title, topics_json, entities_json,"
            "  confidence, status, created_at, user_id"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory.id,
                payload["content"],
                payload["content_type"],
                payload["platform"],
                payload["platform_version"],
                payload["session_id"],
                payload["session_title"],
                json.dumps(payload["topics"]),
                json.dumps(payload["entities"]),
                payload["confidence"],
                payload["status"],
                payload["created_at"],
                payload["user_id"],
            ),
        )

    async def delete_memory(self, memory_id: str) -> None:
        if self._conn is None:
            raise StorageError("SqliteVecBackend not initialized")
        await self._conn.execute(f"DELETE FROM {self.VEC_TABLE} WHERE id = ?", (memory_id,))
        await self._conn.execute(f"DELETE FROM {self.PAYLOAD_TABLE} WHERE id = ?", (memory_id,))
        await self._conn.commit()

    # --- reads ----------------------------------------------------------

    # Multiplier used to over-fetch ANN candidates when the caller provides
    # payload filters. sqlite-vec applies ``k = ?`` at the index layer before
    # SQLite post-filters the JOINed payload rows, so a naive ``k = limit``
    # can return fewer than ``limit`` results (or zero) when all top-k
    # candidates are excluded by the filter. Qdrant's server-side filtering
    # doesn't have this asymmetry. A 10× pool handles the common case; users
    # with very selective filters can lean on the raw ``_K_OVERFETCH_MAX``
    # ceiling below.
    _K_OVERFETCH_MULTIPLIER = 10
    _K_OVERFETCH_MAX = 1000

    async def search(
        self,
        query_embedding: list[float],
        session_config: SessionConfig | None = None,
        limit: int = 10,
        user_id: str = "",
    ) -> list[dict]:
        if self._conn is None:
            raise StorageError("SqliteVecBackend not initialized")

        where_sql, where_params = self._build_sql_where(session_config, user_id=user_id)
        packed = _pack_float32(query_embedding)

        # When there are no payload filters the two limits are identical —
        # keep k = limit to avoid pointless work. With filters, over-fetch so
        # post-filter truncation doesn't silently starve the result set.
        has_filters = bool(where_sql)
        k = (
            min(limit * self._K_OVERFETCH_MULTIPLIER, self._K_OVERFETCH_MAX)
            if has_filters
            else limit
        )

        # sqlite-vec KNN: MATCH ? AND k = ?. Apply payload filters with AND.
        sql = (
            f"SELECT v.id, v.distance, "
            "  p.content, p.content_type, p.platform, p.platform_version,"
            "  p.session_id, p.session_title, p.topics_json, p.entities_json,"
            "  p.confidence, p.status, p.created_at, p.user_id "
            f"FROM {self.VEC_TABLE} v "
            f"JOIN {self.PAYLOAD_TABLE} p ON p.id = v.id "
            "WHERE v.embedding MATCH ? AND k = ? "
        )
        params: list[Any] = [packed, k]
        if where_sql:
            sql += f"AND {where_sql} "
            params.extend(where_params)
        # Cap the final result set at ``limit`` — we over-fetched candidates,
        # not results.
        sql += "ORDER BY v.distance LIMIT ?"
        params.append(limit)

        results: list[dict] = []
        async with self._conn.execute(sql, params) as cur:
            async for row in cur:
                (
                    mid,
                    distance,
                    content,
                    content_type,
                    platform,
                    platform_version,
                    session_id,
                    session_title,
                    topics_json,
                    entities_json,
                    confidence,
                    status,
                    created_at,
                    row_user_id,
                ) = row
                # Cosine distance in sqlite-vec is in [0, 2]; convert to similarity.
                score = 1.0 - float(distance)
                results.append(
                    {
                        "id": str(mid),
                        "score": score,
                        "payload": {
                            "content": content,
                            "content_type": content_type,
                            "platform": platform,
                            "platform_version": platform_version,
                            "session_id": session_id,
                            "session_title": session_title,
                            "topics": json.loads(topics_json) if topics_json else [],
                            "entities": json.loads(entities_json) if entities_json else [],
                            "confidence": confidence,
                            "status": status,
                            "created_at": created_at,
                            "user_id": row_user_id,
                        },
                    }
                )
        return results

    async def get_collection_info(self) -> dict:
        if self._conn is None:
            raise StorageError("SqliteVecBackend not initialized")
        async with self._conn.execute(f"SELECT COUNT(*) FROM {self.PAYLOAD_TABLE}") as cur:
            row = await cur.fetchone()
            count = int(row[0]) if row else 0
        return {
            "indexed_vectors_count": count,
            "points_count": count,
            "status": "green",
        }

    # --- filter translation --------------------------------------------

    @staticmethod
    def _build_sql_where(config: SessionConfig | None, user_id: str = "") -> tuple[str, list[Any]]:
        """Translate SessionConfig into a parameterised SQL WHERE clause.

        Mirrors ``VectorStore._build_filter`` predicate-for-predicate:
        status=active, user_id, platform IN/NOT IN, content_type IN,
        confidence >=.
        """
        clauses: list[str] = []
        params: list[Any] = []

        # Always filter to active memories (matches Qdrant behaviour)
        clauses.append("p.status = ?")
        params.append("active")

        if user_id:
            clauses.append("p.user_id = ?")
            params.append(user_id)

        if config is None:
            return " AND ".join(clauses), params

        if config.include_sources:
            placeholders = ", ".join("?" for _ in config.include_sources)
            clauses.append(f"p.platform IN ({placeholders})")
            params.extend(s.value for s in config.include_sources)

        if config.exclude_sources:
            placeholders = ", ".join("?" for _ in config.exclude_sources)
            clauses.append(f"p.platform NOT IN ({placeholders})")
            params.extend(s.value for s in config.exclude_sources)

        if config.include_content_types:
            placeholders = ", ".join("?" for _ in config.include_content_types)
            clauses.append(f"p.content_type IN ({placeholders})")
            params.extend(ct.value for ct in config.include_content_types)

        if config.min_confidence > 0:
            clauses.append("p.confidence >= ?")
            params.append(config.min_confidence)

        return " AND ".join(clauses), params
