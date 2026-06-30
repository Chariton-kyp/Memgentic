"""SQLite metadata store for memory records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import structlog

from memgentic.exceptions import StorageError
from memgentic.models import (
    Collection,
    ContentType,
    DreamPatch,
    DreamPatchAction,
    DreamPatchStatus,
    DreamRun,
    DreamStatus,
    IngestionJob,
    IngestionJobStatus,
    Memory,
    MemoryStatus,
    Platform,
    SessionConfig,
    Skill,
    SkillFile,
    Upload,
    UploadStatus,
)

logger = structlog.get_logger()

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL,

    -- Source provenance
    platform TEXT NOT NULL,
    platform_version TEXT,
    session_id TEXT,
    session_title TEXT,
    capture_method TEXT NOT NULL,
    original_timestamp TEXT,
    file_path TEXT,

    -- Knowledge metadata
    topics TEXT NOT NULL DEFAULT '[]',
    entities TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 1.0,
    supersedes TEXT NOT NULL DEFAULT '[]',

    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_accessed TEXT,
    access_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memories_platform ON memories(platform);
CREATE INDEX IF NOT EXISTS idx_memories_content_type ON memories(content_type);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_session_id ON memories(session_id);
-- The ``project`` column is added via migration 9 for upgraded databases. The
-- index here costs nothing on fresh installs (created in the same migration)
-- but lets the metadata store query plans stay consistent across paths.

-- Full-text search on content
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    content,
    topics,
    entities,
    content='memories',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, content, topics, entities)
    VALUES (new.rowid, new.id, new.content, new.topics, new.entities);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, topics, entities)
    VALUES ('delete', old.rowid, old.id, old.content, old.topics, old.entities);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, content, topics, entities)
    VALUES ('delete', old.rowid, old.id, old.content, old.topics, old.entities);
    INSERT INTO memories_fts(rowid, id, content, topics, entities)
    VALUES (new.rowid, new.id, new.content, new.topics, new.entities);
END;

-- Track processed files to avoid re-ingestion
CREATE TABLE IF NOT EXISTS processed_files (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    platform TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    memory_count INTEGER NOT NULL DEFAULT 0
);

"""


class MetadataStore:
    """SQLite-backed metadata store for Memgentic memories."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        # Concurrency-friendly PRAGMAs — must run before any schema/migrations.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(CREATE_TABLE_SQL)
        await self._db.commit()

        from memgentic.storage.migrations import migrate

        applied = await migrate(self._db)
        if applied:
            logger.info("metadata_store.migrations_applied", count=applied)

        logger.info("metadata_store.initialized", path=str(self._db_path))

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # --- Embedding config (pinned to prevent silent model/dim mismatch) ---

    async def get_embedding_config(self) -> dict[str, str] | None:
        """Return the embedding model+dimensions pinned to the current collection,
        or None if nothing has been recorded yet (fresh install).
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        cursor = await self._db.execute("SELECT key, value FROM embedding_config")
        rows = await cursor.fetchall()
        if not rows:
            return None
        config = {row["key"]: row["value"] for row in rows}
        # Require both keys to consider config valid
        if "model" not in config or "dimensions" not in config:
            return None
        return config

    async def set_embedding_config(self, model: str, dimensions: int) -> None:
        """Pin the embedding model + dimensions that built the current collection.
        Called exactly once, the first time the collection is created.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT OR REPLACE INTO embedding_config (key, value, updated_at) VALUES (?, ?, ?)",
            ("model", model, now),
        )
        await self._db.execute(
            "INSERT OR REPLACE INTO embedding_config (key, value, updated_at) VALUES (?, ?, ?)",
            ("dimensions", str(dimensions), now),
        )
        await self._db.commit()

    async def clear_embedding_config(self) -> None:
        """Remove the pinned embedding config. Used by `memgentic re-embed` after
        the collection has been rebuilt with a new model.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        await self._db.execute("DELETE FROM embedding_config")
        await self._db.commit()

    # --- Runtime settings (persistent across restarts, mutable via CLI/REST/MCP) ---

    async def get_runtime_setting(self, key: str) -> str | None:
        """Return a runtime setting value, or None if unset."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        cursor = await self._db.execute(
            "SELECT value FROM runtime_settings WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_runtime_setting(self, key: str, value: str) -> None:
        """Upsert a runtime setting."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT OR REPLACE INTO runtime_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )
        await self._db.commit()

    async def update_dual_sibling(self, memory_id: str, sibling_id: str) -> None:
        """Record the ``dual_sibling_id`` pointer for a dual-profile memory."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        await self._db.execute(
            "UPDATE memories SET dual_sibling_id = ? WHERE id = ?",
            (sibling_id, memory_id),
        )
        await self._db.commit()

    async def save_memory(self, memory: Memory) -> None:
        """Insert or update a memory record."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        # ``updated_at`` is stamped server-side on every save so the retention
        # GC sweep has a reliable "last modified" anchor (e.g. the moment a row
        # was archived/superseded). The Memory model carries no updated_at
        # field — it is bookkeeping only.
        now_iso = datetime.now(UTC).isoformat()
        await self._db.execute(
            """
            INSERT OR REPLACE INTO memories
            (id, content, content_type, platform, platform_version, session_id,
             session_title, capture_method, original_timestamp, file_path,
             topics, entities, confidence, supersedes, status, created_at,
             last_accessed, access_count, importance_score, corroborated_by,
             user_id, is_pinned, pinned_at, capture_profile, dual_sibling_id,
             project, updated_at, distilled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory.id,
                memory.content,
                memory.content_type.value,
                memory.source.platform.value,
                memory.source.platform_version,
                memory.source.session_id,
                memory.source.session_title,
                memory.source.capture_method.value,
                memory.source.original_timestamp.isoformat()
                if memory.source.original_timestamp
                else None,
                memory.source.file_path,
                json.dumps(memory.topics),
                json.dumps(memory.entities),
                memory.confidence,
                json.dumps(memory.supersedes),
                memory.status.value,
                memory.created_at.isoformat(),
                memory.last_accessed.isoformat() if memory.last_accessed else None,
                memory.access_count,
                memory.importance_score,
                json.dumps(memory.corroborated_by),
                memory.user_id,
                1 if memory.is_pinned else 0,
                memory.pinned_at.isoformat() if memory.pinned_at else None,
                memory.capture_profile,
                memory.dual_sibling_id,
                memory.project or "",
                now_iso,
                memory.distilled,
            ),
        )
        await self._db.commit()

    async def save_memories_batch(self, memories: list[Memory]) -> None:
        """Insert multiple memories in a single transaction."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        now_iso = datetime.now(UTC).isoformat()
        rows = [
            (
                m.id,
                m.content,
                m.content_type.value,
                m.source.platform.value,
                m.source.platform_version,
                m.source.session_id,
                m.source.session_title,
                m.source.capture_method.value,
                m.source.original_timestamp.isoformat() if m.source.original_timestamp else None,
                m.source.file_path,
                json.dumps(m.topics),
                json.dumps(m.entities),
                m.confidence,
                json.dumps(m.supersedes),
                m.status.value,
                m.created_at.isoformat(),
                m.last_accessed.isoformat() if m.last_accessed else None,
                m.access_count,
                m.importance_score,
                json.dumps(m.corroborated_by),
                m.user_id,
                1 if m.is_pinned else 0,
                m.pinned_at.isoformat() if m.pinned_at else None,
                m.capture_profile,
                m.dual_sibling_id,
                m.project or "",
                now_iso,
                m.distilled,
            )
            for m in memories
        ]
        await self._db.executemany(
            """
            INSERT OR REPLACE INTO memories
            (id, content, content_type, platform, platform_version, session_id,
             session_title, capture_method, original_timestamp, file_path,
             topics, entities, confidence, supersedes, status, created_at,
             last_accessed, access_count, importance_score, corroborated_by,
             user_id, is_pinned, pinned_at, capture_profile, dual_sibling_id,
             project, updated_at, distilled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self._db.commit()
        logger.info("metadata_store.batch_saved", count=len(memories))

    async def get_memory(self, memory_id: str, user_id: str = "") -> Memory | None:
        """Retrieve a single memory by ID."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            )
        else:
            cursor = await self._db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = await cursor.fetchone()
        return self._row_to_memory(row) if row else None

    async def get_memories_batch(self, ids: list[str]) -> dict[str, Memory | None]:
        """Batch-fetch memories by ID. Returns dict mapping id → Memory (or None if missing)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        sql = f"SELECT * FROM memories WHERE id IN ({placeholders})"
        cursor = await self._db.execute(sql, ids)
        rows = await cursor.fetchall()
        result: dict[str, Memory | None] = {mid: None for mid in ids}
        for row in rows:
            memory = self._row_to_memory(row)
            result[memory.id] = memory
        return result

    async def search_fulltext(
        self,
        query: str,
        session_config: SessionConfig | None = None,
        limit: int = 10,
        user_id: str = "",
    ) -> list[Memory]:
        """Full-text search on content, topics, and entities."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        conditions, params = self._build_filter_conditions(session_config)

        if user_id:
            conditions.append("m.user_id = ?")
            params.append(user_id)

        # Escape for FTS5 phrase match — wrap in double quotes, escape internal quotes
        safe_query = '"' + query.replace('"', '""') + '"'

        sql = f"""
            SELECT m.* FROM memories m
            JOIN memories_fts fts ON m.rowid = fts.rowid
            WHERE memories_fts MATCH ?
            AND m.status = 'active'
            {" AND " + " AND ".join(conditions) if conditions else ""}
            ORDER BY rank
            LIMIT ?
        """
        params = [safe_query, *params, limit]
        try:
            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()
        except Exception:
            logger.warning("metadata_store.fts_query_failed", query=query)
            return []
        return [self._row_to_memory(row) for row in rows]

    async def get_memories_by_filter(
        self,
        session_config: SessionConfig | None = None,
        content_type: ContentType | None = None,
        limit: int = 50,
        offset: int = 0,
        user_id: str = "",
    ) -> list[Memory]:
        """Query memories with optional filtering."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        conditions, params = self._build_filter_conditions(session_config)

        if content_type:
            conditions.append("content_type = ?")
            params.append(content_type.value)

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where = "WHERE status = 'active'"
        if conditions:
            where += " AND " + " AND ".join(conditions)

        sql = f"""
            SELECT * FROM memories {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def get_source_stats(self, user_id: str = "") -> dict[str, int]:
        """Get memory count per source platform."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT platform, COUNT(*) as cnt FROM memories "
                "WHERE status = 'active' AND user_id = ? GROUP BY platform",
                (user_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT platform, COUNT(*) as cnt FROM memories "
                "WHERE status = 'active' GROUP BY platform"
            )
        rows = await cursor.fetchall()
        return {row["platform"]: row["cnt"] for row in rows}

    async def get_project_stats(self, user_id: str = "") -> dict[str, int]:
        """Get memory count per project key.

        Memories with an empty ``project`` are reported under the literal key
        ``""`` so the dashboard can render a "No project" bucket explicitly.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT project, COUNT(*) as cnt FROM memories "
                "WHERE status = 'active' AND user_id = ? GROUP BY project "
                "ORDER BY cnt DESC",
                (user_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT project, COUNT(*) as cnt FROM memories "
                "WHERE status = 'active' GROUP BY project ORDER BY cnt DESC"
            )
        rows = await cursor.fetchall()
        return {(row["project"] or ""): row["cnt"] for row in rows}

    async def get_filtered_count(
        self,
        session_config: SessionConfig | None = None,
        content_type: ContentType | None = None,
        user_id: str = "",
    ) -> int:
        """Count memories matching filters without loading all records."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        query = "SELECT COUNT(*) FROM memories WHERE status = 'active'"
        params: list = []

        conditions, cond_params = self._build_filter_conditions(session_config)
        if conditions:
            query += " AND " + " AND ".join(conditions)
        params.extend(cond_params)

        if content_type:
            query += " AND content_type = ?"
            params.append(content_type.value)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_content_type_counts(self, user_id: str = "") -> dict[str, int]:
        """Active memory counts grouped by content_type."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT content_type, COUNT(*) AS cnt FROM memories "
                "WHERE status = 'active' AND user_id = ? GROUP BY content_type",
                (user_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT content_type, COUNT(*) AS cnt FROM memories "
                "WHERE status = 'active' GROUP BY content_type"
            )
        rows = await cursor.fetchall()
        return {row["content_type"]: int(row["cnt"]) for row in rows}

    async def get_capture_profile_counts(self, user_id: str = "") -> dict[str, int]:
        """Active memory counts grouped by capture_profile (defaults to 'enriched')."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        try:
            if user_id:
                cursor = await self._db.execute(
                    "SELECT capture_profile, COUNT(*) AS cnt FROM memories "
                    "WHERE status = 'active' AND user_id = ? GROUP BY capture_profile",
                    (user_id,),
                )
            else:
                cursor = await self._db.execute(
                    "SELECT capture_profile, COUNT(*) AS cnt FROM memories "
                    "WHERE status = 'active' GROUP BY capture_profile"
                )
            rows = await cursor.fetchall()
            return {(row["capture_profile"] or "enriched"): int(row["cnt"]) for row in rows}
        except Exception:
            return {}

    async def get_total_count(self, user_id: str = "") -> int:
        """Get total active memory count."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT COUNT(*) as cnt FROM memories WHERE status = 'active' AND user_id = ?",
                (user_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT COUNT(*) as cnt FROM memories WHERE status = 'active'"
            )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def update_access(self, memory_id: str) -> None:
        """Update last_accessed and access_count for a retrieved memory."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        await self._db.commit()

    async def is_file_processed(self, file_path: str, file_hash: str) -> bool:
        """Check if a file has already been processed (deduplication)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            "SELECT file_hash FROM processed_files WHERE file_path = ?",
            (file_path,),
        )
        row = await cursor.fetchone()
        return row is not None and row["file_hash"] == file_hash

    async def mark_file_processed(
        self, file_path: str, file_hash: str, platform: str, memory_count: int
    ) -> None:
        """Mark a file as processed."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """
            INSERT OR REPLACE INTO processed_files
            (file_path, file_hash, platform, processed_at, memory_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_path, file_hash, platform, now, memory_count),
        )
        await self._db.commit()

    async def get_memories_since(
        self,
        since: datetime,
        session_config: SessionConfig | None = None,
        limit: int = 100,
        user_id: str = "",
    ) -> list[Memory]:
        """Get memories created after `since` timestamp."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        conditions = ["status = 'active'", "created_at > ?"]
        params: list = [since.isoformat()]

        # Add session config filters if provided
        if session_config:
            extra_conds, extra_params = self._build_filter_conditions(session_config)
            conditions.extend(extra_conds)
            params.extend(extra_params)

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def get_recent_session_handoffs(
        self,
        *,
        since: datetime | None = None,
        session_config: SessionConfig | None = None,
        limit_sessions: int = 3,
        memories_per_session: int = 5,
        user_id: str = "",
    ) -> list[dict]:
        """Return recent memories grouped by original source session.

        This is the backbone for cross-tool continuation: when an agent starts
        in Codex, Claude Code, Gemini CLI, etc., it can ask for the most recent
        source sessions and receive compact bundles that preserve provenance.
        The method intentionally derives handoffs from the existing memories
        table so the first version needs no new schema.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        limit_sessions = max(1, min(20, int(limit_sessions)))
        memories_per_session = max(1, min(20, int(memories_per_session)))

        conditions = ["status = 'active'"]
        params: list = []
        if since is not None:
            conditions.append("created_at > ?")
            params.append(since.isoformat())

        if session_config:
            extra_conds, extra_params = self._build_filter_conditions(session_config)
            conditions.extend(extra_conds)
            params.extend(extra_params)

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where = " AND ".join(conditions)
        # Over-fetch so a noisy latest session does not hide the next one.
        row_limit = max(limit_sessions * memories_per_session * 8, 100)
        sql = f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(row_limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        sessions: dict[tuple[str, str], dict] = {}
        ordered_keys: list[tuple[str, str]] = []

        for row in rows:
            memory = self._row_to_memory(row)
            platform = memory.source.platform.value
            # Only bundle memories that come from a real source session.
            # session_id or file_path is required; bare titles (from manual
            # memgentic_remember calls) would otherwise become singleton bundles
            # and pollute the top-N.
            raw_session_key = memory.source.session_id or memory.source.file_path
            if not raw_session_key:
                continue
            key = (platform, raw_session_key)
            if key not in sessions:
                sessions[key] = {
                    "platform": platform,
                    "session_id": memory.source.session_id,
                    "session_title": memory.source.session_title,
                    "file_path": memory.source.file_path,
                    "last_activity": memory.created_at,
                    "memories": [],
                    "memory_count": 0,
                    "topics": [],
                    "entities": [],
                }
                ordered_keys.append(key)

            bundle = sessions[key]
            bundle["memory_count"] += 1
            if memory.created_at > bundle["last_activity"]:
                bundle["last_activity"] = memory.created_at
            if len(bundle["memories"]) < memories_per_session:
                bundle["memories"].append(memory)
            for topic in memory.topics:
                if topic not in bundle["topics"]:
                    bundle["topics"].append(topic)
            for entity in memory.entities:
                if entity not in bundle["entities"]:
                    bundle["entities"].append(entity)

        return [sessions[key] for key in ordered_keys[:limit_sessions]]

    async def get_top_memories(
        self,
        limit: int = 5,
        user_id: str = "",
    ) -> list[Memory]:
        """Return the highest-importance active memories (all-time).

        Used as a fallback for briefing generation when no recent memories exist.
        Tie-breaks on recency (most recent first).
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        conditions = ["status = 'active'"]
        params: list = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where = " AND ".join(conditions)
        sql = (
            f"SELECT * FROM memories WHERE {where} "
            "ORDER BY importance_score DESC, created_at DESC LIMIT ?"
        )
        params.append(limit)
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def update_importance_score(self, memory_id: str, score: float) -> None:
        """Update a memory's importance score."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            "UPDATE memories SET importance_score = ? WHERE id = ?",
            (round(score, 4), memory_id),
        )
        await self._db.commit()

    async def update_importance_scores_batch(self, updates: list[tuple[str, float]]) -> None:
        """Batch update importance scores. updates = [(memory_id, score), ...]"""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.executemany(
            "UPDATE memories SET importance_score = ? WHERE id = ?",
            [(round(score, 4), mid) for mid, score in updates],
        )
        await self._db.commit()

    async def update_memory_status(self, memory_id: str, status: str, user_id: str = "") -> None:
        """Update a memory's lifecycle status (active, archived, superseded).

        Also stamps ``updated_at`` so the retention GC sweep can measure the
        grace period from the moment the row was archived/superseded.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        now_iso = datetime.now(UTC).isoformat()
        if user_id:
            await self._db.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (status, now_iso, memory_id, user_id),
            )
        else:
            await self._db.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso, memory_id),
            )
        await self._db.commit()

    async def get_gc_candidates(
        self,
        *,
        before_iso: str,
        limit: int = 10_000,
        user_id: str = "",
    ) -> list[Memory]:
        """Return memories eligible for retention hard-deletion.

        A row is a candidate only when it is **already soft-deleted**
        (``status IN ('archived','superseded')``) AND its last-modified anchor
        (``COALESCE(updated_at, created_at)``) is older than ``before_iso``.

        The two absolute safety rules are enforced directly in SQL: pinned rows
        (``is_pinned = 1``) and owner-deliberate ``mcp_tool`` captures are
        excluded and can never be returned as candidates. Active rows are never
        returned.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        params: list = [before_iso]
        user_clause = ""
        if user_id:
            user_clause = "AND user_id = ?"
            params.append(user_id)
        params.append(limit)
        sql = f"""
            SELECT * FROM memories
            WHERE status IN ('archived', 'superseded')
              AND is_pinned = 0
              AND capture_method != 'mcp_tool'
              AND COALESCE(updated_at, created_at) < ?
              {user_clause}
            ORDER BY COALESCE(updated_at, created_at) ASC
            LIMIT ?
        """
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def hard_delete_memories(self, ids: list[str]) -> int:
        """Permanently DELETE memories by id and return the rows removed.

        Safety-guarded at the SQL level (defense in depth): the DELETE only
        affects rows that are ``archived``/``superseded``, **not** pinned, and
        **not** ``mcp_tool`` captures — so even a misused call can never drop an
        active, pinned, or owner-deliberate memory. Vector cleanup is the
        caller's responsibility (see ``retention.run_gc``).

        After the DELETE, any surviving row whose ``supersedes`` or
        ``corroborated_by`` JSON array references a just-purged id has that id
        removed (dangling provenance ref scrub). Both the DELETE and the
        provenance scrub share the same transaction.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        guard_where = (
            f"id IN ({placeholders}) "
            "AND status IN ('archived', 'superseded') "
            "AND is_pinned = 0 "
            "AND capture_method != 'mcp_tool'"
        )
        # Discover which ids will actually survive the guard before deleting,
        # so we only scrub ids that are truly purged (not merely rejected by the
        # SQL safety guard and still alive in the store).
        pre = await self._db.execute(f"SELECT id FROM memories WHERE {guard_where}", ids)
        pre_rows = await pre.fetchall()
        to_purge: set[str] = {row["id"] for row in pre_rows}

        cursor = await self._db.execute(f"DELETE FROM memories WHERE {guard_where}", ids)
        deleted = cursor.rowcount

        # Scrub provenance arrays on surviving rows — same transaction as DELETE.
        if to_purge:
            await self._scrub_provenance_refs(to_purge)

        await self._db.commit()
        logger.info("metadata_store.hard_deleted", requested=len(ids), deleted=deleted)
        return deleted

    async def _scrub_provenance_refs(self, purged_ids: set[str]) -> None:
        """Remove purged ids from ``supersedes`` / ``corroborated_by`` on surviving rows.

        Called within the hard-delete transaction (no separate commit). Only
        rows that actually reference a purged id are updated.
        """
        if not self._db:
            return
        cursor = await self._db.execute("SELECT id, supersedes, corroborated_by FROM memories")
        rows = await cursor.fetchall()
        for row in rows:
            sups: list[str] = json.loads(row["supersedes"]) if row["supersedes"] else []
            corrs: list[str] = json.loads(row["corroborated_by"]) if row["corroborated_by"] else []
            new_sups = [x for x in sups if x not in purged_ids]
            new_corrs = [x for x in corrs if x not in purged_ids]
            if new_sups != sups or new_corrs != corrs:
                await self._db.execute(
                    "UPDATE memories SET supersedes = ?, corroborated_by = ? WHERE id = ?",
                    (json.dumps(new_sups), json.dumps(new_corrs), row["id"]),
                )

    async def update_corroboration(
        self, memory_id: str, platform: str, new_confidence: float
    ) -> None:
        """Add a corroborating platform and update confidence."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        # Read current corroborated_by list
        cursor = await self._db.execute(
            "SELECT corroborated_by FROM memories WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return
        current = json.loads(row["corroborated_by"]) if row["corroborated_by"] else []
        if platform not in current:
            current.append(platform)
        await self._db.execute(
            "UPDATE memories SET corroborated_by = ?, confidence = ? WHERE id = ?",
            (json.dumps(current), min(new_confidence, 1.0), memory_id),
        )
        await self._db.commit()

    # --- Private helpers ---

    def _build_filter_conditions(self, config: SessionConfig | None) -> tuple[list[str], list]:
        """Build SQL WHERE conditions from session config."""
        conditions: list[str] = []
        params: list = []

        if not config:
            return conditions, params

        if config.include_sources:
            placeholders = ",".join("?" for _ in config.include_sources)
            conditions.append(f"platform IN ({placeholders})")
            params.extend(s.value for s in config.include_sources)

        if config.exclude_sources:
            placeholders = ",".join("?" for _ in config.exclude_sources)
            conditions.append(f"platform NOT IN ({placeholders})")
            params.extend(s.value for s in config.exclude_sources)

        if config.include_content_types:
            placeholders = ",".join("?" for _ in config.include_content_types)
            conditions.append(f"content_type IN ({placeholders})")
            params.extend(ct.value for ct in config.include_content_types)

        if config.exclude_content_types:
            placeholders = ",".join("?" for _ in config.exclude_content_types)
            conditions.append(f"content_type NOT IN ({placeholders})")
            params.extend(ct.value for ct in config.exclude_content_types)

        if config.min_confidence > 0:
            conditions.append("confidence >= ?")
            params.append(config.min_confidence)

        if config.include_projects:
            placeholders = ",".join("?" for _ in config.include_projects)
            conditions.append(f"project IN ({placeholders})")
            params.extend(p.lower() for p in config.include_projects)

        if config.exclude_projects:
            placeholders = ",".join("?" for _ in config.exclude_projects)
            conditions.append(f"project NOT IN ({placeholders})")
            params.extend(p.lower() for p in config.exclude_projects)

        return conditions, params

    @staticmethod
    def _row_to_memory(row: aiosqlite.Row) -> Memory:
        """Convert a database row to a Memory model."""
        from memgentic.models import CaptureMethod, SourceMetadata

        # Read user_id with fallback for pre-migration databases
        try:
            user_id = row["user_id"]
        except (IndexError, KeyError):
            user_id = ""

        # Read is_pinned/pinned_at with fallback for pre-migration databases
        try:
            is_pinned = bool(row["is_pinned"])
        except (IndexError, KeyError):
            is_pinned = False

        try:
            pinned_at_raw = row["pinned_at"]
            pinned_at = datetime.fromisoformat(pinned_at_raw) if pinned_at_raw else None
        except (IndexError, KeyError):
            pinned_at = None

        # capture_profile/dual_sibling_id are added in migration 8. Older rows
        # (pre-migration snapshots, test fixtures) may lack them — fall back to
        # the default rather than crashing deserialisation.
        try:
            capture_profile = row["capture_profile"] or "enriched"
            if capture_profile not in ("raw", "enriched", "dual"):
                capture_profile = "enriched"
        except (IndexError, KeyError):
            capture_profile = "enriched"

        try:
            dual_sibling_id = row["dual_sibling_id"]
        except (IndexError, KeyError):
            dual_sibling_id = None

        # project added in migration 9; default to empty string when absent so
        # legacy fixtures and pre-migration databases keep deserialising.
        try:
            project = row["project"] or ""
        except (IndexError, KeyError):
            project = ""

        # distilled added in migration 13; NULL on raw/legacy rows. Fall back to
        # None so pre-migration snapshots / fixtures keep deserialising.
        try:
            distilled = row["distilled"]
        except (IndexError, KeyError):
            distilled = None

        return Memory(
            id=row["id"],
            user_id=user_id or "",
            content=row["content"],
            content_type=ContentType(row["content_type"]),
            distilled=distilled,
            source=SourceMetadata(
                platform=Platform(row["platform"]),
                platform_version=row["platform_version"],
                session_id=row["session_id"],
                session_title=row["session_title"],
                capture_method=CaptureMethod(row["capture_method"]),
                original_timestamp=datetime.fromisoformat(row["original_timestamp"])
                if row["original_timestamp"]
                else None,
                file_path=row["file_path"],
            ),
            topics=json.loads(row["topics"]),
            entities=json.loads(row["entities"]),
            confidence=row["confidence"],
            supersedes=json.loads(row["supersedes"]),
            status=MemoryStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"])
            if row["last_accessed"]
            else None,
            access_count=row["access_count"],
            importance_score=row["importance_score"],
            corroborated_by=json.loads(row["corroborated_by"]) if row["corroborated_by"] else [],
            is_pinned=is_pinned,
            pinned_at=pinned_at,
            capture_profile=capture_profile,
            dual_sibling_id=dual_sibling_id,
            project=project,
        )

    # ── Collection methods ──────────────────────────────────────────────

    async def create_collection(self, collection: Collection) -> None:
        """Insert a new collection."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            INSERT INTO collections
            (id, user_id, name, description, color, icon, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection.id,
                collection.user_id,
                collection.name,
                collection.description,
                collection.color,
                collection.icon,
                collection.position,
                collection.created_at.isoformat(),
                collection.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_collections(self, user_id: str = "") -> list[Collection]:
        """List collections ordered by position."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT * FROM collections WHERE user_id = ? ORDER BY position, created_at",
                (user_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM collections ORDER BY position, created_at"
            )
        rows = await cursor.fetchall()
        return [self._row_to_collection(row) for row in rows]

    async def get_collection(self, collection_id: str) -> Collection | None:
        """Get a single collection by ID."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute("SELECT * FROM collections WHERE id = ?", (collection_id,))
        row = await cursor.fetchone()
        return self._row_to_collection(row) if row else None

    async def update_collection(self, collection_id: str, **kwargs) -> None:
        """Update collection fields (name, description, color, icon, position)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        allowed = {"name", "description", "color", "icon", "position"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return
        updates["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        values.append(collection_id)
        await self._db.execute(
            f"UPDATE collections SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self._db.commit()

    async def delete_collection(self, collection_id: str) -> None:
        """Delete a collection (cascades to membership via FK)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        # Enable foreign keys so CASCADE works
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        await self._db.commit()

    async def add_memory_to_collection(
        self, collection_id: str, memory_id: str, position: float = 0
    ) -> None:
        """Add a memory to a collection."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            """
            INSERT OR IGNORE INTO collection_memories
            (collection_id, memory_id, position, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (collection_id, memory_id, position, now),
        )
        await self._db.commit()

    async def remove_memory_from_collection(self, collection_id: str, memory_id: str) -> None:
        """Remove a memory from a collection."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            "DELETE FROM collection_memories WHERE collection_id = ? AND memory_id = ?",
            (collection_id, memory_id),
        )
        await self._db.commit()

    async def get_collection_memories(
        self, collection_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        """Get memories in a collection via join query."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            """
            SELECT m.* FROM memories m
            JOIN collection_memories cm ON m.id = cm.memory_id
            WHERE cm.collection_id = ?
            ORDER BY cm.position, cm.added_at DESC
            LIMIT ? OFFSET ?
            """,
            (collection_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def get_collection_memory_count(self, collection_id: str) -> int:
        """Get the number of memories in a collection."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM collection_memories WHERE collection_id = ?",
            (collection_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_memory_collections(self, memory_id: str) -> list[Collection]:
        """Get which collections a memory belongs to."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            """
            SELECT c.* FROM collections c
            JOIN collection_memories cm ON c.id = cm.collection_id
            WHERE cm.memory_id = ?
            ORDER BY c.position, c.created_at
            """,
            (memory_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_collection(row) for row in rows]

    @staticmethod
    def _row_to_collection(row: aiosqlite.Row) -> Collection:
        """Convert a database row to a Collection model."""
        return Collection(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            color=row["color"],
            icon=row["icon"],
            position=row["position"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # ── Pin methods ─────────────────────────────────────────────────────

    async def pin_memory(self, memory_id: str) -> None:
        """Pin a memory for quick access."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE memories SET is_pinned = 1, pinned_at = ? WHERE id = ?",
            (now, memory_id),
        )
        await self._db.commit()

    async def unpin_memory(self, memory_id: str) -> None:
        """Unpin a memory."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            "UPDATE memories SET is_pinned = 0, pinned_at = NULL WHERE id = ?",
            (memory_id,),
        )
        await self._db.commit()

    async def get_pinned_memories(self, user_id: str = "", limit: int = 50) -> list[Memory]:
        """Return pinned memories ordered by pinned_at (most recent first)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                """
                SELECT * FROM memories
                WHERE is_pinned = 1 AND status = 'active' AND user_id = ?
                ORDER BY pinned_at DESC LIMIT ?
                """,
                (user_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT * FROM memories
                WHERE is_pinned = 1 AND status = 'active'
                ORDER BY pinned_at DESC LIMIT ?
                """,
                (limit,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    # ── Upload tracking ─────────────────────────────────────────────────

    async def create_upload(self, upload: Upload) -> None:
        """Insert a new upload tracking record."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            INSERT INTO uploads
            (id, user_id, memory_id, filename, mime_type, file_size,
             upload_source, original_url, status, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload.id,
                upload.user_id,
                upload.memory_id,
                upload.filename,
                upload.mime_type,
                upload.file_size,
                upload.upload_source,
                upload.original_url,
                upload.status.value,
                upload.error_message,
                upload.created_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def update_upload_status(
        self,
        upload_id: str,
        status: UploadStatus,
        memory_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update the status of an upload, optionally linking to the created memory."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            UPDATE uploads
            SET status = ?, memory_id = COALESCE(?, memory_id), error_message = ?
            WHERE id = ?
            """,
            (status.value, memory_id, error, upload_id),
        )
        await self._db.commit()

    async def get_uploads(self, user_id: str = "", limit: int = 50) -> list[Upload]:
        """List recent uploads ordered by creation time."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT * FROM uploads WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM uploads ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_upload(row) for row in rows]

    @staticmethod
    def _row_to_upload(row: aiosqlite.Row) -> Upload:
        """Convert a database row to an Upload model."""
        return Upload(
            id=row["id"],
            user_id=row["user_id"],
            memory_id=row["memory_id"],
            filename=row["filename"],
            mime_type=row["mime_type"],
            file_size=row["file_size"],
            upload_source=row["upload_source"],
            original_url=row["original_url"],
            status=UploadStatus(row["status"]),
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ── Batch operations ───────────────────────────────────────────────

    async def batch_update_memories(
        self,
        memory_ids: list[str],
        updates: dict,
    ) -> int:
        """Batch-update multiple memories. Returns the number of rows affected.

        Supported update keys: ``status`` (str), ``topics`` (list[str]).
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if not memory_ids:
            return 0

        updated = 0
        for memory_id in memory_ids:
            set_parts: list[str] = []
            params: list = []

            if "status" in updates:
                set_parts.append("status = ?")
                params.append(updates["status"])
            if "topics" in updates:
                set_parts.append("topics = ?")
                params.append(json.dumps(updates["topics"]))

            if not set_parts:
                continue

            params.append(memory_id)
            sql = f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ?"  # noqa: S608
            cursor = await self._db.execute(sql, params)
            updated += cursor.rowcount

        await self._db.commit()
        return updated

    async def batch_archive_memories(self, memory_ids: list[str]) -> int:
        """Archive (soft-delete) multiple memories. Returns the count archived."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if not memory_ids:
            return 0

        placeholders = ",".join("?" * len(memory_ids))
        cursor = await self._db.execute(
            f"UPDATE memories SET status = 'archived' WHERE id IN ({placeholders})",  # noqa: S608
            memory_ids,
        )
        await self._db.commit()
        return cursor.rowcount

    # ── Skill methods ──────────────────────────────────────────────────

    async def create_skill(self, skill: Skill) -> None:
        """Insert a new skill."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            INSERT INTO skills
            (id, user_id, name, description, content, config, source, source_url,
             version, tags, distribute_to, auto_distribute, source_memory_ids,
             auto_extracted, extraction_confidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill.id,
                skill.user_id,
                skill.name,
                skill.description,
                skill.content,
                json.dumps(skill.config),
                skill.source,
                skill.source_url,
                skill.version,
                json.dumps(skill.tags),
                json.dumps(skill.distribute_to),
                1 if skill.auto_distribute else 0,
                json.dumps(skill.source_memory_ids),
                1 if skill.auto_extracted else 0,
                skill.extraction_confidence,
                skill.created_at.isoformat(),
                skill.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_skills(self, user_id: str = "") -> list[Skill]:
        """List all skills, optionally filtered by user_id."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT * FROM skills WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
        else:
            cursor = await self._db.execute("SELECT * FROM skills ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_skill(row) for row in rows]

    async def get_skill(self, skill_id: str) -> Skill | None:
        """Get a skill by ID, including its files."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        skill = self._row_to_skill(row)
        skill.files = await self.get_skill_files(skill_id)
        return skill

    async def get_skill_by_name(self, name: str, user_id: str = "") -> Skill | None:
        """Get a skill by name, including its files."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            cursor = await self._db.execute(
                "SELECT * FROM skills WHERE name = ? AND user_id = ?",
                (name, user_id),
            )
        else:
            cursor = await self._db.execute("SELECT * FROM skills WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            return None
        skill = self._row_to_skill(row)
        skill.files = await self.get_skill_files(skill.id)
        return skill

    async def update_skill(self, skill_id: str, **kwargs) -> None:
        """Update skill fields."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        allowed = {
            "name",
            "description",
            "content",
            "config",
            "source",
            "source_url",
            "version",
            "tags",
            "distribute_to",
            "auto_distribute",
            "source_memory_ids",
            "auto_extracted",
            "extraction_confidence",
        }
        updates: dict = {}
        for k, v in kwargs.items():
            if k not in allowed or v is None:
                continue
            if k in ("config", "tags", "distribute_to", "source_memory_ids"):
                updates[k] = json.dumps(v)
            elif k in ("auto_distribute", "auto_extracted"):
                updates[k] = 1 if v else 0
            else:
                updates[k] = v

        if not updates:
            return

        updates["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        values.append(skill_id)
        await self._db.execute(
            f"UPDATE skills SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self._db.commit()

    async def delete_skill(self, skill_id: str) -> None:
        """Delete a skill (cascades to files and distributions via FK)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        await self._db.commit()

    async def create_skill_file(self, skill_file: SkillFile) -> None:
        """Add a file to a skill."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            INSERT INTO skill_files (id, skill_id, path, content, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                skill_file.id,
                skill_file.skill_id,
                skill_file.path,
                skill_file.content,
                skill_file.created_at.isoformat(),
                skill_file.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def update_skill_file(self, file_id: str, path: str, content: str) -> None:
        """Update a skill file's path and content."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "UPDATE skill_files SET path = ?, content = ?, updated_at = ? WHERE id = ?",
            (path, content, now, file_id),
        )
        await self._db.commit()

    async def delete_skill_file(self, file_id: str) -> None:
        """Delete a skill file."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute("DELETE FROM skill_files WHERE id = ?", (file_id,))
        await self._db.commit()

    async def get_skill_files(self, skill_id: str) -> list[SkillFile]:
        """List files for a skill."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            "SELECT * FROM skill_files WHERE skill_id = ? ORDER BY path",
            (skill_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_skill_file(row) for row in rows]

    async def log_skill_distribution(self, skill_id: str, tool: str, target_path: str) -> None:
        """Record a skill distribution to a tool."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        import uuid as _uuid

        now = datetime.now(UTC).isoformat()
        dist_id = str(_uuid.uuid4())
        await self._db.execute(
            """
            INSERT OR REPLACE INTO skill_distributions
            (id, skill_id, tool, target_path, distributed_at, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (dist_id, skill_id, tool, target_path, now),
        )
        await self._db.commit()

    async def get_skill_distributions(self, skill_id: str) -> list[dict]:
        """List distributions for a skill."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            "SELECT * FROM skill_distributions WHERE skill_id = ? ORDER BY distributed_at DESC",
            (skill_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "skill_id": row["skill_id"],
                "tool": row["tool"],
                "target_path": row["target_path"],
                "distributed_at": row["distributed_at"],
                "status": row["status"],
            }
            for row in rows
        ]

    async def delete_skill_distribution(self, skill_id: str, tool: str) -> None:
        """Remove a single skill distribution row by (skill_id, tool)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            "DELETE FROM skill_distributions WHERE skill_id = ? AND tool = ?",
            (skill_id, tool),
        )
        await self._db.commit()

    # ── Ingestion job methods ─────────────────────────────────────────

    async def create_ingestion_job(self, job: IngestionJob) -> None:
        """Insert a new ingestion job row."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            INSERT INTO ingestion_jobs
            (id, user_id, source_type, source_path, status, total_items,
             processed_items, failed_items, error_message, started_at,
             completed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.user_id,
                job.source_type,
                job.source_path,
                job.status.value,
                job.total_items,
                job.processed_items,
                job.failed_items,
                job.error_message,
                job.started_at.isoformat() if job.started_at else None,
                job.completed_at.isoformat() if job.completed_at else None,
                job.created_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_ingestion_jobs(
        self,
        user_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[IngestionJob], int]:
        """List ingestion jobs (most recent first) with total count.

        Returns ``(jobs, total)``.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))

        if user_id:
            count_cursor = await self._db.execute(
                "SELECT COUNT(*) FROM ingestion_jobs WHERE user_id = ?",
                (user_id,),
            )
            row_cursor = await self._db.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, safe_limit, safe_offset),
            )
        else:
            count_cursor = await self._db.execute("SELECT COUNT(*) FROM ingestion_jobs")
            row_cursor = await self._db.execute(
                """
                SELECT * FROM ingestion_jobs
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (safe_limit, safe_offset),
            )

        count_row = await count_cursor.fetchone()
        total = int(count_row[0]) if count_row and count_row[0] is not None else 0
        rows = await row_cursor.fetchall()
        jobs = [self._row_to_ingestion_job(row) for row in rows]
        return jobs, total

    async def get_ingestion_job(self, job_id: str) -> IngestionJob | None:
        """Fetch a single ingestion job by id."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            "SELECT * FROM ingestion_jobs WHERE id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_ingestion_job(row)

    async def update_ingestion_job(self, job_id: str, **kwargs) -> None:
        """Partially update an ingestion job.

        Supported fields: status, total_items, processed_items, failed_items,
        error_message, started_at, completed_at.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        allowed = {
            "status",
            "total_items",
            "processed_items",
            "failed_items",
            "error_message",
            "started_at",
            "completed_at",
        }
        updates: dict = {}
        for key, value in kwargs.items():
            if key not in allowed or value is None:
                continue
            if key == "status":
                updates[key] = value.value if isinstance(value, IngestionJobStatus) else str(value)
            elif key in ("started_at", "completed_at"):
                updates[key] = value.isoformat() if isinstance(value, datetime) else str(value)
            else:
                updates[key] = value

        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        values.append(job_id)
        await self._db.execute(
            f"UPDATE ingestion_jobs SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self._db.commit()

    @staticmethod
    def _row_to_ingestion_job(row: aiosqlite.Row) -> IngestionJob:
        """Convert a database row to an IngestionJob model."""
        return IngestionJob(
            id=row["id"],
            user_id=row["user_id"],
            source_type=row["source_type"],
            source_path=row["source_path"],
            status=IngestionJobStatus(row["status"]),
            total_items=row["total_items"],
            processed_items=row["processed_items"],
            failed_items=row["failed_items"],
            error_message=row["error_message"],
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"])
            if row["completed_at"]
            else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_skill(row: aiosqlite.Row) -> Skill:
        """Convert a database row to a Skill model."""
        return Skill(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            content=row["content"],
            config=json.loads(row["config"]) if row["config"] else {},
            source=row["source"],
            source_url=row["source_url"],
            version=row["version"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            distribute_to=json.loads(row["distribute_to"]) if row["distribute_to"] else [],
            auto_distribute=bool(row["auto_distribute"]),
            source_memory_ids=json.loads(row["source_memory_ids"])
            if row["source_memory_ids"]
            else [],
            auto_extracted=bool(row["auto_extracted"]),
            extraction_confidence=row["extraction_confidence"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_skill_file(row: aiosqlite.Row) -> SkillFile:
        """Convert a database row to a SkillFile model."""
        return SkillFile(
            id=row["id"],
            skill_id=row["skill_id"],
            path=row["path"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # ------------------------------------------------------------------
    # Dream runs + patches (auto-dream consolidation)
    # ------------------------------------------------------------------

    async def create_dream_run(self, run: DreamRun) -> None:
        """Insert a new dream run row."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        await self._db.execute(
            """
            INSERT INTO dream_runs
            (id, project, status, model, instructions, input_session_ids,
             input_memory_count, error, usage_input_tokens, usage_output_tokens,
             created_at, ended_at, applied_at, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.project,
                run.status.value,
                run.model,
                run.instructions,
                json.dumps(run.input_session_ids),
                run.input_memory_count,
                run.error,
                run.usage_input_tokens,
                run.usage_output_tokens,
                run.created_at.isoformat(),
                run.ended_at.isoformat() if run.ended_at else None,
                run.applied_at.isoformat() if run.applied_at else None,
                run.user_id,
            ),
        )
        await self._db.commit()

    async def update_dream_run(self, run_id: str, **kwargs) -> None:
        """Partially update a dream run.

        Supported fields: status, model, error, usage_input_tokens,
        usage_output_tokens, ended_at, applied_at, input_memory_count,
        input_session_ids.
        """
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        allowed = {
            "status",
            "model",
            "error",
            "usage_input_tokens",
            "usage_output_tokens",
            "ended_at",
            "applied_at",
            "input_memory_count",
            "input_session_ids",
        }
        updates: dict = {}
        for key, value in kwargs.items():
            if key not in allowed:
                continue
            if value is None and key in ("ended_at", "applied_at", "error"):
                updates[key] = None
                continue
            if value is None:
                continue
            if key == "status":
                updates[key] = value.value if isinstance(value, DreamStatus) else str(value)
            elif key in ("ended_at", "applied_at"):
                updates[key] = value.isoformat() if isinstance(value, datetime) else str(value)
            elif key == "input_session_ids":
                updates[key] = json.dumps(list(value))
            else:
                updates[key] = value

        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values())
        values.append(run_id)
        await self._db.execute(
            f"UPDATE dream_runs SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self._db.commit()

    async def get_dream_run(self, dream_id: str) -> DreamRun | None:
        """Fetch a single dream run by id."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        cursor = await self._db.execute(
            "SELECT * FROM dream_runs WHERE id = ?",
            (dream_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_dream_run(row)

    async def list_dream_runs(
        self,
        *,
        project: str | None = None,
        status: str | None = None,
        user_id: str = "",
        limit: int = 20,
    ) -> list[DreamRun]:
        """List dream runs (most recent first), optionally filtered by project/status."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")

        safe_limit = max(1, min(int(limit), 500))
        conditions: list[str] = []
        params: list = []
        if project is not None:
            conditions.append("project = ?")
            params.append(project)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(safe_limit)

        cursor = await self._db.execute(
            f"SELECT * FROM dream_runs{where_clause} "  # noqa: S608
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_dream_run(row) for row in rows]

    async def create_dream_patches(self, patches: list[DreamPatch]) -> None:
        """Batch-insert dream patches belonging to a single run."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if not patches:
            return
        rows = [
            (
                p.id,
                p.dream_id,
                p.action.value,
                json.dumps(p.target_memory_ids),
                p.new_content,
                json.dumps(p.new_metadata, default=str) if p.new_metadata is not None else None,
                p.evidence,
                p.status.value,
                p.created_at.isoformat(),
                p.applied_at.isoformat() if p.applied_at else None,
            )
            for p in patches
        ]
        await self._db.executemany(
            """
            INSERT INTO dream_patches
            (id, dream_id, action, target_memory_ids, new_content, new_metadata,
             evidence, status, created_at, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self._db.commit()

    async def get_dream_patches(
        self,
        dream_id: str,
        *,
        status: str | None = None,
    ) -> list[DreamPatch]:
        """Return patches for a dream, optionally filtered by status."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if status is not None:
            cursor = await self._db.execute(
                "SELECT * FROM dream_patches WHERE dream_id = ? AND status = ? ORDER BY created_at",
                (dream_id, status),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM dream_patches WHERE dream_id = ? ORDER BY created_at",
                (dream_id,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_dream_patch(row) for row in rows]

    async def update_dream_patch_status(
        self,
        patch_id: str,
        status: DreamPatchStatus,
        *,
        applied_at: datetime | None = None,
    ) -> None:
        """Mark a single dream patch with a new lifecycle status."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        applied_iso = applied_at.isoformat() if applied_at else None
        await self._db.execute(
            "UPDATE dream_patches SET status = ?, applied_at = ? WHERE id = ?",
            (status.value, applied_iso, patch_id),
        )
        await self._db.commit()

    @staticmethod
    def _row_to_dream_run(row: aiosqlite.Row) -> DreamRun:
        """Convert a database row to a DreamRun model."""
        return DreamRun(
            id=row["id"],
            project=row["project"],
            status=DreamStatus(row["status"]),
            model=row["model"],
            instructions=row["instructions"],
            input_session_ids=(
                json.loads(row["input_session_ids"]) if row["input_session_ids"] else []
            ),
            input_memory_count=row["input_memory_count"],
            error=row["error"],
            usage_input_tokens=row["usage_input_tokens"],
            usage_output_tokens=row["usage_output_tokens"],
            created_at=datetime.fromisoformat(row["created_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            applied_at=(datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None),
            user_id=row["user_id"],
        )

    @staticmethod
    def _row_to_dream_patch(row: aiosqlite.Row) -> DreamPatch:
        """Convert a database row to a DreamPatch model."""
        return DreamPatch(
            id=row["id"],
            dream_id=row["dream_id"],
            action=DreamPatchAction(row["action"]),
            target_memory_ids=(
                json.loads(row["target_memory_ids"]) if row["target_memory_ids"] else []
            ),
            new_content=row["new_content"],
            new_metadata=json.loads(row["new_metadata"]) if row["new_metadata"] else None,
            evidence=row["evidence"],
            status=DreamPatchStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            applied_at=(datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None),
        )
