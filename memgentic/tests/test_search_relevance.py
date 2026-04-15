"""Quality tests for hybrid search and search-relevance behavior.

These tests use mocked embedder/vector store so they run offline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from memgentic.graph.search import hybrid_search
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SessionConfig,
    SourceMetadata,
)
from memgentic.processing.query import parse_query_intent

DIMS = 768


def _vec(seed: float = 0.1) -> list[float]:
    return [seed] * DIMS


def _make_memory(content: str, ctype: ContentType = ContentType.FACT) -> Memory:
    return Memory(
        content=content,
        content_type=ctype,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        created_at=datetime.now(UTC),
    )


@pytest.fixture()
def mock_embedder():
    e = AsyncMock()
    e.embed.return_value = _vec()
    return e


@pytest.fixture()
def mock_vector_store():
    vs = AsyncMock()
    vs.search.return_value = []
    return vs


@pytest.fixture()
def mock_metadata_store():
    store = AsyncMock()
    store.search_fulltext.return_value = []
    store.get_memory.return_value = None
    store.get_memories_batch.return_value = {}
    return store


class TestQueryIntentIntegration:
    async def test_decision_query_biases_content_type(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        config = SessionConfig()
        await hybrid_search(
            query="what did we decide about Postgres",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            session_config=config,
        )
        # Decision content type should have been injected
        assert config.include_content_types is not None
        assert ContentType.DECISION in config.include_content_types

    async def test_existing_content_type_filter_preserved(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        config = SessionConfig(include_content_types=[ContentType.LEARNING])
        await hybrid_search(
            query="what did we decide about Postgres",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            session_config=config,
        )
        # Existing filter not overwritten
        assert config.include_content_types == [ContentType.LEARNING]

    async def test_clean_query_used_for_embedding_when_intent_detected(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        await hybrid_search(
            query="what did we decide about Qdrant",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            session_config=SessionConfig(),
        )
        called_with = mock_embedder.embed.await_args.args[0]
        assert "decide" not in called_with
        assert "qdrant" in called_with.lower()

    async def test_plain_query_passed_through_unchanged(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        await hybrid_search(
            query="Qdrant collection settings",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            session_config=SessionConfig(),
        )
        called_with = mock_embedder.embed.await_args.args[0]
        assert called_with == "Qdrant collection settings"


class TestSearchRobustness:
    async def test_empty_results_return_empty_list(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        result = await hybrid_search(
            query="anything",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
        )
        assert result == []

    async def test_no_results_graceful(self, mock_embedder, mock_vector_store, mock_metadata_store):
        result = await hybrid_search(
            query="nonexistent",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
        )
        assert isinstance(result, list)

    async def test_special_characters_in_query(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        result = await hybrid_search(
            query="'; DROP TABLE memories; --",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
        )
        assert isinstance(result, list)

    async def test_very_long_query(self, mock_embedder, mock_vector_store, mock_metadata_store):
        result = await hybrid_search(
            query="performance " * 200,
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
        )
        assert isinstance(result, list)

    async def test_unicode_query(self, mock_embedder, mock_vector_store, mock_metadata_store):
        result = await hybrid_search(
            query="ελληνικά 你好世界 🐍",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
        )
        assert isinstance(result, list)


class TestBatchLookupUsage:
    async def test_batch_lookup_called_once(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        # Provide some semantic results so scores dict is populated
        mock_vector_store.search.return_value = [
            {"id": "m1", "score": 0.9, "payload": {"content": "x"}},
            {"id": "m2", "score": 0.8, "payload": {"content": "y"}},
        ]
        mock_metadata_store.get_memories_batch.return_value = {
            "m1": _make_memory("x"),
            "m2": _make_memory("y"),
        }
        result = await hybrid_search(
            query="qdrant",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
        )
        assert mock_metadata_store.get_memories_batch.await_count == 1
        assert mock_metadata_store.get_memory.await_count == 0
        assert len(result) == 2


class TestParseHelpers:
    def test_parse_helper_returns_intent(self):
        intent = parse_query_intent("what did we decide")
        assert "decision" in intent.implied_content_types
