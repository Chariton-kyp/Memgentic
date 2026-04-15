"""Edge-case tests for Memgentic core modules.

Covers boundary conditions, malformed input, empty data, and large payloads
across hybrid search, knowledge graph, ingestion pipeline, adapters, and
the metadata store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.graph.knowledge import create_knowledge_graph
from memgentic.graph.search import hybrid_search
from memgentic.models import (
    CaptureMethod,
    ContentType,
    ConversationChunk,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore

DIMS = 768


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


def _make_memory(mid: str, content: str = "test content") -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.MCP_TOOL,
            original_timestamp=datetime(2026, 3, 25, 10, 0, 0, tzinfo=UTC),
        ),
        topics=["python"],
        entities=["Memgentic"],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_batch.side_effect = lambda texts: [
        _fake_embedding(0.1 * i) for i in range(len(texts))
    ]
    return embedder


@pytest.fixture()
def mock_vector_store():
    store = AsyncMock()
    store.search.return_value = []
    store.upsert_memory = AsyncMock()
    store.upsert_memories_batch = AsyncMock()
    return store


@pytest.fixture()
def mock_metadata_store():
    store = AsyncMock()
    store.search_fulltext.return_value = []
    store.get_memory.return_value = None
    return store


@pytest.fixture()
async def knowledge_graph(tmp_path: Path):
    graph = create_knowledge_graph(tmp_path / "edge_graph.json")
    await graph.load()
    return graph


@pytest.fixture()
def pipeline_settings(tmp_path: Path) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=DIMS,
    )


@pytest.fixture()
async def real_metadata_store(tmp_path: Path):
    db_path = tmp_path / "edge_test.db"
    store = MetadataStore(db_path)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture()
async def pipeline(
    pipeline_settings: MemgenticSettings,
    real_metadata_store: MetadataStore,
    mock_embedder,
    mock_vector_store,
):
    return IngestionPipeline(
        settings=pipeline_settings,
        metadata_store=real_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
    )


# ---------------------------------------------------------------------------
# Hybrid search edge cases
# ---------------------------------------------------------------------------


class TestHybridSearchEdgeCases:
    """Edge cases for the hybrid_search function."""

    async def test_empty_query_string(self, mock_embedder, mock_vector_store, mock_metadata_store):
        """Empty query should still call embedder and return results if any."""
        mock_vector_store.search.return_value = [
            {"id": "mem-1", "score": 0.5, "payload": {"content": "something"}},
        ]

        results = await hybrid_search(
            query="",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )

        mock_embedder.embed.assert_awaited_once_with("")
        assert len(results) == 1

    async def test_very_long_query(self, mock_embedder, mock_vector_store, mock_metadata_store):
        """A 1000+ character query should not crash."""
        long_query = "semantic search " * 100  # ~1600 chars

        results = await hybrid_search(
            query=long_query,
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )

        mock_embedder.embed.assert_awaited_once_with(long_query)
        assert results == []

    async def test_unicode_query(self, mock_embedder, mock_vector_store, mock_metadata_store):
        """Unicode characters in query should not crash."""
        unicode_query = "Привет мир 你好世界 こんにちは"

        results = await hybrid_search(
            query=unicode_query,
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )

        mock_embedder.embed.assert_awaited_once_with(unicode_query)
        assert results == []

    async def test_emoji_query(self, mock_embedder, mock_vector_store, mock_metadata_store):
        """Emoji in query should not crash."""
        emoji_query = "Python is great 🐍🔥💻"

        results = await hybrid_search(
            query=emoji_query,
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )

        mock_embedder.embed.assert_awaited_once_with(emoji_query)
        assert results == []

    async def test_sql_injection_query(self, mock_embedder, mock_vector_store, mock_metadata_store):
        """SQL injection attempts in query should not crash."""
        injection_query = "'; DROP TABLE memories; --"

        results = await hybrid_search(
            query=injection_query,
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )

        mock_embedder.embed.assert_awaited_once_with(injection_query)
        assert isinstance(results, list)

    async def test_special_characters_query(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """Special characters (regex, shell, etc.) should not crash."""
        special_query = r"test.*[a-z]+\d{3} $(command) `backtick` <tag>"

        results = await hybrid_search(
            query=special_query,
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )

        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Knowledge graph edge cases
# ---------------------------------------------------------------------------


class TestKnowledgeGraphEdgeCases:
    """Edge cases for the KnowledgeGraph."""

    async def test_empty_graph_query_neighbors(self, tmp_path: Path):
        """Querying neighbors on an empty graph should return not_found."""
        g = create_knowledge_graph(tmp_path / "empty.json")
        result = await g.query_neighbors("anything")
        assert result["not_found"] is True
        assert result["neighbors"] == []

    async def test_empty_graph_get_graph_data(self, tmp_path: Path):
        """Getting graph data from empty graph should return empty lists."""
        g = create_knowledge_graph(tmp_path / "empty.json")
        data = await g.get_graph_data()
        assert data["nodes"] == []
        assert data["edges"] == []

    async def test_empty_graph_node_edge_counts(self, tmp_path: Path):
        """Empty graph should have zero nodes and edges."""
        g = create_knowledge_graph(tmp_path / "empty.json")
        assert g.node_count == 0
        assert g.edge_count == 0

    async def test_add_memory_empty_topics_and_entities(self, tmp_path: Path):
        """Adding a memory with no topics and no entities should be a no-op."""
        g = create_knowledge_graph(tmp_path / "empty.json")
        await g.add_memory("m1", topics=[], entities=[])
        assert g.node_count == 0
        assert g.edge_count == 0

    async def test_add_memory_single_topic_no_edges(self, tmp_path: Path):
        """A single topic creates a node but no edges (no co-occurrence pairs)."""
        g = create_knowledge_graph(tmp_path / "single.json")
        await g.add_memory("m1", topics=["python"], entities=[])
        assert g.node_count == 1
        assert g.edge_count == 0

    async def test_get_node_memory_ids_nonexistent(self, tmp_path: Path):
        """Getting memory IDs for a nonexistent node should return empty list."""
        g = create_knowledge_graph(tmp_path / "empty.json")
        assert g.get_node_memory_ids("nonexistent") == []

    async def test_add_memory_unicode_topics(self, tmp_path: Path):
        """Unicode topic names should work correctly."""
        g = create_knowledge_graph(tmp_path / "unicode.json")
        await g.add_memory("m1", topics=["机器学习", "人工智能"], entities=["Мнеме"])
        assert g.node_count == 3
        assert g.edge_count == 3

    async def test_save_load_empty_graph(self, tmp_path: Path):
        """Saving and loading an empty graph should not crash."""
        path = tmp_path / "empty_roundtrip.json"
        g1 = create_knowledge_graph(path)
        await g1.save()

        g2 = create_knowledge_graph(path)
        await g2.load()
        assert g2.node_count == 0
        assert g2.edge_count == 0


# ---------------------------------------------------------------------------
# Pipeline edge cases
# ---------------------------------------------------------------------------


class TestPipelineEdgeCases:
    """Edge cases for the IngestionPipeline."""

    async def test_empty_chunks_list(self, pipeline: IngestionPipeline):
        """Ingesting an empty chunks list should return empty."""
        memories = await pipeline.ingest_conversation(
            chunks=[],
            platform=Platform.CLAUDE_CODE,
        )
        assert memories == []

    async def test_all_whitespace_chunks(self, pipeline: IngestionPipeline):
        """Chunks with only whitespace should be filtered out."""
        chunks = [
            ConversationChunk(content="   \n\t  ", content_type=ContentType.FACT),
            ConversationChunk(content="", content_type=ContentType.FACT),
            ConversationChunk(content="\n", content_type=ContentType.FACT),
        ]
        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )
        assert memories == []

    async def test_very_large_content(self, pipeline: IngestionPipeline, mock_embedder):
        """A chunk with 10KB+ content should be processed without error."""
        large_content = "This is a test sentence. " * 500  # ~12.5KB
        chunks = [
            ConversationChunk(
                content=large_content,
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]
        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )
        assert len(memories) == 1
        assert len(memories[0].content) > 10_000
        mock_embedder.embed_batch.assert_called_once()

    async def test_ingest_nonexistent_file_path(self, pipeline: IngestionPipeline):
        """A file_path that doesn't exist should still allow ingestion (hash fallback)."""
        chunks = [
            ConversationChunk(
                content="Test memory content",
                content_type=ContentType.FACT,
            ),
        ]
        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            file_path="/nonexistent/path/conversation.jsonl",
        )
        assert len(memories) == 1


# ---------------------------------------------------------------------------
# Adapter edge cases
# ---------------------------------------------------------------------------


class TestAdapterEdgeCases:
    """Edge cases for adapter file discovery."""

    def test_discover_files_nonexistent_directory(self):
        """Discover files with non-existent watch paths should return empty, not crash."""
        from memgentic.adapters.base import BaseAdapter

        class FakeAdapter(BaseAdapter):
            @property
            def platform(self) -> Platform:
                return Platform.UNKNOWN

            @property
            def watch_paths(self) -> list[Path]:
                return [Path("/nonexistent/path/that/does/not/exist")]

            @property
            def file_patterns(self) -> list[str]:
                return ["*.jsonl"]

            async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
                return []

            async def get_session_id(self, file_path: Path) -> str | None:
                return None

            async def get_session_title(self, file_path: Path) -> str | None:
                return None

        adapter = FakeAdapter()
        files = adapter.discover_files()
        assert files == []

    def test_discover_files_empty_directory(self, tmp_path: Path):
        """Discover files in an empty directory should return empty list."""
        from memgentic.adapters.base import BaseAdapter

        class FakeAdapter(BaseAdapter):
            @property
            def platform(self) -> Platform:
                return Platform.UNKNOWN

            @property
            def watch_paths(self) -> list[Path]:
                return [tmp_path]

            @property
            def file_patterns(self) -> list[str]:
                return ["*.jsonl"]

            async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
                return []

            async def get_session_id(self, file_path: Path) -> str | None:
                return None

            async def get_session_title(self, file_path: Path) -> str | None:
                return None

        adapter = FakeAdapter()
        files = adapter.discover_files()
        assert files == []


# ---------------------------------------------------------------------------
# Metadata store edge cases
# ---------------------------------------------------------------------------


class TestMetadataStoreEdgeCases:
    """Edge cases for MetadataStore operations."""

    async def test_get_nonexistent_memory(self, real_metadata_store: MetadataStore):
        """Getting a memory that doesn't exist should return None."""
        result = await real_metadata_store.get_memory("nonexistent-id-12345")
        assert result is None

    async def test_fulltext_search_empty_query(self, real_metadata_store: MetadataStore):
        """Full-text search with empty query should return empty or not crash."""
        results = await real_metadata_store.search_fulltext("", limit=10)
        assert isinstance(results, list)

    async def test_fulltext_search_sql_injection(self, real_metadata_store: MetadataStore):
        """SQL injection in fulltext search should not crash."""
        results = await real_metadata_store.search_fulltext("'; DROP TABLE memories; --", limit=10)
        assert isinstance(results, list)

    async def test_fulltext_search_special_fts5_chars(self, real_metadata_store: MetadataStore):
        """FTS5 special characters should not crash the search."""
        # FTS5 uses * for prefix, " for phrases, etc.
        for query in ['"unclosed', "prefix*", "col:value", "NOT OR AND", "NEAR(a b)"]:
            results = await real_metadata_store.search_fulltext(query, limit=10)
            assert isinstance(results, list)

    async def test_save_and_get_memory_roundtrip(self, real_metadata_store: MetadataStore):
        """Save a memory and retrieve it by ID."""
        mem = _make_memory("edge-test-1", "Edge case test content")
        await real_metadata_store.save_memory(mem)
        got = await real_metadata_store.get_memory("edge-test-1")
        assert got is not None
        assert got.id == "edge-test-1"
        assert got.content == "Edge case test content"

    async def test_get_source_stats_empty_db(self, real_metadata_store: MetadataStore):
        """Source stats on empty database should return empty dict."""
        stats = await real_metadata_store.get_source_stats()
        assert stats == {}

    async def test_get_total_count_empty_db(self, real_metadata_store: MetadataStore):
        """Total count on empty database should return 0."""
        count = await real_metadata_store.get_total_count()
        assert count == 0
