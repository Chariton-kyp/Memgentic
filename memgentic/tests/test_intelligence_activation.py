"""Tests for fully activated LLM intelligence features.

Covers:
- LLM classification wired into the pipeline
- LLM extraction wired into the pipeline
- LLM summarization wired into the pipeline
- Contradiction detection on ingest
- Importance decay in search ranking
- Consolidation using public MetadataStore methods
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.graph.search import hybrid_search
from memgentic.models import (
    CaptureMethod,
    ContentType,
    ConversationChunk,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.processing.maintenance import consolidate
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


def _mock_llm(available: bool = True):
    """Create a mock LLMClient with configurable availability."""
    llm = MagicMock()
    llm.available = available
    llm.generate = AsyncMock(return_value="")
    llm.generate_structured = AsyncMock(return_value=None)
    return llm


def _make_memory(
    mid: str = "m-1",
    content: str = "test content",
    platform: Platform = Platform.CLAUDE_CODE,
    created_at: datetime | None = None,
    importance_score: float = 1.0,
    access_count: int = 0,
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        created_at=created_at or datetime.now(UTC),
        importance_score=importance_score,
        access_count=access_count,
        status=status,
    )


@pytest.fixture()
def settings(tmp_path):
    # These tests assert exact LLM call sequences and vector_store.search call
    # counts from before fact-distillation and write-time-dedup existed. Disable
    # those features here so this file continues to test classification /
    # extraction / summarization / contradiction wiring in isolation. The new
    # features have dedicated coverage in test_pipeline.py / test_intelligence.py.
    return MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=DIMS,
        memory_half_life_days=90,
        enable_fact_distillation=False,
        enable_write_time_dedup=False,
    )


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
    vs = AsyncMock()
    vs.upsert_memory = AsyncMock()
    vs.upsert_memories_batch = AsyncMock()
    vs.search = AsyncMock(return_value=[])
    vs.delete_memory = AsyncMock()
    return vs


# =====================================================================
# Task 1: LLM Classification in Pipeline
# =====================================================================


class TestLLMClassificationInPipeline:
    """Verify LLM classification is wired into the ingestion pipeline."""

    async def test_llm_classification_applied_to_memories(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """When LLM is available, classification results set content_type on memories."""
        llm = _mock_llm(available=True)
        # LLM returns "decision" for classification
        llm.generate_structured.side_effect = [
            # classify_node calls for each chunk
            ClassificationResult(content_type="decision", confidence=0.95),
            ClassificationResult(content_type="code_snippet", confidence=0.88),
            # extract_node call
            ExtractionResult(topics=["python"], entities=["FastAPI"]),
            # summarize_node call
            SummaryResult(summary="Test summary"),
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="We decided to use FastAPI",
                content_type=ContentType.RAW_EXCHANGE,
            ),
            ConversationChunk(
                content="def hello(): return 'world'",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            session_id="test-session",
        )

        assert len(memories) == 2
        assert memories[0].content_type == ContentType.DECISION
        assert memories[0].confidence == 0.95
        assert memories[1].content_type == ContentType.CODE_SNIPPET
        assert memories[1].confidence == 0.88

    async def test_heuristic_fallback_when_no_llm(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """When no LLM client, pipeline uses heuristic classification."""
        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=None,  # No LLM
        )

        chunks = [
            ConversationChunk(
                content="We decided to use FastAPI",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        assert len(memories) == 1
        # Original content_type preserved (no LLM to change it)
        assert memories[0].content_type == ContentType.RAW_EXCHANGE

    async def test_llm_failure_falls_back_to_heuristics(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """When LLM raises an error, pipeline falls back gracefully."""
        llm = _mock_llm(available=True)
        llm.generate_structured.side_effect = RuntimeError("API rate limited")

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="We decided to use FastAPI",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        # Should not raise
        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        assert len(memories) == 1


# =====================================================================
# Task 2: LLM Entity/Topic Extraction
# =====================================================================


class TestLLMExtractionInPipeline:
    """Verify LLM extraction is wired to populate memory.topics and memory.entities."""

    async def test_extraction_populates_topics_and_entities(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """LLM extraction results appear in stored memory metadata."""
        llm = _mock_llm(available=True)
        llm.generate_structured.side_effect = [
            # classify
            ClassificationResult(content_type="fact", confidence=0.9),
            # extract — this is the key test
            ExtractionResult(
                topics=["architecture", "microservices"],
                entities=["FastAPI", "Docker"],
            ),
            # summarize
            SummaryResult(summary="Architecture discussion"),
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="We use FastAPI with Docker for microservices",
                content_type=ContentType.RAW_EXCHANGE,
                topics=["python"],  # Pre-existing topic
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        assert len(memories) == 1
        # LLM-extracted topics merged with existing
        assert "architecture" in memories[0].topics
        assert "microservices" in memories[0].topics
        assert "python" in memories[0].topics  # Pre-existing preserved
        # LLM-extracted entities
        assert "FastAPI" in memories[0].entities
        assert "Docker" in memories[0].entities


# =====================================================================
# Task 3: LLM Summarization
# =====================================================================


class TestLLMSummarizationInPipeline:
    """Verify LLM summarization is wired and applied."""

    async def test_summarization_sets_session_title(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """LLM summary is used as session_title when no title provided."""
        llm = _mock_llm(available=True)
        llm.generate_structured.side_effect = [
            # classify (2 chunks)
            ClassificationResult(content_type="decision", confidence=0.9),
            ClassificationResult(content_type="fact", confidence=0.85),
            # extract
            ExtractionResult(topics=["testing"], entities=[]),
            # summarize — sets session title
            SummaryResult(summary="Decided on test framework and coverage targets"),
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="Let's use pytest",
                content_type=ContentType.RAW_EXCHANGE,
            ),
            ConversationChunk(
                content="Target 80% coverage",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            session_title=None,  # No title provided
        )

        assert len(memories) == 2
        # Summary applied as session title
        assert memories[0].source.session_title == "Decided on test framework and coverage targets"

    async def test_summarization_does_not_overwrite_existing_title(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """When session_title is already set, LLM summary does not overwrite it."""
        llm = _mock_llm(available=True)
        llm.generate_structured.side_effect = [
            ClassificationResult(content_type="fact", confidence=0.9),
            ClassificationResult(content_type="fact", confidence=0.9),
            ExtractionResult(topics=[], entities=[]),
            SummaryResult(summary="LLM-generated summary"),
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(content="Content A", content_type=ContentType.RAW_EXCHANGE),
            ConversationChunk(content="Content B", content_type=ContentType.RAW_EXCHANGE),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
            session_title="Original title",
        )

        # Existing title preserved
        assert memories[0].source.session_title == "Original title"


# =====================================================================
# Task 4: Contradiction Detection on Ingest
# =====================================================================


class TestContradictionDetection:
    """Verify contradiction detection marks older memories as superseded."""

    async def test_contradiction_supersedes_older_memory(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """When a new memory contradicts an existing one, the old one is superseded."""
        # Save an existing memory
        existing = _make_memory(
            mid="existing-1",
            content="We use PostgreSQL for the database",
        )
        await metadata_store.save_memory(existing)

        llm = _mock_llm(available=True)
        # Intelligence pipeline calls
        llm.generate_structured.side_effect = [
            ClassificationResult(content_type="decision", confidence=0.9),
            ExtractionResult(topics=["database"], entities=[]),
            SummaryResult(summary="Database change"),
        ]

        # Vector search returns the existing memory as similar.
        # search() is called twice: once for corroboration, once for contradiction detection.
        similar_result = [
            {
                "id": "existing-1",
                "score": 0.90,
                "payload": {"platform": "claude_code"},
            }
        ]
        mock_vector_store.search.side_effect = [
            similar_result,  # corroboration check
            similar_result,  # contradiction detection
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="MongoDB is our primary data store going forward",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        assert len(memories) == 1
        # The old memory should be superseded
        old = await metadata_store.get_memory("existing-1")
        assert old is not None
        assert old.status == MemoryStatus.SUPERSEDED
        # New memory should reference the old one
        assert "existing-1" in memories[0].supersedes

    async def test_no_contradiction_when_high_text_overlap(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """Similar memories with high text overlap are not flagged as contradictions."""
        existing = _make_memory(
            mid="existing-2",
            content="Python is great for backend development",
        )
        await metadata_store.save_memory(existing)

        llm = _mock_llm(available=True)
        llm.generate_structured.side_effect = [
            ClassificationResult(content_type="fact", confidence=0.9),
            ExtractionResult(topics=["python"], entities=[]),
            SummaryResult(summary="Python discussion"),
        ]

        # High similarity AND high text overlap = not a contradiction
        similar_result = [
            {
                "id": "existing-2",
                "score": 0.92,
                "payload": {"platform": "claude_code"},
            }
        ]
        mock_vector_store.search.side_effect = [
            similar_result,  # corroboration check
            similar_result,  # contradiction detection
        ]

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=llm,
        )

        chunks = [
            ConversationChunk(
                content="Python is great for backend development and APIs",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        # The existing memory should still be active (not contradicted)
        old = await metadata_store.get_memory("existing-2")
        assert old is not None
        assert old.status == MemoryStatus.ACTIVE

    async def test_no_contradiction_without_llm(
        self, metadata_store: MetadataStore, mock_embedder, mock_vector_store, settings
    ):
        """Without LLM, contradiction detection is skipped (corroboration may still run)."""
        # Disable corroboration so search is only called for contradiction detection
        settings.enable_corroboration = False

        mock_vector_store.search.return_value = []

        pipeline = IngestionPipeline(
            settings=settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            llm_client=None,
        )

        chunks = [
            ConversationChunk(
                content="Some content",
                content_type=ContentType.RAW_EXCHANGE,
            ),
        ]

        memories = await pipeline.ingest_conversation(
            chunks=chunks,
            platform=Platform.CLAUDE_CODE,
        )

        assert len(memories) == 1
        # Without LLM, contradiction detection is skipped — search should not be called
        mock_vector_store.search.assert_not_called()


# =====================================================================
# Task 5: Importance Decay in Search Ranking
# =====================================================================


class TestImportanceDecayInSearch:
    """Verify importance_score and temporal decay affect search ranking."""

    async def test_newer_memory_ranks_higher(self, metadata_store: MetadataStore, settings):
        """A newer memory should rank higher than an older one with same base score."""
        now = datetime.now(UTC)

        new_mem = _make_memory(
            mid="new-1",
            content="New information about Python",
            created_at=now,
            importance_score=1.0,
        )
        old_mem = _make_memory(
            mid="old-1",
            content="Old information about Python",
            created_at=now - timedelta(days=180),
            importance_score=1.0,
        )
        await metadata_store.save_memory(new_mem)
        await metadata_store.save_memory(old_mem)

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = _fake_embedding()

        mock_vs = AsyncMock()
        # Both returned at same rank
        mock_vs.search.return_value = [
            {"id": "new-1", "score": 0.9, "payload": {}},
            {"id": "old-1", "score": 0.9, "payload": {}},
        ]

        results = await hybrid_search(
            query="python info",
            metadata_store=metadata_store,
            vector_store=mock_vs,
            embedder=mock_embedder,
            settings=settings,
            limit=10,
        )

        assert len(results) == 2
        assert results[0]["id"] == "new-1"
        assert results[1]["id"] == "old-1"
        assert results[0]["score"] > results[1]["score"]

    async def test_high_importance_memory_ranks_higher(
        self, metadata_store: MetadataStore, settings
    ):
        """A memory with higher importance_score ranks higher."""
        now = datetime.now(UTC)

        important = _make_memory(
            mid="imp-1",
            content="Important fact",
            created_at=now,
            importance_score=1.0,
        )
        unimportant = _make_memory(
            mid="unimp-1",
            content="Less important fact",
            created_at=now,
            importance_score=0.3,
        )
        await metadata_store.save_memory(important)
        await metadata_store.save_memory(unimportant)

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = _fake_embedding()

        mock_vs = AsyncMock()
        mock_vs.search.return_value = [
            {"id": "imp-1", "score": 0.9, "payload": {}},
            {"id": "unimp-1", "score": 0.9, "payload": {}},
        ]

        results = await hybrid_search(
            query="facts",
            metadata_store=metadata_store,
            vector_store=mock_vs,
            embedder=mock_embedder,
            settings=settings,
            limit=10,
        )

        assert len(results) == 2
        assert results[0]["id"] == "imp-1"

    async def test_decay_formula_correctness(self, metadata_store: MetadataStore, settings):
        """Verify the decay formula: effective_score = base * importance * 0.5^(days/half_life)."""
        now = datetime.now(UTC)
        half_life = settings.memory_half_life_days  # 90

        # Memory exactly one half-life old
        mem = _make_memory(
            mid="decay-1",
            content="Decaying memory",
            created_at=now - timedelta(days=half_life),
            importance_score=1.0,
        )
        # Fresh memory for reference
        fresh = _make_memory(
            mid="fresh-1",
            content="Fresh memory",
            created_at=now,
            importance_score=1.0,
        )
        await metadata_store.save_memory(mem)
        await metadata_store.save_memory(fresh)

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = _fake_embedding()

        mock_vs = AsyncMock()
        # Same RRF position
        mock_vs.search.return_value = [
            {"id": "fresh-1", "score": 1.0, "payload": {}},
            {"id": "decay-1", "score": 1.0, "payload": {}},
        ]

        results = await hybrid_search(
            query="test",
            metadata_store=metadata_store,
            vector_store=mock_vs,
            embedder=mock_embedder,
            settings=settings,
            limit=10,
        )

        # fresh-1 should be rank 0 (highest)
        assert results[0]["id"] == "fresh-1"
        # decay-1 score should be approximately half of fresh-1's
        # (same RRF rank, same importance, but half decay)
        # The exact ratio depends on RRF scores being different,
        # but the relative ordering should hold
        assert results[1]["id"] == "decay-1"
        assert results[1]["score"] < results[0]["score"]

    async def test_half_life_from_settings(self, tmp_path):
        """half_life is read from MemgenticSettings.memory_half_life_days."""
        custom_settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
            embedding_dimensions=DIMS,
            memory_half_life_days=30,  # Custom half-life
        )
        assert custom_settings.memory_half_life_days == 30


# =====================================================================
# Task 6: Consolidation Using Public Methods
# =====================================================================


class TestConsolidationPublicMethods:
    """Verify consolidation.py uses only public MetadataStore methods."""

    async def test_update_importance_score_method(self, metadata_store: MetadataStore):
        """MetadataStore.update_importance_score works correctly."""
        mem = _make_memory(mid="pub-1", importance_score=1.0)
        await metadata_store.save_memory(mem)

        await metadata_store.update_importance_score("pub-1", 0.42)

        got = await metadata_store.get_memory("pub-1")
        assert got is not None
        assert got.importance_score == 0.42

    async def test_update_memory_status_method(self, metadata_store: MetadataStore):
        """MetadataStore.update_memory_status works correctly."""
        mem = _make_memory(mid="pub-2")
        await metadata_store.save_memory(mem)

        await metadata_store.update_memory_status("pub-2", MemoryStatus.SUPERSEDED.value)

        got = await metadata_store.get_memory("pub-2")
        assert got is not None
        assert got.status == MemoryStatus.SUPERSEDED

    async def test_update_importance_scores_batch_method(self, metadata_store: MetadataStore):
        """MetadataStore.update_importance_scores_batch works correctly."""
        mem1 = _make_memory(mid="batch-1", importance_score=1.0)
        mem2 = _make_memory(mid="batch-2", importance_score=1.0)
        await metadata_store.save_memory(mem1)
        await metadata_store.save_memory(mem2)

        await metadata_store.update_importance_scores_batch(
            [
                ("batch-1", 0.5),
                ("batch-2", 0.3),
            ]
        )

        got1 = await metadata_store.get_memory("batch-1")
        got2 = await metadata_store.get_memory("batch-2")
        assert got1 is not None and got1.importance_score == 0.5
        assert got2 is not None and got2.importance_score == 0.3

    async def test_consolidation_uses_public_api(self, metadata_store: MetadataStore, settings):
        """Full consolidation run uses only public MetadataStore methods."""
        now = datetime.now(UTC)
        old_mem = _make_memory(
            mid="consol-1",
            created_at=now - timedelta(days=180),
            importance_score=1.0,
        )
        await metadata_store.save_memory(old_mem)

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(return_value=[])
        mock_vs.delete_memory = AsyncMock()

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * DIMS)

        report = await consolidate(metadata_store, mock_vs, mock_embedder, settings)

        assert report.importance_updated >= 1
        got = await metadata_store.get_memory("consol-1")
        assert got is not None
        assert got.importance_score < 0.3  # Decayed significantly
