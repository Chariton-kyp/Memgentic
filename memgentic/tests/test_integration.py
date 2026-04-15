"""Integration / end-to-end tests that exercise the full Memgentic pipeline.

These tests combine real MetadataStore (in-memory SQLite) with mock
VectorStore / Embedder to verify that the entire flow works correctly
from ingestion through search and retrieval.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.graph.knowledge import create_knowledge_graph
from memgentic.graph.search import hybrid_search
from memgentic.models import (
    CaptureMethod,
    ContentType,
    ConversationChunk,
    Memory,
    MemoryStatus,
    Platform,
    SessionConfig,
    SourceMetadata,
)
from memgentic.processing.intelligence import (
    ClassificationResult,
    ExtractionResult,
    SummaryResult,
)
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore

DIMS = 768


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


def _make_mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_batch.side_effect = lambda texts: [
        _fake_embedding(0.1 * i) for i in range(len(texts))
    ]
    return embedder


def _make_mock_vector_store():
    vs = AsyncMock()
    vs.upsert_memory = AsyncMock()
    vs.upsert_memories_batch = AsyncMock()
    vs.search = AsyncMock(return_value=[])
    vs.delete_memory = AsyncMock()
    vs.get_collection_info = AsyncMock(return_value={"indexed_vectors_count": 0, "status": "green"})
    return vs


def _make_mock_llm(available: bool = True):
    llm = MagicMock()
    llm.available = available
    llm.generate = AsyncMock(return_value="")
    llm.generate_structured = AsyncMock(return_value=None)
    return llm


@pytest.fixture()
def settings(tmp_path: Path) -> MemgenticSettings:
    # Pre-existing integration tests use fixed-sequence LLM mocks and assume
    # the pre-Phase-1 pipeline shape. Opt out of fact distillation and
    # write-time dedup here; those features have their own dedicated tests.
    return MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=DIMS,
        enable_corroboration=False,
        enable_fact_distillation=False,
        enable_write_time_dedup=False,
    )


@pytest.fixture()
async def meta_store(tmp_path: Path) -> MetadataStore:
    db_path = tmp_path / "integration_test.db"
    store = MetadataStore(db_path)
    await store.initialize()
    yield store
    await store.close()


# =====================================================================
# 1. Create memory -> search -> find it
# =====================================================================


class TestCreateAndSearchMemory:
    """Full round-trip: ingest a memory and retrieve it via search."""

    async def test_ingest_single_and_find_via_metadata(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Ingest a single memory and retrieve it from the metadata store."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        memory = await pipeline.ingest_single(
            content="Python 3.12 supports type parameter syntax for generics.",
            content_type=ContentType.FACT,
            platform=Platform.CLAUDE_CODE,
            topics=["python", "generics"],
            entities=["Python"],
        )

        # Verify it was stored
        retrieved = await meta_store.get_memory(memory.id)
        assert retrieved is not None
        assert retrieved.content == memory.content
        assert retrieved.source.platform == Platform.CLAUDE_CODE
        assert "python" in retrieved.topics
        assert "Python" in retrieved.entities

        # Verify embedding was generated and stored in vector store
        embedder.embed.assert_called_once()
        vs.upsert_memory.assert_called_once()

    async def test_ingest_and_find_via_fulltext_search(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Ingest a memory and find it with fulltext (FTS5) search."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        await pipeline.ingest_single(
            content="Qdrant supports both local file-based and server modes for vector storage.",
            content_type=ContentType.LEARNING,
            platform=Platform.CHATGPT,
            topics=["qdrant", "vectors"],
        )

        # Search via fulltext (FTS5 uses phrase match, so search for a single term)
        results = await meta_store.search_fulltext("Qdrant", limit=10)
        assert len(results) >= 1
        assert "qdrant" in results[0].content.lower()
        assert results[0].source.platform == Platform.CHATGPT

    async def test_ingest_and_find_via_hybrid_search(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Ingest memories and retrieve via hybrid search (semantic + keyword)."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        mem = await pipeline.ingest_single(
            content="FastAPI is built on Starlette and Pydantic for async web APIs.",
            content_type=ContentType.FACT,
            platform=Platform.CLAUDE_CODE,
            topics=["fastapi", "python"],
            entities=["FastAPI", "Starlette"],
        )

        # Configure vector store to return this memory in semantic search
        vs.search.return_value = [
            {"id": mem.id, "score": 0.92, "payload": {"content": mem.content}},
        ]

        results = await hybrid_search(
            query="FastAPI web framework",
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            settings=settings,
            limit=10,
        )

        assert len(results) >= 1
        found_ids = [r["id"] for r in results]
        assert mem.id in found_ids


# =====================================================================
# 2. Import conversation chunks -> verify metadata
# =====================================================================


class TestConversationImport:
    """Ingest conversation chunks and verify stored memories have correct metadata."""

    async def test_chunks_stored_with_correct_source_metadata(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Each chunk is stored as a memory with the correct source provenance."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        chunks = [
            ConversationChunk(
                content="We chose SQLite for metadata storage.",
                content_type=ContentType.DECISION,
                topics=["sqlite", "architecture"],
                entities=["SQLite"],
                confidence=0.9,
            ),
            ConversationChunk(
                content="The embedding model is Qwen3-Embedding with 768d vectors.",
                content_type=ContentType.FACT,
                topics=["embeddings"],
                entities=["Qwen3", "Ollama"],
                confidence=0.95,
            ),
            ConversationChunk(
                content="User prefers fully automated pipelines.",
                content_type=ContentType.PREFERENCE,
                topics=["workflow"],
                confidence=1.0,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.GEMINI_CLI,
            session_id="session-42",
            session_title="Architecture deep dive",
            capture_method=CaptureMethod.AUTO_DAEMON,
            platform_version="gemini-2.0-flash",
        )

        assert len(memories) == 3

        # Verify source metadata on all memories
        for mem in memories:
            assert mem.source.platform == Platform.GEMINI_CLI
            assert mem.source.session_id == "session-42"
            assert mem.source.session_title == "Architecture deep dive"
            assert mem.source.capture_method == CaptureMethod.AUTO_DAEMON
            assert mem.source.platform_version == "gemini-2.0-flash"

        # Verify content types preserved
        assert memories[0].content_type == ContentType.DECISION
        assert memories[1].content_type == ContentType.FACT
        assert memories[2].content_type == ContentType.PREFERENCE

        # Verify topics and entities
        assert "sqlite" in memories[0].topics
        assert "SQLite" in memories[0].entities
        assert "Qwen3" in memories[1].entities

        # Verify all stored in metadata store
        for mem in memories:
            stored = await meta_store.get_memory(mem.id)
            assert stored is not None
            assert stored.content == mem.content

    async def test_empty_chunks_skipped(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Empty or whitespace-only chunks are not stored."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        chunks = [
            ConversationChunk(
                content="Real content here.",
                content_type=ContentType.FACT,
            ),
            ConversationChunk(
                content="   ",  # Whitespace only
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        assert len(memories) == 1
        assert memories[0].content == "Real content here."

    async def test_multiple_conversations_different_platforms(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Memories from different platforms are stored independently."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        # Ingest from Claude Code
        await pipeline.ingest_conversation(
            chunks=[
                ConversationChunk(
                    content="Claude Code says use async/await.",
                    content_type=ContentType.FACT,
                    topics=["async"],
                ),
            ],
            platform=Platform.CLAUDE_CODE,
            session_id="claude-session-1",
        )

        # Ingest from ChatGPT
        await pipeline.ingest_conversation(
            chunks=[
                ConversationChunk(
                    content="ChatGPT recommends type hints.",
                    content_type=ContentType.FACT,
                    topics=["typing"],
                ),
            ],
            platform=Platform.CHATGPT,
            session_id="chatgpt-session-1",
        )

        # Filter by source
        claude_config = SessionConfig(include_sources=[Platform.CLAUDE_CODE])
        claude_memories = await meta_store.get_memories_by_filter(
            session_config=claude_config, limit=100
        )
        assert len(claude_memories) == 1
        assert claude_memories[0].source.platform == Platform.CLAUDE_CODE

        chatgpt_config = SessionConfig(include_sources=[Platform.CHATGPT])
        chatgpt_memories = await meta_store.get_memories_by_filter(
            session_config=chatgpt_config, limit=100
        )
        assert len(chatgpt_memories) == 1
        assert chatgpt_memories[0].source.platform == Platform.CHATGPT


# =====================================================================
# 3. Hybrid search returns results from multiple engines
# =====================================================================


class TestHybridSearchMultiEngine:
    """Verify hybrid search merges semantic, keyword, and graph results."""

    async def test_hybrid_merges_semantic_and_keyword_results(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Results found by keyword but not semantic (and vice versa) are both returned."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        # Store two memories in metadata
        mem_keyword = Memory(
            id="keyword-only",
            content="SQLite FTS5 is great for full-text search indexing.",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CLAUDE_CODE,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["sqlite", "fts5"],
        )
        mem_semantic = Memory(
            id="semantic-only",
            content="Vector databases enable similarity search at scale.",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CHATGPT,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["vectors"],
        )
        await meta_store.save_memory(mem_keyword)
        await meta_store.save_memory(mem_semantic)

        # Semantic search returns only mem_semantic
        vs.search.return_value = [
            {
                "id": "semantic-only",
                "score": 0.88,
                "payload": {"content": mem_semantic.content},
            },
        ]

        # FTS5 uses phrase match, so use a term that appears in mem_keyword's content
        results = await hybrid_search(
            query="full-text",
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            settings=settings,
            limit=10,
        )

        found_ids = {r["id"] for r in results}
        # keyword-only should appear via FTS5, semantic-only via vector search
        assert "keyword-only" in found_ids
        assert "semantic-only" in found_ids

    async def test_hybrid_search_with_graph_boost(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Graph-connected memories get boosted in hybrid search."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        graph = create_knowledge_graph(settings.graph_path)

        mem = Memory(
            id="graph-mem",
            content="Docker containers run isolated processes.",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CLAUDE_CODE,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["docker", "containers"],
        )
        await meta_store.save_memory(mem)

        # Add to knowledge graph
        await graph.add_memory("graph-mem", ["docker", "containers"], [])

        # Semantic search returns it
        vs.search.return_value = [
            {"id": "graph-mem", "score": 0.85, "payload": {"content": mem.content}},
        ]

        results = await hybrid_search(
            query="docker containers",
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            graph=graph,
            settings=settings,
            limit=10,
        )

        assert len(results) >= 1
        assert results[0]["id"] == "graph-mem"

    async def test_hybrid_search_source_filtering(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Hybrid search respects session_config source filters."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        mem_claude = Memory(
            id="filter-claude",
            content="Claude Code insight about testing strategies.",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CLAUDE_CODE,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["testing"],
        )
        mem_chatgpt = Memory(
            id="filter-chatgpt",
            content="ChatGPT insight about testing strategies.",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CHATGPT,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["testing"],
        )
        await meta_store.save_memory(mem_claude)
        await meta_store.save_memory(mem_chatgpt)

        # Both returned by semantic search
        vs.search.return_value = [
            {"id": "filter-claude", "score": 0.9, "payload": {}},
            {"id": "filter-chatgpt", "score": 0.9, "payload": {}},
        ]

        # Filter to only Claude Code
        config = SessionConfig(include_sources=[Platform.CLAUDE_CODE])

        results = await hybrid_search(
            query="testing strategies",
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            session_config=config,
            settings=settings,
            limit=10,
        )

        found_ids = {r["id"] for r in results}
        # Both may appear since vector search mock doesn't filter,
        # but keyword search does filter; at minimum claude should be present
        assert "filter-claude" in found_ids


# =====================================================================
# 4. Full pipeline with intelligence (mock LLM) -> verify topics/entities
# =====================================================================


class TestPipelineWithIntelligence:
    """End-to-end: intelligence pipeline enriches memories with LLM results."""

    async def test_full_pipeline_populates_topics_entities_summary(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Full pipeline with LLM: classification, extraction, summarization all applied."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()
        llm = _make_mock_llm(available=True)

        # Configure LLM responses for the intelligence graph
        llm.generate_structured.side_effect = [
            # classify_node: one per chunk
            ClassificationResult(content_type="decision", confidence=0.92),
            ClassificationResult(content_type="learning", confidence=0.87),
            # extract_node
            ExtractionResult(
                topics=["microservices", "api-design"],
                entities=["FastAPI", "gRPC"],
            ),
            # summarize_node
            SummaryResult(summary="Decided on microservices architecture with FastAPI and gRPC"),
        ]

        graph = create_knowledge_graph(settings.graph_path)

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            llm_client=llm,
            graph=graph,
        )

        chunks = [
            ConversationChunk(
                content="Let's go with a microservices architecture using FastAPI.",
                content_type=ContentType.RAW_EXCHANGE,
                topics=["architecture"],
            ),
            ConversationChunk(
                content="I learned that gRPC is better for inter-service communication.",
                content_type=ContentType.RAW_EXCHANGE,
                topics=["networking"],
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            session_id="intel-session",
        )

        assert len(memories) == 2

        # Classification applied
        assert memories[0].content_type == ContentType.DECISION
        assert memories[0].confidence == 0.92
        assert memories[1].content_type == ContentType.LEARNING
        assert memories[1].confidence == 0.87

        # Extraction merged: LLM topics + original topics
        assert "microservices" in memories[0].topics
        assert "api-design" in memories[0].topics
        assert "architecture" in memories[0].topics  # Pre-existing preserved

        # LLM entities populated
        assert "FastAPI" in memories[0].entities
        assert "gRPC" in memories[0].entities

        # Summary used as session title (none was provided)
        assert memories[0].source.session_title is not None
        assert "microservices" in memories[0].source.session_title.lower()

        # Knowledge graph updated
        assert graph.node_count > 0

        # Verify memories persisted in metadata store with enriched data
        for mem in memories:
            stored = await meta_store.get_memory(mem.id)
            assert stored is not None
            assert len(stored.topics) > 0

    async def test_pipeline_graceful_degradation_on_llm_failure(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """When LLM fails entirely, pipeline still ingests with heuristic data."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()
        llm = _make_mock_llm(available=True)

        # LLM always fails
        llm.generate_structured.side_effect = RuntimeError("Service unavailable")

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="We decided to deploy on Kubernetes.",
                content_type=ContentType.RAW_EXCHANGE,
                topics=["deployment"],
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        # Should still succeed
        assert len(memories) == 1
        assert memories[0].content == "We decided to deploy on Kubernetes."
        # Original topics preserved even though LLM failed
        assert "deployment" in memories[0].topics

        # Verify stored
        stored = await meta_store.get_memory(memories[0].id)
        assert stored is not None

    async def test_pipeline_without_llm_still_works(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Pipeline works fine without any LLM client at all."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            llm_client=None,
        )

        chunks = [
            ConversationChunk(
                content="Simple fact about Python.",
                content_type=ContentType.FACT,
                topics=["python"],
                entities=["Python"],
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CHATGPT,
            session_id="no-llm",
            session_title="No LLM session",
        )

        assert len(memories) == 1
        assert memories[0].topics == ["python"]
        assert memories[0].entities == ["Python"]
        assert memories[0].source.session_title == "No LLM session"


# =====================================================================
# 5. Deduplication
# =====================================================================


class TestDeduplication:
    """Verify file-based deduplication prevents double-ingestion."""

    async def test_duplicate_file_skipped(
        self, meta_store: MetadataStore, settings: MemgenticSettings, tmp_path: Path
    ):
        """Ingesting the same file twice produces memories only once."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        # Create a real file for hashing
        test_file = tmp_path / "conversation.jsonl"
        test_file.write_text('{"role":"user","content":"hello"}')

        chunks = [
            ConversationChunk(
                content="Hello from a conversation file.",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        # First ingest
        first = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            file_path=str(test_file),
        )
        assert len(first) == 1

        # Second ingest of the same file
        second = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            file_path=str(test_file),
        )
        assert len(second) == 0  # Skipped as duplicate


# =====================================================================
# 6. Memory lifecycle
# =====================================================================


class TestMemoryLifecycle:
    """Test memory status transitions and access tracking."""

    async def test_access_tracking(self, meta_store: MetadataStore, settings: MemgenticSettings):
        """Accessing a memory updates access_count and last_accessed."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        mem = await pipeline.ingest_single(
            content="Access tracking test memory.",
            content_type=ContentType.FACT,
        )

        # Initial state
        stored = await meta_store.get_memory(mem.id)
        assert stored is not None
        assert stored.access_count == 0

        # Update access
        await meta_store.update_access(mem.id)

        updated = await meta_store.get_memory(mem.id)
        assert updated is not None
        assert updated.access_count == 1
        assert updated.last_accessed is not None

    async def test_status_transitions(self, meta_store: MetadataStore, settings: MemgenticSettings):
        """Memory can transition from active -> archived -> active."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        mem = await pipeline.ingest_single(
            content="Status transition test memory.",
            content_type=ContentType.FACT,
        )

        assert (await meta_store.get_memory(mem.id)).status == MemoryStatus.ACTIVE

        await meta_store.update_memory_status(mem.id, MemoryStatus.ARCHIVED.value)
        assert (await meta_store.get_memory(mem.id)).status == MemoryStatus.ARCHIVED

        await meta_store.update_memory_status(mem.id, MemoryStatus.ACTIVE.value)
        assert (await meta_store.get_memory(mem.id)).status == MemoryStatus.ACTIVE

    async def test_filtered_count(self, meta_store: MetadataStore, settings: MemgenticSettings):
        """Filtered count works with session config and content type."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        await pipeline.ingest_single(
            content="Fact from Claude",
            content_type=ContentType.FACT,
            platform=Platform.CLAUDE_CODE,
        )
        await pipeline.ingest_single(
            content="Decision from ChatGPT",
            content_type=ContentType.DECISION,
            platform=Platform.CHATGPT,
        )
        await pipeline.ingest_single(
            content="Another fact from Claude",
            content_type=ContentType.FACT,
            platform=Platform.CLAUDE_CODE,
        )

        total = await meta_store.get_total_count()
        assert total == 3

        claude_config = SessionConfig(include_sources=[Platform.CLAUDE_CODE])
        claude_count = await meta_store.get_filtered_count(session_config=claude_config)
        assert claude_count == 2

        fact_count = await meta_store.get_filtered_count(content_type=ContentType.FACT)
        assert fact_count == 2


# =====================================================================
# 7. Knowledge graph integration
# =====================================================================


class TestKnowledgeGraphIntegration:
    """Verify the knowledge graph is updated during ingestion."""

    async def test_graph_populated_from_pipeline(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Topics and entities from ingested memories are added to the knowledge graph."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()
        graph = create_knowledge_graph(settings.graph_path)

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            graph=graph,
        )

        await pipeline.ingest_single(
            content="FastAPI and Pydantic work well together.",
            content_type=ContentType.FACT,
            topics=["fastapi", "pydantic"],
            entities=["FastAPI", "Pydantic"],
        )

        assert graph.node_count >= 2
        data = await graph.get_graph_data(min_weight=1)
        node_ids = {n["id"] for n in data.get("nodes", [])}
        assert "fastapi" in node_ids or "FastAPI" in node_ids

    async def test_graph_neighbors_after_ingestion(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Entities co-occurring in a memory are connected in the graph."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()
        graph = create_knowledge_graph(settings.graph_path)

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
            graph=graph,
        )

        await pipeline.ingest_single(
            content="Docker and Kubernetes for container orchestration.",
            content_type=ContentType.FACT,
            topics=["docker", "kubernetes"],
        )

        result = await graph.query_neighbors("docker", depth=1)
        assert not result.get("not_found", False)
        neighbor_names = {n["name"] for n in result.get("neighbors", [])}
        assert "kubernetes" in neighbor_names


# =====================================================================
# 8. Credential scrubbing in pipeline
# =====================================================================


class TestCredentialScrubbing:
    """Verify credential scrubbing works in the pipeline."""

    async def test_api_keys_scrubbed(self, meta_store: MetadataStore, settings: MemgenticSettings):
        """API keys in content are redacted before storage."""
        settings.enable_credential_scrubbing = True
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        # Synthetic test fixture — not a real API key.  # pragma: allowlist secret
        fake_key = "sk-" + "X" * 48
        mem = await pipeline.ingest_single(
            content=f"Set OPENAI_API_KEY={fake_key} to use the API.",
            content_type=ContentType.FACT,
        )

        stored = await meta_store.get_memory(mem.id)
        assert stored is not None
        # The actual key value should be redacted
        assert fake_key not in stored.content

    async def test_scrubbing_disabled(self, meta_store: MetadataStore, settings: MemgenticSettings):
        """When scrubbing is disabled, content is stored as-is."""
        settings.enable_credential_scrubbing = False
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        content = "Just a normal fact without credentials."
        mem = await pipeline.ingest_single(
            content=content,
            content_type=ContentType.FACT,
        )

        stored = await meta_store.get_memory(mem.id)
        assert stored is not None
        assert stored.content == content


# =====================================================================
# 9. Source stats
# =====================================================================


class TestSourceStats:
    """Verify source statistics are correctly reported."""

    async def test_source_stats_after_multi_platform_ingest(
        self, meta_store: MetadataStore, settings: MemgenticSettings
    ):
        """Source stats accurately reflect ingested memories by platform."""
        embedder = _make_mock_embedder()
        vs = _make_mock_vector_store()

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=meta_store,
            vector_store=vs,
            embedder=embedder,
        )

        # Ingest from multiple platforms
        for _ in range(3):
            await pipeline.ingest_single(
                content="Claude memory",
                content_type=ContentType.FACT,
                platform=Platform.CLAUDE_CODE,
            )
        for _ in range(2):
            await pipeline.ingest_single(
                content="ChatGPT memory",
                content_type=ContentType.FACT,
                platform=Platform.CHATGPT,
            )

        stats = await meta_store.get_source_stats()
        assert stats.get("claude_code", 0) == 3
        assert stats.get("chatgpt", 0) == 2
        assert await meta_store.get_total_count() == 5
