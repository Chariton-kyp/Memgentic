"""Tests for the ingestion pipeline (IngestionPipeline)."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.exceptions import EmbeddingError
from memgentic.models import (
    ContentType,
    ConversationChunk,
    Memory,
    Platform,
)
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore

DIMS = 768


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


@pytest.fixture()
def pipeline_settings(tmp_path) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=DIMS,
    )


@pytest.fixture()
def mock_embedder():
    """Mock Embedder: embed() returns a single vector, embed_batch() returns a list."""
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_batch.side_effect = lambda texts: [
        _fake_embedding(0.1 * i) for i in range(len(texts))
    ]
    return embedder


@pytest.fixture()
def mock_vector_store():
    """Mock VectorStore with async methods."""
    vs = AsyncMock()
    vs.upsert_memory = AsyncMock()
    vs.upsert_memories_batch = AsyncMock()
    return vs


@pytest.fixture()
async def pipeline(
    pipeline_settings: MemgenticSettings,
    metadata_store: MetadataStore,
    mock_embedder,
    mock_vector_store,
):
    """IngestionPipeline wired with real MetadataStore and mocked embedder/vector store."""
    return IngestionPipeline(
        settings=pipeline_settings,
        metadata_store=metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
    )


class TestIngestConversation:
    async def test_full_flow(
        self,
        pipeline: IngestionPipeline,
        sample_chunks: list[ConversationChunk],
        mock_embedder,
        mock_vector_store,
        metadata_store: MetadataStore,
    ):
        memories = await pipeline.ingest_conversation(
            chunks=sample_chunks,
            platform=Platform.CLAUDE_CODE,
            session_id="sess-001",
            session_title="Test conversation",
        )

        assert len(memories) == 3
        assert all(isinstance(m, Memory) for m in memories)
        assert all(m.source.platform == Platform.CLAUDE_CODE for m in memories)
        mock_embedder.embed_batch.assert_called_once()
        mock_vector_store.upsert_memories_batch.assert_called_once()

        count = await metadata_store.get_total_count()
        assert count == 3

    async def test_empty_chunks_skipped(
        self,
        pipeline: IngestionPipeline,
    ):
        chunks = [
            ConversationChunk(
                content="   ",  # whitespace-only
                content_type=ContentType.FACT,
            ),
        ]
        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )
        assert memories == []


class TestDeduplication:
    async def test_duplicate_file_skipped(
        self,
        pipeline: IngestionPipeline,
        sample_chunks: list[ConversationChunk],
    ):
        # Create a real temp file so the pipeline can hash it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"test": true}\n')
            tmp_file = f.name

        try:
            # First ingestion
            first = await pipeline.ingest_conversation(
                chunks=sample_chunks,
                platform=Platform.CLAUDE_CODE,
                file_path=tmp_file,
            )
            assert len(first) == 3

            # Second ingestion of the same file — should be skipped
            second = await pipeline.ingest_conversation(
                chunks=sample_chunks,
                platform=Platform.CLAUDE_CODE,
                file_path=tmp_file,
            )
            assert second == []
        finally:
            os.unlink(tmp_file)


class TestIngestSingle:
    async def test_ingest_single(
        self,
        pipeline: IngestionPipeline,
        mock_embedder,
        mock_vector_store,
        metadata_store: MetadataStore,
    ):
        memory = await pipeline.ingest_single(
            content="Python 3.12 supports type parameter syntax",
            content_type=ContentType.FACT,
            platform=Platform.CLAUDE_CODE,
            topics=["python"],
        )

        assert memory.content == "Python 3.12 supports type parameter syntax"
        assert memory.source.platform == Platform.CLAUDE_CODE
        assert memory.topics == ["python"]
        mock_embedder.embed.assert_called_once()
        mock_vector_store.upsert_memory.assert_called_once()

        got = await metadata_store.get_memory(memory.id)
        assert got is not None


class TestNoiseFiltering:
    async def test_noise_chunks_filtered(
        self,
        pipeline: IngestionPipeline,
        metadata_store: MetadataStore,
    ):
        chunks = [
            ConversationChunk(
                content="ok",  # noise: too short
                content_type=ContentType.RAW_EXCHANGE,
            ),
            ConversationChunk(
                content="Sure, thanks!",  # noise: pleasantry
                content_type=ContentType.RAW_EXCHANGE,
            ),
            ConversationChunk(
                content="We decided to use PostgreSQL because of JSONB support",
                content_type=ContentType.DECISION,
            ),
        ]
        memories = await pipeline.ingest_conversation(chunks=chunks, platform=Platform.CLAUDE_CODE)
        assert len(memories) == 1
        assert "PostgreSQL" in memories[0].content

    async def test_all_noise_returns_empty(
        self,
        pipeline: IngestionPipeline,
    ):
        chunks = [
            ConversationChunk(content="ok", content_type=ContentType.RAW_EXCHANGE),
            ConversationChunk(content="thanks", content_type=ContentType.RAW_EXCHANGE),
        ]
        memories = await pipeline.ingest_conversation(chunks=chunks, platform=Platform.CLAUDE_CODE)
        assert memories == []


class TestWriteTimeDedup:
    async def test_write_time_dedup_skips_duplicate(
        self,
        pipeline_settings: MemgenticSettings,
        metadata_store: MetadataStore,
        mock_embedder,
        mock_vector_store,
        sample_chunks: list[ConversationChunk],
    ):
        # Enable write-time dedup
        pipeline_settings.enable_write_time_dedup = True
        # First call: empty store, all unique
        mock_vector_store.search.return_value = []
        pipeline = IngestionPipeline(
            settings=pipeline_settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )
        first = await pipeline.ingest_conversation(
            chunks=sample_chunks, platform=Platform.CLAUDE_CODE
        )
        assert len(first) == 3

        # Now simulate a near-duplicate hit for every chunk
        async def fake_search(*_args, **_kwargs):
            return [
                {
                    "id": "existing",
                    "score": 0.95,
                    "payload": {
                        "content": (
                            "We chose Qdrant for vector search due to its local file-based mode."
                        )
                    },
                }
            ]

        mock_vector_store.search.side_effect = fake_search
        second = await pipeline.ingest_conversation(
            chunks=[sample_chunks[0]], platform=Platform.CLAUDE_CODE
        )
        # Duplicate should be skipped
        assert second == []

    async def test_write_time_dedup_keeps_distinct_content(
        self,
        pipeline_settings: MemgenticSettings,
        metadata_store: MetadataStore,
        mock_embedder,
        mock_vector_store,
    ):
        pipeline_settings.enable_write_time_dedup = True

        async def fake_search(*_args, **_kwargs):
            return [
                {
                    "id": "existing",
                    "score": 0.95,
                    "payload": {"content": "completely unrelated existing memory"},
                }
            ]

        mock_vector_store.search.side_effect = fake_search
        pipeline = IngestionPipeline(
            settings=pipeline_settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )
        chunks = [
            ConversationChunk(
                content="We chose Qdrant for vector search due to its local file mode",
                content_type=ContentType.DECISION,
            )
        ]
        result = await pipeline.ingest_conversation(chunks=chunks, platform=Platform.CLAUDE_CODE)
        # High score but low overlap → not a duplicate
        assert len(result) == 1


class TestErrorHandling:
    async def test_embedding_failure_returns_empty(
        self,
        pipeline: IngestionPipeline,
        sample_chunks: list[ConversationChunk],
        mock_embedder,
    ):
        mock_embedder.embed_batch.side_effect = EmbeddingError("Ollama down")

        # Should not raise — returns empty list
        memories = await pipeline.ingest_conversation(
            chunks=sample_chunks,
            platform=Platform.CLAUDE_CODE,
        )
        assert memories == []

    async def test_single_embedding_failure_raises(
        self,
        pipeline: IngestionPipeline,
        mock_embedder,
    ):
        mock_embedder.embed.side_effect = EmbeddingError("Ollama down")

        with pytest.raises(EmbeddingError):
            await pipeline.ingest_single(content="will fail")
