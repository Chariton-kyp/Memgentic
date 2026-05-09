"""End-to-end coverage for the project filter — model → store → SessionConfig.

Smaller-than-integration: spins up a real ``MetadataStore`` against a temp
SQLite file, writes a handful of memories under different project keys, and
exercises the include/exclude filter paths through ``SessionConfig`` plus
the project stats helper.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SessionConfig,
    SourceMetadata,
)
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.migrations import _backfill_project_column, migrate


def _make_memory(
    *,
    content: str,
    project: str,
    platform: Platform = Platform.CLAUDE_CODE,
    file_path: str | None = None,
) -> Memory:
    return Memory(
        content=content,
        content_type=ContentType.RAW_EXCHANGE,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
            file_path=file_path,
        ),
        project=project,
    )


@pytest.fixture
async def store(tmp_path: Path):
    db_path = tmp_path / "memgentic.db"
    s = MetadataStore(db_path)
    await s.initialize()
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_save_and_load_preserves_project(store: MetadataStore) -> None:
    memory = _make_memory(content="hello world from memgentic", project="memgentic")
    await store.save_memory(memory)

    loaded = await store.get_memory(memory.id)
    assert loaded is not None
    assert loaded.project == "memgentic"


@pytest.mark.asyncio
async def test_include_projects_filter(store: MetadataStore) -> None:
    await store.save_memories_batch(
        [
            _make_memory(content="memgentic note one", project="memgentic"),
            _make_memory(content="memgentic note two", project="memgentic"),
            _make_memory(content="vetervo note", project="vetervo"),
            _make_memory(content="inproma note", project="inproma"),
        ]
    )

    config = SessionConfig(include_projects=["memgentic", "vetervo"])
    rows = await store.get_memories_by_filter(session_config=config, limit=20)
    projects = sorted(m.project for m in rows)
    assert projects == ["memgentic", "memgentic", "vetervo"]


@pytest.mark.asyncio
async def test_exclude_projects_filter(store: MetadataStore) -> None:
    await store.save_memories_batch(
        [
            _make_memory(content="memgentic note", project="memgentic"),
            _make_memory(content="vetervo note", project="vetervo"),
            _make_memory(content="inproma note", project="inproma"),
        ]
    )

    config = SessionConfig(exclude_projects=["vetervo"])
    rows = await store.get_memories_by_filter(session_config=config, limit=20)
    assert {m.project for m in rows} == {"memgentic", "inproma"}


@pytest.mark.asyncio
async def test_project_stats(store: MetadataStore) -> None:
    await store.save_memories_batch(
        [
            _make_memory(content="m1", project="memgentic"),
            _make_memory(content="m2", project="memgentic"),
            _make_memory(content="v1", project="vetervo"),
        ]
    )
    stats = await store.get_project_stats()
    assert stats == {"memgentic": 2, "vetervo": 1}


@pytest.mark.asyncio
async def test_migration_backfills_project_from_file_path(tmp_path: Path) -> None:
    """A pre-9 database with file_path-only rows gets project values backfilled.

    Simulates the upgrade path: build a v8 schema by hand, insert legacy rows,
    then run ``migrate`` and confirm the new ``project`` column is populated
    from the existing Claude-Code-style slug embedded in ``file_path``.
    """
    db_path = tmp_path / "legacy.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_type TEXT NOT NULL,
                platform TEXT NOT NULL,
                platform_version TEXT,
                session_id TEXT,
                session_title TEXT,
                capture_method TEXT NOT NULL,
                original_timestamp TEXT,
                file_path TEXT,
                topics TEXT NOT NULL DEFAULT '[]',
                entities TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 1.0,
                supersedes TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_accessed TEXT,
                access_count INTEGER NOT NULL DEFAULT 0,
                importance_score REAL NOT NULL DEFAULT 1.0,
                corroborated_by TEXT NOT NULL DEFAULT '[]',
                user_id TEXT NOT NULL DEFAULT '',
                is_pinned INTEGER NOT NULL DEFAULT 0,
                pinned_at TEXT,
                capture_profile TEXT NOT NULL DEFAULT 'enriched',
                dual_sibling_id TEXT
            )"""
        )
        await conn.execute(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
            "description TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        # Pretend we're at v8 already so only migration 9 runs.
        await conn.executemany(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
            [(v, f"v{v}", "2026-01-01T00:00:00+00:00") for v in range(1, 9)],
        )

        slug = "C--Users-harit-Desktop-Business-Projects-memgentic-public-export"
        legacy_rows = [
            (
                "id-1",
                "legacy memgentic content",
                "raw_exchange",
                "claude_code",
                "auto_daemon",
                f"C:/Users/harit/.claude/projects/{slug}/abc.jsonl",
                "2026-01-01T00:00:00+00:00",
            ),
            (
                "id-2",
                "legacy memory without a path",
                "raw_exchange",
                "manual",
                "mcp_tool",
                None,
                "2026-01-01T00:00:00+00:00",
            ),
        ]
        await conn.executemany(
            """INSERT INTO memories
               (id, content, content_type, platform, capture_method, file_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            legacy_rows,
        )
        await conn.commit()

        applied = await migrate(conn)
        assert applied >= 1  # migration 9 ran

        cursor = await conn.execute("SELECT id, project FROM memories ORDER BY id")
        rows = await cursor.fetchall()

    project_by_id = dict(rows)
    assert project_by_id["id-1"] == "memgentic-public-export"
    # The row without a file_path stays empty — backfill cannot infer it.
    assert project_by_id["id-2"] == ""


@pytest.mark.asyncio
async def test_backfill_helper_idempotent(tmp_path: Path) -> None:
    """Running the backfill twice on the same db is a no-op."""
    db_path = tmp_path / "twice.db"
    s = MetadataStore(db_path)
    await s.initialize()
    try:
        slug = "C--Users-harit-Desktop-Business-Projects-Vetervo"
        legacy = _make_memory(
            content="legacy",
            project="",  # simulate a row that escaped backfill
            file_path=f"C:/Users/harit/.claude/projects/{slug}/abc.jsonl",
        )
        await s.save_memory(legacy)
        # Force the column to empty even though save_memory normally writes it.
        async with s._db.execute("UPDATE memories SET project = '' WHERE id = ?", (legacy.id,)):
            pass
        await s._db.commit()

        await _backfill_project_column(s._db)
        loaded = await s.get_memory(legacy.id)
        assert loaded is not None
        assert loaded.project == "vetervo"

        # Second run — the WHERE project='' guard should leave the row alone.
        await _backfill_project_column(s._db)
        loaded2 = await s.get_memory(legacy.id)
        assert loaded2 is not None
        assert loaded2.project == "vetervo"
    finally:
        await s.close()
