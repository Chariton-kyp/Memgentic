"""Tests for hybrid search (semantic + keyword + graph) with RRF scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from memgentic.graph.knowledge import create_knowledge_graph
from memgentic.graph.search import (
    DEFAULT_GRAPH_WEIGHT,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_SEMANTIC_WEIGHT,
    hybrid_search,
)
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)

DIMS = 768
RRF_K = 60  # default rrf_k


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


def _rrf_score(rank: int, k: int = RRF_K) -> float:
    """RRF contribution for a single retrieval method at given rank (0-based)."""
    return 1.0 / (k + rank + 1)


@pytest.fixture()
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_query = embedder.embed
    embedder.embed_document = embedder.embed
    return embedder


@pytest.fixture()
def mock_vector_store():
    store = AsyncMock()
    store.search.return_value = []
    return store


@pytest.fixture()
def mock_metadata_store():
    store = AsyncMock()
    store.search_fulltext.return_value = []
    store.get_memory.return_value = None  # No decay applied unless explicitly set
    return store


@pytest.fixture()
async def knowledge_graph(tmp_path):
    graph = create_knowledge_graph(tmp_path / "test_graph.json")
    await graph.load()
    return graph


# --- Tests ---


async def test_hybrid_search_semantic_only(mock_embedder, mock_vector_store, mock_metadata_store):
    """Hybrid search with only semantic results, no graph."""
    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 0.9, "payload": {"content": "semantic hit 1"}},
        {"id": "mem-2", "score": 0.7, "payload": {"content": "semantic hit 2"}},
    ]

    results = await hybrid_search(
        query="test query",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
    )

    assert len(results) == 2
    assert results[0]["id"] == "mem-1"
    assert results[1]["id"] == "mem-2"
    # Raw weighted RRF scores — semantic-only signal at semantic_weight × 1/(k+rank).
    assert results[0]["score"] == round(DEFAULT_SEMANTIC_WEIGHT * _rrf_score(0), 6)
    assert results[1]["score"] == round(DEFAULT_SEMANTIC_WEIGHT * _rrf_score(1), 6)
    # Per-signal observability — semantic-only path
    assert results[0]["semantic_rank"] == 1
    assert results[0]["keyword_rank"] is None
    assert results[0]["graph_boosted"] is False
    assert results[0]["search_method"] == "semantic"
    mock_embedder.embed.assert_awaited_once_with("test query")


async def test_hybrid_search_semantic_plus_keyword(
    mock_embedder, mock_vector_store, mock_metadata_store
):
    """Hybrid search combining semantic and keyword results, no graph."""
    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 0.9, "payload": {"content": "semantic result"}},
    ]
    mock_metadata_store.search_fulltext.return_value = [
        _make_memory("mem-1", "keyword+semantic overlap"),
        _make_memory("mem-2", "keyword only result"),
    ]

    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
    )

    assert len(results) == 2
    # mem-1 in both: semantic rank 0 + keyword rank 0 with weighted RRF
    assert results[0]["id"] == "mem-1"
    expected_mem1 = (
        DEFAULT_SEMANTIC_WEIGHT * _rrf_score(0)
        + DEFAULT_KEYWORD_WEIGHT * _rrf_score(0)
    )
    assert results[0]["score"] == round(expected_mem1, 6)
    assert results[0]["search_method"] == "hybrid"
    # mem-2 keyword rank 1 only — keyword-weighted contribution only
    assert results[1]["id"] == "mem-2"
    assert results[1]["score"] == round(DEFAULT_KEYWORD_WEIGHT * _rrf_score(1), 6)
    assert results[1]["search_method"] == "keyword"


async def test_hybrid_search_all_three(
    mock_embedder, mock_vector_store, mock_metadata_store, knowledge_graph
):
    """Hybrid search with semantic + keyword + graph boost."""
    # Add data to graph so the query term "python" finds neighbors
    await knowledge_graph.add_memory("mem-3", topics=["python"], entities=["Memgentic"])

    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 0.8, "payload": {"content": "semantic"}},
    ]
    mock_metadata_store.search_fulltext.return_value = [
        _make_memory("mem-2", "keyword result"),
    ]

    # Query "python" — graph has a node for "python" with memory "mem-3"
    results = await hybrid_search(
        query="python",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=knowledge_graph,
        limit=10,
    )

    result_ids = {r["id"] for r in results}
    assert "mem-1" in result_ids  # semantic
    assert "mem-2" in result_ids  # keyword
    assert "mem-3" in result_ids  # graph-boosted


async def test_hybrid_search_rrf_scoring(mock_embedder, mock_vector_store, mock_metadata_store):
    """Verify RRF scoring produces correct raw fused scores."""
    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 1.0, "payload": {}},
    ]
    mock_metadata_store.search_fulltext.return_value = [
        _make_memory("mem-2"),
    ]

    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
    )

    assert len(results) == 2
    # mem-1 (semantic-only rank 0) → semantic_weight × rrf(0)
    # mem-2 (keyword-only rank 0) → keyword_weight × rrf(0)
    # Semantic weight (0.6) > keyword weight (0.25) so mem-1 ranks first.
    sem_score = round(DEFAULT_SEMANTIC_WEIGHT * _rrf_score(0), 6)
    kw_score = round(DEFAULT_KEYWORD_WEIGHT * _rrf_score(0), 6)
    assert results[0]["id"] == "mem-1"
    assert results[0]["score"] == sem_score
    assert results[1]["id"] == "mem-2"
    assert results[1]["score"] == kw_score


async def test_hybrid_search_empty_results(mock_embedder, mock_vector_store, mock_metadata_store):
    """All sources return empty — result should be empty."""
    results = await hybrid_search(
        query="nonexistent topic",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
    )

    assert results == []


async def test_hybrid_search_limit_respected(mock_embedder, mock_vector_store, mock_metadata_store):
    """Limit parameter should cap the number of returned results."""
    mock_vector_store.search.return_value = [
        {"id": f"mem-{i}", "score": 1.0 - i * 0.1, "payload": {}} for i in range(10)
    ]

    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=3,
    )

    assert len(results) == 3


async def test_hybrid_search_graph_boost_score(
    mock_embedder, mock_vector_store, mock_metadata_store, knowledge_graph
):
    """Graph-boosted memories get rank-0 RRF score (raw 1/61) when alone."""
    # Add memory with two co-occurring topics so "testing" has a neighbor "pytest"
    # which carries the memory ID. The search queries "testing", finds neighbor "pytest",
    # and gets "mem-graph" from pytest's memory_ids.
    await knowledge_graph.add_memory("mem-graph", topics=["testing", "pytest"], entities=[])

    mock_vector_store.search.return_value = []
    mock_metadata_store.search_fulltext.return_value = []

    results = await hybrid_search(
        query="testing",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=knowledge_graph,
        limit=10,
    )

    assert len(results) == 1
    assert results[0]["id"] == "mem-graph"
    # Single graph-only result — graph_weight × rrf(0)
    assert results[0]["score"] == round(DEFAULT_GRAPH_WEIGHT * _rrf_score(0), 6)
    assert results[0]["search_method"] == "graph"
    assert results[0]["graph_boosted"] is True


async def test_hybrid_search_custom_weights(
    mock_embedder, mock_vector_store, mock_metadata_store
):
    """Caller-supplied weights override the per-signal RRF defaults."""
    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 0.9, "payload": {}},
    ]
    mock_metadata_store.search_fulltext.return_value = [_make_memory("mem-2")]

    # Invert the defaults: weight keyword above semantic to confirm the
    # weights actually flow through to the fused score.
    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
        semantic_weight=0.1,
        keyword_weight=0.9,
        graph_weight=0.0,
    )

    assert len(results) == 2
    # mem-2 (keyword rank 1) at weight 0.9 must outrank mem-1 (semantic rank 1) at 0.1
    assert results[0]["id"] == "mem-2"
    assert results[1]["id"] == "mem-1"


async def test_hybrid_search_min_score_filters_low_relevance(
    mock_embedder, mock_vector_store, mock_metadata_store
):
    """min_score drops fused-score < threshold (no-match cutoff)."""
    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 0.9, "payload": {}},
    ]
    mock_metadata_store.search_fulltext.return_value = []

    # Default semantic_weight=0.6, rank 0 → score = 0.6/61 ≈ 0.00984.
    # A min_score above that should drop the only candidate.
    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
        min_score=0.05,
    )
    assert results == []

    # Setting it below the actual score keeps the candidate.
    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
        min_score=0.001,
    )
    assert len(results) == 1
    assert results[0]["id"] == "mem-1"


async def test_hybrid_search_observability_fields_present(
    mock_embedder, mock_vector_store, mock_metadata_store
):
    """Every result carries semantic_rank/keyword_rank/graph_boosted/search_method."""
    mock_vector_store.search.return_value = [
        {"id": "mem-1", "score": 0.9, "payload": {}},
    ]
    mock_metadata_store.search_fulltext.return_value = [_make_memory("mem-1")]

    results = await hybrid_search(
        query="test",
        metadata_store=mock_metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        graph=None,
        limit=10,
    )

    assert len(results) == 1
    r = results[0]
    # mem-1 in semantic rank 1 + keyword rank 1 → "hybrid" label, both ranks set
    assert r["semantic_rank"] == 1
    assert r["keyword_rank"] == 1
    assert r["graph_boosted"] is False
    assert r["search_method"] == "hybrid"
