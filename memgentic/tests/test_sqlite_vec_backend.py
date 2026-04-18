"""Tests for the opt-in SqliteVecBackend."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.exceptions import StorageError
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SessionConfig,
    SourceMetadata,
)

pytest.importorskip("sqlite_vec", reason="sqlite-vec optional extra not installed")

from memgentic.storage.backends.sqlite_vec import SqliteVecBackend  # noqa: E402
from memgentic.storage.vectors import VectorStore  # noqa: E402

DIMS = 8  # small dim keeps tests fast


def _embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.01 for i in range(DIMS)]


def _make_memory(
    content: str = "vector test",
    platform: Platform = Platform.CLAUDE_CODE,
    content_type: ContentType = ContentType.FACT,
    confidence: float = 1.0,
    mid: str | None = None,
) -> Memory:
    return Memory(
        id=mid or str(uuid.uuid4()),
        content=content,
        content_type=content_type,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        confidence=confidence,
    )


def _settings(tmp_path, dims: int = DIMS) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.SQLITE_VEC,
        embedding_dimensions=dims,
    )


@pytest.fixture()
async def backend(tmp_path):
    """Directly instantiated SqliteVecBackend (no façade)."""
    b = SqliteVecBackend(_settings(tmp_path))
    # Make sure sqlite-vec is actually loadable in this environment; if not,
    # skip rather than error — keeps CI green on exotic platforms.
    try:
        await b.initialize()
    except StorageError as e:
        pytest.skip(f"sqlite-vec extension could not load: {e}")
    yield b
    await b.close()


class TestSmoke:
    async def test_sqlite_vec_importable(self):
        import sqlite_vec  # noqa: F401

    async def test_initialize_creates_schema(self, backend: SqliteVecBackend):
        info = await backend.get_collection_info()
        assert info["points_count"] == 0
        assert info["status"] == "green"


class TestRoundTrip:
    async def test_upsert_and_search_returns_same_id(self, backend: SqliteVecBackend):
        mem = _make_memory(content="hello world")
        await backend.upsert_memory(mem, _embedding(0.5))

        results = await backend.search(_embedding(0.5), limit=5)
        assert len(results) == 1
        assert results[0]["id"] == mem.id
        # Cosine similarity of identical vectors should be ~1.0
        assert results[0]["score"] > 0.99
        assert results[0]["payload"]["content"] == "hello world"

    async def test_batch_upsert(self, backend: SqliteVecBackend):
        mems = [_make_memory(content=f"doc {i}") for i in range(5)]
        embs = [_embedding(0.1 * (i + 1)) for i in range(5)]
        await backend.upsert_memories_batch(mems, embs)

        info = await backend.get_collection_info()
        assert info["points_count"] == 5

        results = await backend.search(_embedding(0.3), limit=10)
        assert len(results) == 5
        ids = {r["id"] for r in results}
        assert ids == {m.id for m in mems}


class TestFilters:
    async def test_filter_by_platform(self, backend: SqliteVecBackend):
        a = _make_memory(content="cc", platform=Platform.CLAUDE_CODE)
        b = _make_memory(content="gc", platform=Platform.GEMINI_CLI)
        await backend.upsert_memories_batch([a, b], [_embedding(0.2), _embedding(0.2)])

        cfg = SessionConfig(include_sources=[Platform.CLAUDE_CODE])
        results = await backend.search(_embedding(0.2), session_config=cfg, limit=10)
        assert len(results) == 1
        assert results[0]["id"] == a.id

        cfg_ex = SessionConfig(exclude_sources=[Platform.CLAUDE_CODE])
        results = await backend.search(_embedding(0.2), session_config=cfg_ex, limit=10)
        assert len(results) == 1
        assert results[0]["id"] == b.id

    async def test_filter_by_content_type(self, backend: SqliteVecBackend):
        a = _make_memory(content="a", content_type=ContentType.FACT)
        b = _make_memory(content="b", content_type=ContentType.PREFERENCE)
        await backend.upsert_memories_batch([a, b], [_embedding(0.2), _embedding(0.2)])

        cfg = SessionConfig(include_content_types=[ContentType.PREFERENCE])
        results = await backend.search(_embedding(0.2), session_config=cfg, limit=10)
        assert len(results) == 1
        assert results[0]["id"] == b.id

    async def test_min_confidence_filter(self, backend: SqliteVecBackend):
        lo = _make_memory(content="lo", confidence=0.3)
        hi = _make_memory(content="hi", confidence=0.9)
        await backend.upsert_memories_batch([lo, hi], [_embedding(0.2), _embedding(0.2)])

        cfg = SessionConfig(min_confidence=0.5)
        results = await backend.search(_embedding(0.2), session_config=cfg, limit=10)
        assert len(results) == 1
        assert results[0]["id"] == hi.id


class TestDelete:
    async def test_delete(self, backend: SqliteVecBackend):
        mem = _make_memory(content="to delete")
        await backend.upsert_memory(mem, _embedding(0.2))

        await backend.delete_memory(mem.id)

        results = await backend.search(_embedding(0.2), limit=10)
        assert len(results) == 0
        info = await backend.get_collection_info()
        assert info["points_count"] == 0


class TestEmbeddingPin:
    async def test_safety_pin_rejects_dim_change(self, tmp_path):
        # First init at DIMS=8
        s1 = _settings(tmp_path, dims=DIMS)
        b1 = SqliteVecBackend(s1)
        try:
            await b1.initialize()
        except StorageError as e:
            pytest.skip(f"sqlite-vec extension could not load: {e}")
        await b1.close()

        # Same path, different dim — should raise
        s2 = _settings(tmp_path, dims=DIMS + 1)
        # Point s2 at the same data_dir so sqlite_path matches
        s2 = MemgenticSettings(
            data_dir=s1.data_dir,
            storage_backend=StorageBackend.SQLITE_VEC,
            embedding_dimensions=DIMS + 1,
        )
        b2 = SqliteVecBackend(s2)
        with pytest.raises(StorageError):
            await b2.initialize()
        await b2.close()

    async def test_safety_pin_accepts_same_config(self, tmp_path):
        s = _settings(tmp_path)
        b1 = SqliteVecBackend(s)
        try:
            await b1.initialize()
        except StorageError as e:
            pytest.skip(f"sqlite-vec extension could not load: {e}")
        await b1.close()

        b2 = SqliteVecBackend(s)
        await b2.initialize()  # should not raise
        await b2.close()


class TestMultiWriter:
    async def test_two_connections_can_write_without_locking(self, tmp_path):
        s = _settings(tmp_path)
        b1 = SqliteVecBackend(s)
        b2 = SqliteVecBackend(s)
        try:
            await b1.initialize()
        except StorageError as e:
            pytest.skip(f"sqlite-vec extension could not load: {e}")
        await b2.initialize()

        # Interleave writes from both connections. WAL mode + busy_timeout
        # means neither should raise "database is locked".
        async def writer(b: SqliteVecBackend, tag: str) -> None:
            for i in range(5):
                mem = _make_memory(content=f"{tag}-{i}")
                await b.upsert_memory(mem, _embedding(0.1 + i * 0.01))

        await asyncio.gather(writer(b1, "a"), writer(b2, "b"))

        info = await b1.get_collection_info()
        assert info["points_count"] == 10

        await b1.close()
        await b2.close()


class TestFacadeIntegration:
    async def test_facade_routes_to_sqlite_vec_backend(self, tmp_path):
        s = _settings(tmp_path)
        store = VectorStore(s)
        try:
            await store.initialize()
        except StorageError as e:
            pytest.skip(f"sqlite-vec extension could not load: {e}")

        mem = _make_memory(content="via facade")
        await store.upsert_memory(mem, _embedding(0.4))
        results = await store.search(_embedding(0.4), limit=5)
        assert len(results) == 1
        assert results[0]["id"] == mem.id

        await store.close()
