"""Tests for Qdrant vector store (VectorStore) — async, local file-based mode."""

from __future__ import annotations

import uuid

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SessionConfig,
    SourceMetadata,
)
from memgentic.storage.vectors import VectorStore

DIMS = 768


def _fake_embedding(seed: float = 0.1) -> list[float]:
    """Return a deterministic 768-d fake embedding."""
    return [seed + i * 0.0001 for i in range(DIMS)]


def _uuid(n: int) -> str:
    """Deterministic UUID from an integer seed."""
    return str(uuid.UUID(int=n))


def _make_memory(
    id: str | None = None,
    content: str = "vector test",
    platform: Platform = Platform.CLAUDE_CODE,
    content_type: ContentType = ContentType.FACT,
    confidence: float = 1.0,
) -> Memory:
    return Memory(
        id=id or str(uuid.uuid4()),
        content=content,
        content_type=content_type,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        confidence=confidence,
    )


@pytest.fixture()
async def vector_store(tmp_path):
    """An initialised VectorStore backed by a temporary Qdrant local directory."""
    settings = MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.LOCAL,
        collection_name="test_collection",
        embedding_dimensions=DIMS,
    )
    store = VectorStore(settings)
    # Disable server auto-detection so tests always use isolated local files
    store._try_server_connection = _no_server  # type: ignore[assignment]
    await store.initialize()
    yield store
    await store.close()


async def _no_server() -> bool:
    """Stub that prevents auto-detection of a running Qdrant server in tests."""
    return False


class TestInitialize:
    async def test_creates_collection(self, vector_store: VectorStore):
        info = await vector_store.get_collection_info()
        assert info["status"] in ("green", "yellow", "grey")
        assert info["points_count"] == 0


class TestUpsertAndSearch:
    async def test_upsert_and_search_roundtrip(self, vector_store: VectorStore):
        uid = _uuid(1)
        mem = _make_memory(id=uid, content="Qdrant is a vector database")
        emb = _fake_embedding(0.5)
        await vector_store.upsert_memory(mem, emb)

        results = await vector_store.search(emb, limit=5)
        assert len(results) >= 1
        assert results[0]["id"] == uid
        assert results[0]["payload"]["content"] == "Qdrant is a vector database"
        assert results[0]["score"] > 0.9  # self-search should be very high

    async def test_upsert_memories_batch(self, vector_store: VectorStore):
        memories = [_make_memory(id=_uuid(10 + i), content=f"Batch memory {i}") for i in range(3)]
        embeddings = [_fake_embedding(0.1 * (i + 1)) for i in range(3)]
        await vector_store.upsert_memories_batch(memories, embeddings)

        info = await vector_store.get_collection_info()
        assert info["points_count"] == 3


class TestSearchFilters:
    async def test_search_with_include_sources(self, vector_store: VectorStore):
        uid1, uid2 = _uuid(20), _uuid(21)
        m1 = _make_memory(id=uid1, platform=Platform.CLAUDE_CODE)
        m2 = _make_memory(id=uid2, platform=Platform.CHATGPT)
        emb1 = _fake_embedding(0.2)
        emb2 = _fake_embedding(0.21)

        await vector_store.upsert_memory(m1, emb1)
        await vector_store.upsert_memory(m2, emb2)

        config = SessionConfig(include_sources=[Platform.CLAUDE_CODE])
        results = await vector_store.search(emb1, session_config=config, limit=10)
        platforms = {r["payload"]["platform"] for r in results}
        assert "chatgpt" not in platforms

    async def test_search_with_exclude_sources(self, vector_store: VectorStore):
        uid1, uid2 = _uuid(30), _uuid(31)
        m1 = _make_memory(id=uid1, platform=Platform.CLAUDE_CODE)
        m2 = _make_memory(id=uid2, platform=Platform.CHATGPT)
        emb1 = _fake_embedding(0.3)
        emb2 = _fake_embedding(0.31)

        await vector_store.upsert_memory(m1, emb1)
        await vector_store.upsert_memory(m2, emb2)

        config = SessionConfig(exclude_sources=[Platform.CHATGPT])
        results = await vector_store.search(emb1, session_config=config, limit=10)
        platforms = {r["payload"]["platform"] for r in results}
        assert "chatgpt" not in platforms

    async def test_search_with_min_confidence(self, vector_store: VectorStore):
        uid1, uid2 = _uuid(40), _uuid(41)
        m1 = _make_memory(id=uid1, confidence=0.3)
        m2 = _make_memory(id=uid2, confidence=0.9)
        emb = _fake_embedding(0.4)

        await vector_store.upsert_memory(m1, emb)
        await vector_store.upsert_memory(m2, _fake_embedding(0.41))

        config = SessionConfig(min_confidence=0.5)
        results = await vector_store.search(emb, session_config=config, limit=10)
        for r in results:
            assert r["payload"]["confidence"] >= 0.5


class TestDeleteAndInfo:
    async def test_delete_memory(self, vector_store: VectorStore):
        uid = _uuid(50)
        mem = _make_memory(id=uid)
        await vector_store.upsert_memory(mem, _fake_embedding(0.6))

        info_before = await vector_store.get_collection_info()
        assert info_before["points_count"] == 1

        await vector_store.delete_memory(uid)

        info_after = await vector_store.get_collection_info()
        assert info_after["points_count"] == 0

    async def test_get_collection_info(self, vector_store: VectorStore):
        info = await vector_store.get_collection_info()
        assert "indexed_vectors_count" in info
        assert "points_count" in info
        assert "status" in info


class TestEmbeddingSafetyCheck:
    """v0.5.0 #4 — refuse to start when the pinned embedding model or dimensions
    disagree with what's configured.
    """

    async def test_first_init_pins_model_and_dim(self, tmp_path):
        from memgentic.storage.metadata import MetadataStore

        settings = MemgenticSettings(
            data_dir=tmp_path / "memgentic_data",
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_fresh",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
        )
        meta = MetadataStore(settings.sqlite_path)
        vec = VectorStore(settings)
        vec._try_server_connection = _no_server  # type: ignore[assignment]
        try:
            await meta.initialize()
            await vec.initialize(meta)
            pinned = await meta.get_embedding_config()
        finally:
            await vec.close()
            await meta.close()

        assert pinned is not None
        assert pinned["model"] == "qwen3-embedding:0.6b"
        assert pinned["dimensions"] == "768"

    async def test_dim_mismatch_raises(self, tmp_path):
        from memgentic.exceptions import EmbeddingMismatchError
        from memgentic.storage.metadata import MetadataStore

        settings_a = MemgenticSettings(
            data_dir=tmp_path / "memgentic_data",
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_dim",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
        )
        meta = MetadataStore(settings_a.sqlite_path)
        vec = VectorStore(settings_a)
        vec._try_server_connection = _no_server  # type: ignore[assignment]
        await meta.initialize()
        await vec.initialize(meta)
        await vec.close()

        settings_b = MemgenticSettings(
            data_dir=settings_a.data_dir,
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_dim",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=384,
        )
        vec2 = VectorStore(settings_b)
        vec2._try_server_connection = _no_server  # type: ignore[assignment]
        try:
            with pytest.raises(EmbeddingMismatchError) as excinfo:
                await vec2.initialize(meta)
            msg = str(excinfo.value)
            assert "re-embed" in msg
            assert "768" in msg
            assert "384" in msg
        finally:
            await vec2.close()
            await meta.close()

    async def test_model_mismatch_raises(self, tmp_path):
        from memgentic.exceptions import EmbeddingMismatchError
        from memgentic.storage.metadata import MetadataStore

        settings_a = MemgenticSettings(
            data_dir=tmp_path / "memgentic_data",
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_model",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
        )
        meta = MetadataStore(settings_a.sqlite_path)
        vec = VectorStore(settings_a)
        vec._try_server_connection = _no_server  # type: ignore[assignment]
        await meta.initialize()
        await vec.initialize(meta)
        await vec.close()

        settings_b = MemgenticSettings(
            data_dir=settings_a.data_dir,
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_model",
            embedding_model="nomic-embed-text",
            embedding_dimensions=768,
        )
        vec2 = VectorStore(settings_b)
        vec2._try_server_connection = _no_server  # type: ignore[assignment]
        try:
            with pytest.raises(EmbeddingMismatchError) as excinfo:
                await vec2.initialize(meta)
            assert "nomic-embed-text" in str(excinfo.value)
            assert "qwen3-embedding:0.6b" in str(excinfo.value)
        finally:
            await vec2.close()
            await meta.close()

    async def test_missing_pin_backfills_from_collection(self, tmp_path):
        from memgentic.storage.metadata import MetadataStore

        settings = MemgenticSettings(
            data_dir=tmp_path / "memgentic_data",
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_backfill",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
        )
        meta = MetadataStore(settings.sqlite_path)
        vec = VectorStore(settings)
        vec._try_server_connection = _no_server  # type: ignore[assignment]
        await meta.initialize()
        await vec.initialize(meta)
        # Simulate pre-v0.5.0 DB: collection exists, pin is missing.
        await meta.clear_embedding_config()
        assert await meta.get_embedding_config() is None
        await vec.close()

        vec2 = VectorStore(settings)
        vec2._try_server_connection = _no_server  # type: ignore[assignment]
        try:
            await vec2.initialize(meta)
            pinned = await meta.get_embedding_config()
        finally:
            await vec2.close()
            await meta.close()

        assert pinned is not None
        assert pinned["model"] == "qwen3-embedding:0.6b"
        assert pinned["dimensions"] == "768"

    async def test_no_metadata_store_keeps_old_behaviour(self, tmp_path):
        """Callers not passing metadata_store keep pre-v0.5.0 behaviour (no
        check, no pin). Important for backwards compatibility during staged
        rollout.
        """
        from memgentic.storage.metadata import MetadataStore

        settings = MemgenticSettings(
            data_dir=tmp_path / "memgentic_data",
            storage_backend=StorageBackend.LOCAL,
            collection_name="safety_nostore",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dimensions=768,
        )
        vec = VectorStore(settings)
        vec._try_server_connection = _no_server  # type: ignore[assignment]
        try:
            await vec.initialize()
        finally:
            await vec.close()

        meta = MetadataStore(settings.sqlite_path)
        await meta.initialize()
        try:
            assert await meta.get_embedding_config() is None
        finally:
            await meta.close()
