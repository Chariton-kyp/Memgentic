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

    async def save_memory(self, memory: Memory) -> None:
        """Insert or update a memory record."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
        await self._db.execute(
            """
            INSERT OR REPLACE INTO memories
            (id, content, content_type, platform, platform_version, session_id,
             session_title, capture_method, original_timestamp, file_path,
             topics, entities, confidence, supersedes, status, created_at,
             last_accessed, access_count, importance_score, corroborated_by,
             user_id, is_pinned, pinned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        await self._db.commit()

    async def save_memories_batch(self, memories: list[Memory]) -> None:
        """Insert multiple memories in a single transaction."""
        if not self._db:
            raise StorageError("MetadataStore not initialized — call initialize() first")
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
             user_id, is_pinned, pinned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        """Update a memory's lifecycle status (active, archived, superseded)."""
        if not self._db:
            raise StorageError("MetadataStore not initialized")
        if user_id:
            await self._db.execute(
                "UPDATE memories SET status = ? WHERE id = ? AND user_id = ?",
                (status, memory_id, user_id),
            )
        else:
            await self._db.execute(
                "UPDATE memories SET status = ? WHERE id = ?",
                (status, memory_id),
            )
        await self._db.commit()

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

        if config.min_confidence > 0:
            conditions.append("confidence >= ?")
            params.append(config.min_confidence)

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

        return Memory(
            id=row["id"],
            user_id=user_id or "",
            content=row["content"],
            content_type=ContentType(row["content_type"]),
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
