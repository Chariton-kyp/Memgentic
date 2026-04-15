"""Tests for SQLite metadata store (MetadataStore)."""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(
    id: str = "m-1",
    content: str = "test content",
    platform: Platform = Platform.CLAUDE_CODE,
    content_type: ContentType = ContentType.FACT,
    confidence: float = 1.0,
    session_id: str | None = None,
) -> Memory:
    return Memory(
        id=id,
        content=content,
        content_type=content_type,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
            session_id=session_id,
        ),
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSaveAndRetrieve:
    """Round-trip save / get operations."""

    async def test_save_and_get_memory(self, metadata_store: MetadataStore, sample_memory: Memory):
        await metadata_store.save_memory(sample_memory)
        got = await metadata_store.get_memory(sample_memory.id)

        assert got is not None
        assert got.id == sample_memory.id
        assert got.content == sample_memory.content
        assert got.source.platform == Platform.CLAUDE_CODE
        assert got.source.platform_version == "claude-sonnet-4"
        assert got.confidence == pytest.approx(0.95)
        assert got.topics == ["qdrant", "vector-db", "architecture"]
        assert got.entities == ["ExampleCorp", "Memgentic"]

    async def test_get_memory_not_found(self, metadata_store: MetadataStore):
        got = await metadata_store.get_memory("nonexistent")
        assert got is None

    async def test_save_memories_batch_and_count(self, metadata_store: MetadataStore):
        memories = [_make_memory(id=f"batch-{i}", content=f"Memory {i}") for i in range(5)]
        await metadata_store.save_memories_batch(memories)
        count = await metadata_store.get_total_count()
        assert count == 5


class TestFullTextSearch:
    """FTS5 search including sanitisation of special characters."""

    async def test_search_basic(self, metadata_store: MetadataStore):
        mem = _make_memory(id="fts-1", content="Python asyncio event loop tutorial")
        await metadata_store.save_memory(mem)

        results = await metadata_store.search_fulltext("asyncio")
        assert len(results) >= 1
        assert results[0].id == "fts-1"

    async def test_search_special_chars_cpp(self, metadata_store: MetadataStore):
        """FTS5 must not crash on special characters like 'C++'."""
        mem = _make_memory(id="fts-cpp", content="C++ template meta-programming guide")
        await metadata_store.save_memory(mem)

        # Should not raise — the store wraps in a phrase query
        results = await metadata_store.search_fulltext("C++")
        # The phrase-quoted query may or may not match, but must not error
        assert isinstance(results, list)

    async def test_search_with_quotes(self, metadata_store: MetadataStore):
        mem = _make_memory(id="fts-q", content='He said "hello world" to the compiler')
        await metadata_store.save_memory(mem)
        results = await metadata_store.search_fulltext('"hello world"')
        assert isinstance(results, list)

    async def test_search_with_session_config(self, metadata_store: MetadataStore):
        mem1 = _make_memory(
            id="fts-s1", content="Qdrant vector database", platform=Platform.CLAUDE_CODE
        )
        mem2 = _make_memory(id="fts-s2", content="Qdrant cloud setup", platform=Platform.CHATGPT)
        await metadata_store.save_memories_batch([mem1, mem2])

        config = SessionConfig(include_sources=[Platform.CLAUDE_CODE])
        results = await metadata_store.search_fulltext("Qdrant", session_config=config)
        assert all(r.source.platform == Platform.CLAUDE_CODE for r in results)

    async def test_search_no_results(self, metadata_store: MetadataStore):
        results = await metadata_store.search_fulltext("xyznonexistent")
        assert results == []


class TestSourceStats:
    async def test_get_source_stats(self, metadata_store: MetadataStore):
        memories = [
            _make_memory(id="ss-1", platform=Platform.CLAUDE_CODE),
            _make_memory(id="ss-2", platform=Platform.CLAUDE_CODE),
            _make_memory(id="ss-3", platform=Platform.CHATGPT),
        ]
        await metadata_store.save_memories_batch(memories)
        stats = await metadata_store.get_source_stats()

        assert stats["claude_code"] == 2
        assert stats["chatgpt"] == 1

    async def test_get_source_stats_empty(self, metadata_store: MetadataStore):
        stats = await metadata_store.get_source_stats()
        assert stats == {}


class TestFilterQueries:
    async def test_filter_by_include_sources(self, metadata_store: MetadataStore):
        memories = [
            _make_memory(id="f-1", platform=Platform.CLAUDE_CODE),
            _make_memory(id="f-2", platform=Platform.CHATGPT),
            _make_memory(id="f-3", platform=Platform.GEMINI_CLI),
        ]
        await metadata_store.save_memories_batch(memories)

        config = SessionConfig(include_sources=[Platform.CLAUDE_CODE, Platform.GEMINI_CLI])
        results = await metadata_store.get_memories_by_filter(session_config=config)
        platforms = {r.source.platform for r in results}
        assert platforms == {Platform.CLAUDE_CODE, Platform.GEMINI_CLI}

    async def test_filter_by_exclude_sources(self, metadata_store: MetadataStore):
        memories = [
            _make_memory(id="fe-1", platform=Platform.CLAUDE_CODE),
            _make_memory(id="fe-2", platform=Platform.CHATGPT),
        ]
        await metadata_store.save_memories_batch(memories)

        config = SessionConfig(exclude_sources=[Platform.CHATGPT])
        results = await metadata_store.get_memories_by_filter(session_config=config)
        assert all(r.source.platform != Platform.CHATGPT for r in results)

    async def test_filter_by_content_type(self, metadata_store: MetadataStore):
        memories = [
            _make_memory(id="ct-1", content_type=ContentType.DECISION),
            _make_memory(id="ct-2", content_type=ContentType.FACT),
        ]
        await metadata_store.save_memories_batch(memories)

        results = await metadata_store.get_memories_by_filter(content_type=ContentType.DECISION)
        assert len(results) == 1
        assert results[0].content_type == ContentType.DECISION

    async def test_filter_by_min_confidence(self, metadata_store: MetadataStore):
        memories = [
            _make_memory(id="mc-1", confidence=0.3),
            _make_memory(id="mc-2", confidence=0.9),
        ]
        await metadata_store.save_memories_batch(memories)

        config = SessionConfig(min_confidence=0.5)
        results = await metadata_store.get_memories_by_filter(session_config=config)
        assert len(results) == 1
        assert results[0].confidence >= 0.5

    async def test_filter_no_config(self, metadata_store: MetadataStore):
        memories = [_make_memory(id=f"nc-{i}") for i in range(3)]
        await metadata_store.save_memories_batch(memories)
        results = await metadata_store.get_memories_by_filter()
        assert len(results) == 3

    async def test_filter_with_offset_and_limit(self, metadata_store: MetadataStore):
        memories = [_make_memory(id=f"ol-{i}", content=f"Memory {i}") for i in range(5)]
        await metadata_store.save_memories_batch(memories)
        results = await metadata_store.get_memories_by_filter(limit=2, offset=0)
        assert len(results) == 2


class TestUpdateAccess:
    async def test_update_access(self, metadata_store: MetadataStore):
        mem = _make_memory(id="ua-1")
        await metadata_store.save_memory(mem)

        await metadata_store.update_access("ua-1")
        got = await metadata_store.get_memory("ua-1")
        assert got is not None
        assert got.access_count == 1
        assert got.last_accessed is not None

        await metadata_store.update_access("ua-1")
        got2 = await metadata_store.get_memory("ua-1")
        assert got2 is not None
        assert got2.access_count == 2


class TestFileProcessedDedup:
    async def test_is_file_processed_false_initially(self, metadata_store: MetadataStore):
        result = await metadata_store.is_file_processed("/some/file.jsonl", "abc123")
        assert result is False

    async def test_mark_and_check_processed(self, metadata_store: MetadataStore):
        await metadata_store.mark_file_processed("/some/file.jsonl", "abc123", "claude_code", 5)
        assert await metadata_store.is_file_processed("/some/file.jsonl", "abc123") is True

    async def test_different_hash_not_processed(self, metadata_store: MetadataStore):
        await metadata_store.mark_file_processed("/some/file.jsonl", "hash_v1", "claude_code", 5)
        # Same path, different hash => not processed (file changed)
        assert await metadata_store.is_file_processed("/some/file.jsonl", "hash_v2") is False


class TestBuildFilterConditions:
    """Test the private _build_filter_conditions helper directly."""

    def test_none_config(self, metadata_store: MetadataStore):
        conditions, params = metadata_store._build_filter_conditions(None)
        assert conditions == []
        assert params == []

    def test_include_sources(self, metadata_store: MetadataStore):
        config = SessionConfig(include_sources=[Platform.CLAUDE_CODE, Platform.CHATGPT])
        conditions, params = metadata_store._build_filter_conditions(config)
        assert len(conditions) == 1
        assert "IN" in conditions[0]
        assert params == ["claude_code", "chatgpt"]

    def test_exclude_sources(self, metadata_store: MetadataStore):
        config = SessionConfig(exclude_sources=[Platform.CODEX_CLI])
        conditions, params = metadata_store._build_filter_conditions(config)
        assert len(conditions) == 1
        assert "NOT IN" in conditions[0]
        assert params == ["codex_cli"]

    def test_include_content_types(self, metadata_store: MetadataStore):
        config = SessionConfig(include_content_types=[ContentType.DECISION, ContentType.FACT])
        conditions, params = metadata_store._build_filter_conditions(config)
        assert any("content_type" in c for c in conditions)
        assert "decision" in params
        assert "fact" in params

    def test_min_confidence(self, metadata_store: MetadataStore):
        config = SessionConfig(min_confidence=0.8)
        conditions, params = metadata_store._build_filter_conditions(config)
        assert any("confidence" in c for c in conditions)
        assert 0.8 in params

    def test_combined_filters(self, metadata_store: MetadataStore):
        config = SessionConfig(
            include_sources=[Platform.CLAUDE_CODE],
            exclude_sources=[Platform.CHATGPT],
            min_confidence=0.5,
        )
        conditions, params = metadata_store._build_filter_conditions(config)
        # include + exclude + confidence = 3 conditions
        assert len(conditions) == 3
