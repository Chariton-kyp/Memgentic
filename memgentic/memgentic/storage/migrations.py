"""SQLite schema migration framework — versioned SQL scripts."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite
import structlog

logger = structlog.get_logger()

# Each migration is a tuple of (version, description, sql_statements)
# Version 1 is the initial schema (already created by metadata.py's CREATE_TABLE_SQL)
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (1, "initial schema", []),  # Already applied by CREATE TABLE IF NOT EXISTS
    (
        2,
        "add importance score",
        [
            "ALTER TABLE memories ADD COLUMN importance_score REAL DEFAULT 1.0",
        ],
    ),
    (
        3,
        "add corroborated_by",
        [
            "ALTER TABLE memories ADD COLUMN corroborated_by TEXT DEFAULT '[]'",
        ],
    ),
    (
        4,
        "add user_id to memories",
        [
            "ALTER TABLE memories ADD COLUMN user_id TEXT NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id)",
        ],
    ),
    (
        5,
        "add collections, uploads, and pin support",
        [
            # Collections
            """CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#6B7280',
                icon TEXT NOT NULL DEFAULT 'folder',
                position REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_collections_user_id ON collections(user_id)",
            # Collection membership
            """CREATE TABLE IF NOT EXISTS collection_memories (
                collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                position REAL NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL,
                PRIMARY KEY (collection_id, memory_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_collection_memories_memory "
            "ON collection_memories(memory_id)",
            # Uploads tracking
            """CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                memory_id TEXT REFERENCES memories(id) ON DELETE SET NULL,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                upload_source TEXT NOT NULL DEFAULT 'manual',
                original_url TEXT,
                status TEXT NOT NULL DEFAULT 'processing',
                error_message TEXT,
                created_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_uploads_memory_id ON uploads(memory_id)",
            # Pin support
            "ALTER TABLE memories ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE memories ADD COLUMN pinned_at TEXT",
            "CREATE INDEX IF NOT EXISTS idx_memories_pinned ON memories(is_pinned, pinned_at)",
        ],
    ),
    (
        6,
        "add skills, skill_files, skill_distributions, and ingestion_jobs",
        [
            # Skills table
            """CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                config TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT 'manual',
                source_url TEXT,
                version TEXT NOT NULL DEFAULT '1.0.0',
                tags TEXT NOT NULL DEFAULT '[]',
                distribute_to TEXT NOT NULL DEFAULT '["claude","codex","cursor"]',
                auto_distribute INTEGER NOT NULL DEFAULT 1,
                source_memory_ids TEXT NOT NULL DEFAULT '[]',
                auto_extracted INTEGER NOT NULL DEFAULT 0,
                extraction_confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_skills_user ON skills(user_id)",
            # Skill files
            """CREATE TABLE IF NOT EXISTS skill_files (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(skill_id, path)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_skill_files_skill ON skill_files(skill_id)",
            # Skill distributions
            """CREATE TABLE IF NOT EXISTS skill_distributions (
                id TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                tool TEXT NOT NULL,
                target_path TEXT NOT NULL,
                distributed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                UNIQUE(skill_id, tool)
            )""",
            # Ingestion jobs
            """CREATE TABLE IF NOT EXISTS ingestion_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL,
                source_path TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                total_items INTEGER NOT NULL DEFAULT 0,
                processed_items INTEGER NOT NULL DEFAULT 0,
                failed_items INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL
            )""",
        ],
    ),
    (
        7,
        "embedding_config — pin model/dimensions to prevent silent mismatch",
        [
            # Key/value store recording the embedding model + dimensions used
            # to build the current vector collection. VectorStore reads this
            # on startup and refuses to proceed if the configured model/dim
            # differs from what's pinned.
            """CREATE TABLE IF NOT EXISTS embedding_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
        ],
    ),
    (
        8,
        "capture_profile — raw / enriched / dual per-memory + runtime settings kv",
        [
            # Per-memory capture profile selector. 'enriched' keeps the historic
            # default (topics/entities/LLM importance). 'raw' stores verbatim
            # chunks with no LLM enrichment. 'dual' writes both rows and links
            # them through dual_sibling_id for dashboard de-duplication.
            "ALTER TABLE memories ADD COLUMN capture_profile TEXT "
            "NOT NULL DEFAULT 'enriched' "
            "CHECK (capture_profile IN ('raw', 'enriched', 'dual'))",
            # Sibling pointer used only by dual-profile pairs. For raw/enriched
            # standalones it remains NULL.
            "ALTER TABLE memories ADD COLUMN dual_sibling_id TEXT",
            "CREATE INDEX IF NOT EXISTS idx_memories_capture_profile ON memories(capture_profile)",
            # Lightweight key/value table for runtime-mutable settings that must
            # persist across restarts (e.g. the default capture profile changed
            # via CLI / REST / MCP). Kept deliberately minimal — not a general
            # config dumping ground.
            """CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
        ],
    ),
    (
        9,
        "project — friendly key for cross-tool project filtering",
        [
            # Friendly project name derived from the originating working
            # directory (Path(cwd).name.lower()), or decoded from a Claude
            # Code parent-directory slug as a fallback. Empty string when
            # unknown. Backfilled in Python below for legacy rows.
            "ALTER TABLE memories ADD COLUMN project TEXT NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project)",
        ],
    ),
    (
        10,
        "dreams — auto-dream consolidation runs and proposed patches",
        [
            # A dream is a single LLM-driven consolidation pass over the live
            # memory store. It produces patch proposals that the user reviews
            # and explicitly applies; the live memories table is untouched
            # until ``apply_dream`` runs.
            """CREATE TABLE IF NOT EXISTS dream_runs (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN
                        ('pending','running','completed','failed','canceled')),
                model TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '',
                input_session_ids TEXT NOT NULL DEFAULT '[]',
                input_memory_count INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                usage_input_tokens INTEGER NOT NULL DEFAULT 0,
                usage_output_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                ended_at TEXT,
                applied_at TEXT,
                user_id TEXT NOT NULL DEFAULT ''
            )""",
            "CREATE INDEX IF NOT EXISTS idx_dream_runs_project ON dream_runs(project)",
            "CREATE INDEX IF NOT EXISTS idx_dream_runs_status ON dream_runs(status)",
            "CREATE INDEX IF NOT EXISTS idx_dream_runs_created_at ON dream_runs(created_at)",
            # Individual patch operations belonging to a dream. ``status`` drives
            # the apply/reject lifecycle. ``target_memory_ids`` and
            # ``new_metadata`` are JSON-encoded.
            """CREATE TABLE IF NOT EXISTS dream_patches (
                id TEXT PRIMARY KEY,
                dream_id TEXT NOT NULL REFERENCES dream_runs(id) ON DELETE CASCADE,
                action TEXT NOT NULL CHECK (action IN
                    ('merge','supersede','archive_stale',
                     'normalize_date','insert_insight','update_field')),
                target_memory_ids TEXT NOT NULL DEFAULT '[]',
                new_content TEXT,
                new_metadata TEXT,
                evidence TEXT,
                status TEXT NOT NULL DEFAULT 'proposed'
                    CHECK (status IN
                        ('proposed','applied','rejected','superseded_by_apply')),
                created_at TEXT NOT NULL,
                applied_at TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_dream_patches_dream_id ON dream_patches(dream_id)",
            "CREATE INDEX IF NOT EXISTS idx_dream_patches_status ON dream_patches(status)",
        ],
    ),
    (
        11,
        "retention — updated_at bookkeeping for GC",
        [
            # Last-modified timestamp, stamped by save_memory / save_memories_batch
            # / update_memory_status. The retention GC sweep uses
            # COALESCE(updated_at, created_at) as the "archived/superseded at"
            # anchor to decide when a soft-deleted row is past its grace period.
            # Legacy rows keep updated_at = NULL and fall back to created_at.
            "ALTER TABLE memories ADD COLUMN updated_at TEXT",
            "CREATE INDEX IF NOT EXISTS idx_memories_status_updated "
            "ON memories(status, updated_at)",
        ],
    ),
]

SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


async def get_current_version(db: aiosqlite.Connection) -> int:
    """Get the current schema version from the database."""
    # Ensure the version table exists
    await db.execute(SCHEMA_VERSION_TABLE)
    await db.commit()
    cursor = await db.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    if row is not None and row[0] is not None:
        return int(row[0])
    return 0


async def migrate(db: aiosqlite.Connection) -> int:
    """Apply any pending migrations. Returns the number of migrations applied."""
    current = await get_current_version(db)
    applied = 0
    latest_version = current

    for version, description, statements in MIGRATIONS:
        if version <= current:
            continue

        logger.info("migration.applying", version=version, description=description)

        for sql in statements:
            await db.execute(sql)

        # Post-DDL backfills that need Python-side derivation. SQLite has no
        # built-in REGEXP and the slug→project mapping is non-trivial.
        if version == 9:
            await _backfill_project_column(db)

        now = datetime.now(UTC).isoformat()
        await db.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, now),
        )
        await db.commit()
        applied += 1
        latest_version = version
        logger.info("migration.applied", version=version)

    if applied:
        logger.info("migration.complete", applied=applied, current_version=latest_version)
    else:
        logger.debug("migration.up_to_date", version=current)

    return applied


async def _backfill_project_column(db: aiosqlite.Connection) -> None:
    """Populate ``memories.project`` for legacy rows from their ``file_path``.

    Imported here to avoid a top-level cycle (``processing.project`` is a
    stand-alone helper but ``processing/__init__`` historically pulls in heavy
    pipeline imports).
    """
    from memgentic.processing.project import derive_project

    cursor = await db.execute(
        "SELECT id, file_path FROM memories WHERE project = '' AND file_path IS NOT NULL"
    )
    # Materialize — aiosqlite annotates fetchall() as Iterable[Row], which
    # isn't Sized, so ``len(rows)`` below needs a concrete list.
    rows = list(await cursor.fetchall())
    if not rows:
        return

    updates: list[tuple[str, str]] = []
    for row in rows:
        memory_id = row[0]
        file_path = row[1]
        project = derive_project(file_path=file_path)
        if project:
            updates.append((project, memory_id))

    if not updates:
        logger.info("migration.project_backfill_empty", scanned=len(rows))
        return

    await db.executemany(
        "UPDATE memories SET project = ? WHERE id = ?",
        updates,
    )
    logger.info(
        "migration.project_backfill_complete",
        scanned=len(rows),
        updated=len(updates),
    )
