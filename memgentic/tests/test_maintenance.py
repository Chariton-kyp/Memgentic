"""Tests for background consolidation — importance recomputation, dedup, contradictions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.processing.maintenance import (
    ConsolidationReport,
    consolidate,
)
from memgentic.processing.utils import text_overlap
from memgentic.storage.metadata import MetadataStore


def _make_memory(
    mid: str = "m-1",
    content: str = "test content",
    platform: Platform = Platform.CLAUDE_CODE,
    confidence: float = 1.0,
    created_at: datetime | None = None,
    access_count: int = 0,
    importance_score: float = 1.0,
) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        confidence=confidence,
        created_at=created_at or datetime.now(UTC),
        access_count=access_count,
        importance_score=importance_score,
    )


@pytest.fixture()
def settings(tmp_path):
    return MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        collection_name="test_memories",
        embedding_dimensions=768,
        memory_half_life_days=90,
    )


@pytest.fixture()
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 768)
    return embedder


@pytest.fixture()
def mock_vector_store():
    vs = AsyncMock()
    vs.search = AsyncMock(return_value=[])
    vs.delete_memory = AsyncMock()
    return vs


class TestRecomputeImportance:
    """Tests for importance score recomputation."""

    async def test_decays_old_memories(
        self, metadata_store: MetadataStore, mock_vector_store, mock_embedder, settings
    ):
        """Memory created 180 days ago with half_life=90 gets score ~0.25."""
        old_date = datetime.now(UTC) - timedelta(days=180)
        mem = _make_memory(mid="old-1", created_at=old_date, importance_score=1.0)
        await metadata_store.save_memory(mem)

        report = await consolidate(metadata_store, mock_vector_store, mock_embedder, settings)

        updated = await metadata_store.get_memory("old-1")
        assert updated is not None
        # e^(-180/90) = e^(-2) ≈ 0.1353
        assert updated.importance_score < 0.3
        assert report.importance_updated >= 1

    async def test_boosts_accessed_memories(
        self, metadata_store: MetadataStore, mock_vector_store, mock_embedder, settings
    ):
        """Memory with access_count=10 gets higher score than unaccessed."""
        date = datetime.now(UTC) - timedelta(days=30)
        mem_accessed = _make_memory(
            mid="accessed-1", created_at=date, access_count=10, importance_score=0.5
        )
        mem_not_accessed = _make_memory(
            mid="not-accessed-1", created_at=date, access_count=0, importance_score=0.5
        )
        await metadata_store.save_memory(mem_accessed)
        await metadata_store.save_memory(mem_not_accessed)

        await consolidate(metadata_store, mock_vector_store, mock_embedder, settings)

        got_accessed = await metadata_store.get_memory("accessed-1")
        got_not_accessed = await metadata_store.get_memory("not-accessed-1")
        assert got_accessed is not None
        assert got_not_accessed is not None
        assert got_accessed.importance_score > got_not_accessed.importance_score

    async def test_new_memory_stays_high(
        self, metadata_store: MetadataStore, mock_vector_store, mock_embedder, settings
    ):
        """Memory created today stays ~1.0."""
        mem = _make_memory(mid="new-1", importance_score=0.5)
        await metadata_store.save_memory(mem)

        await consolidate(metadata_store, mock_vector_store, mock_embedder, settings)

        got = await metadata_store.get_memory("new-1")
        assert got is not None
        assert got.importance_score >= 0.95

    async def test_score_capped_at_1(
        self, metadata_store: MetadataStore, mock_vector_store, mock_embedder, settings
    ):
        """Score never exceeds 1.0 even with high access count."""
        mem = _make_memory(mid="capped-1", access_count=1000, importance_score=0.5)
        await metadata_store.save_memory(mem)

        await consolidate(metadata_store, mock_vector_store, mock_embedder, settings)

        got = await metadata_store.get_memory("capped-1")
        assert got is not None
        assert got.importance_score <= 1.0

    async def test_report_structure(
        self, metadata_store: MetadataStore, mock_vector_store, mock_embedder, settings
    ):
        """ConsolidationReport has correct fields."""
        report = await consolidate(metadata_store, mock_vector_store, mock_embedder, settings)

        assert isinstance(report, ConsolidationReport)
        assert isinstance(report.duplicates_merged, int)
        assert isinstance(report.contradictions_flagged, int)
        assert isinstance(report.importance_updated, int)
        assert isinstance(report.errors, int)
        assert isinstance(report.details, list)

    async def test_empty_store(
        self, metadata_store: MetadataStore, mock_vector_store, mock_embedder, settings
    ):
        """No errors on empty database."""
        report = await consolidate(metadata_store, mock_vector_store, mock_embedder, settings)

        assert report.importance_updated == 0
        assert report.errors == 0
        assert report.duplicates_merged == 0


class TestMergeDuplicates:
    """Tests for duplicate detection and merging."""

    async def test_merge_same_platform(
        self, metadata_store: MetadataStore, mock_embedder, settings
    ):
        """Two nearly identical memories from same platform → one superseded."""
        mem1 = _make_memory(mid="dup-1", content="Python is great", confidence=0.9)
        mem2 = _make_memory(mid="dup-2", content="Python is great for dev", confidence=0.8)
        await metadata_store.save_memory(mem1)
        await metadata_store.save_memory(mem2)

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "dup-2",
                    "score": 0.95,
                    "payload": {"platform": "claude_code", "confidence": 0.8},
                }
            ]
        )
        mock_vs.delete_memory = AsyncMock()

        report = await consolidate(metadata_store, mock_vs, mock_embedder, settings)

        assert report.duplicates_merged == 1
        # Lower confidence one should be superseded
        discard = await metadata_store.get_memory("dup-2")
        assert discard is not None
        assert discard.status == MemoryStatus.SUPERSEDED

    async def test_no_merge_different_platform(
        self, metadata_store: MetadataStore, mock_embedder, settings
    ):
        """Similar memories from different platforms → no merge."""
        mem1 = _make_memory(mid="cross-1", content="Python is great", platform=Platform.CLAUDE_CODE)
        mem2 = _make_memory(mid="cross-2", content="Python is great", platform=Platform.CHATGPT)
        await metadata_store.save_memory(mem1)
        await metadata_store.save_memory(mem2)

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "cross-2",
                    "score": 0.95,
                    "payload": {"platform": "chatgpt", "confidence": 1.0},
                }
            ]
        )
        mock_vs.delete_memory = AsyncMock()

        report = await consolidate(metadata_store, mock_vs, mock_embedder, settings)

        assert report.duplicates_merged == 0

    async def test_contradiction_flagged(
        self, metadata_store: MetadataStore, mock_embedder, settings
    ):
        """High semantic similarity but low text overlap across platforms → contradiction."""
        mem1 = _make_memory(
            mid="contra-1",
            content="We use PostgreSQL for the database layer",
            platform=Platform.CLAUDE_CODE,
        )
        mem2 = _make_memory(
            mid="contra-2",
            content="MongoDB is our primary data store going forward",
            platform=Platform.CHATGPT,
        )
        await metadata_store.save_memory(mem1)
        await metadata_store.save_memory(mem2)

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "contra-2",
                    "score": 0.88,
                    "payload": {"platform": "chatgpt", "confidence": 1.0},
                }
            ]
        )
        mock_vs.delete_memory = AsyncMock()

        report = await consolidate(metadata_store, mock_vs, mock_embedder, settings)

        assert report.contradictions_flagged >= 1

    async def test_merge_keeps_higher_confidence(
        self, metadata_store: MetadataStore, mock_embedder, settings
    ):
        """Winner has higher confidence after merge."""
        mem1 = _make_memory(mid="hc-1", content="Test content A", confidence=0.7)
        mem2 = _make_memory(mid="hc-2", content="Test content A variant", confidence=0.95)
        await metadata_store.save_memory(mem1)
        await metadata_store.save_memory(mem2)

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "hc-2",
                    "score": 0.96,
                    "payload": {"platform": "claude_code", "confidence": 0.95},
                }
            ]
        )
        mock_vs.delete_memory = AsyncMock()

        report = await consolidate(metadata_store, mock_vs, mock_embedder, settings)

        assert report.duplicates_merged == 1
        # mem1 (lower confidence) should be superseded
        discarded = await metadata_store.get_memory("hc-1")
        assert discarded is not None
        assert discarded.status == MemoryStatus.SUPERSEDED

        kept = await metadata_store.get_memory("hc-2")
        assert kept is not None
        assert kept.status == MemoryStatus.ACTIVE


class TestTextOverlap:
    """Tests for _text_overlap helper."""

    def test_identical_texts(self):
        assert text_overlap("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert text_overlap("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        score = text_overlap("the cat sat", "the dog sat")
        assert 0.3 < score < 0.8

    def test_empty_text(self):
        assert text_overlap("", "hello") == 0.0
        assert text_overlap("hello", "") == 0.0
