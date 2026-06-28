"""W2 recall-quality tests — relevance floor, normalization, content-type
weighting, feature boosts, raw_exchange exclusion, and the curated briefing.

All search tests use mocked embedder/vector/metadata stores so they run
offline and deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
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
from memgentic.processing.search_basic import basic_search
from memgentic.storage.backends.sqlite_vec import SqliteVecBackend
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

DIMS = 768


def _vec(seed: float = 0.1) -> list[float]:
    return [seed] * DIMS


def _make_memory(mid: str, content: str, ctype: ContentType) -> Memory:
    return Memory(
        id=mid,
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
    e.embed_query = e.embed
    e.embed_document = e.embed
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
    store.get_memories_batch.return_value = {}
    return store


# --- Normalization ---------------------------------------------------------


class TestNormalization:
    async def test_relevance_in_unit_range_and_preserves_order(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """Every result carries a relevance in [0,1]; top is 1.0; order kept."""
        mock_vector_store.search.return_value = [
            {"id": "m1", "score": 0.9, "payload": {"content": "a", "content_type": "fact"}},
            {"id": "m2", "score": 0.7, "payload": {"content": "b", "content_type": "fact"}},
            {"id": "m3", "score": 0.5, "payload": {"content": "c", "content_type": "fact"}},
        ]
        results = await hybrid_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )
        assert [r["id"] for r in results] == ["m1", "m2", "m3"]
        rels = [r["relevance"] for r in results]
        assert all(0.0 <= v <= 1.0 for v in rels)
        # Top normalises to 1.0; ordering strictly descending.
        assert rels[0] == 1.0
        assert rels[0] > rels[1] > rels[2]

    async def test_single_result_relevance_is_one(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """A lone candidate maps to 1.0 (never 0.0) so the floor can't drop it."""
        mock_vector_store.search.return_value = [
            {"id": "m1", "score": 0.42, "payload": {"content": "x", "content_type": "fact"}},
        ]
        results = await hybrid_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
            min_relevance=0.15,
        )
        assert len(results) == 1
        assert results[0]["relevance"] == 1.0


# --- Relevance floor -------------------------------------------------------


class TestRelevanceFloor:
    async def test_floor_drops_subthreshold_results(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """min_relevance trims candidates below the normalized floor, keeps top."""
        mock_vector_store.search.return_value = [
            {"id": "hi", "score": 0.95, "payload": {"content": "good", "content_type": "fact"}},
            {"id": "lo", "score": 0.10, "payload": {"content": "weak", "content_type": "fact"}},
        ]
        results = await hybrid_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
            min_relevance=0.5,
        )
        ids = [r["id"] for r in results]
        # 'lo' is the min → normalises to 0.0 → below floor → dropped.
        assert ids == ["hi"]

    async def test_zero_floor_keeps_all(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        mock_vector_store.search.return_value = [
            {"id": "hi", "score": 0.95, "payload": {"content": "good", "content_type": "fact"}},
            {"id": "lo", "score": 0.10, "payload": {"content": "weak", "content_type": "fact"}},
        ]
        results = await hybrid_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
            min_relevance=0.0,
        )
        assert {r["id"] for r in results} == {"hi", "lo"}


# --- Content-type weighting ------------------------------------------------


class TestContentTypeWeighting:
    async def test_raw_exchange_sinks_below_decision(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """A raw_exchange with a (slightly) higher cosine rank still sorts below
        a decision once the per-type weight (0.4 vs 1.0) is applied."""
        # raw_exchange at semantic rank 0 (higher raw RRF); decision at rank 1.
        mock_vector_store.search.return_value = [
            {
                "id": "raw",
                "score": 0.81,
                "payload": {"content": "chatter", "content_type": "raw_exchange"},
            },
            {
                "id": "dec",
                "score": 0.80,
                "payload": {"content": "we chose X", "content_type": "decision"},
            },
        ]
        # Authoritative content types come from the metadata batch lookup.
        mock_metadata_store.get_memories_batch.return_value = {
            "raw": _make_memory("raw", "chatter", ContentType.RAW_EXCHANGE),
            "dec": _make_memory("dec", "we chose X", ContentType.DECISION),
        }
        results = await hybrid_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )
        assert results[0]["id"] == "dec"
        assert results[1]["id"] == "raw"
        # Observability: the weights actually landed on the results.
        by_id = {r["id"]: r for r in results}
        assert by_id["raw"]["content_type_weight"] == 0.4
        assert by_id["dec"]["content_type_weight"] == 1.0


# --- Feature boosts --------------------------------------------------------


class TestFeatureBoost:
    async def test_proper_noun_match_is_lifted(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """A candidate mentioning a queried proper noun is boosted above a
        same-type candidate with a higher cosine rank but no mention."""
        mock_vector_store.search.return_value = [
            {
                "id": "plain",
                "score": 0.80,
                "payload": {"content": "generic note", "content_type": "fact"},
            },
            {
                "id": "named",
                "score": 0.79,
                "payload": {"content": "Maria approved the plan", "content_type": "fact"},
            },
        ]
        mock_metadata_store.get_memories_batch.return_value = {
            "plain": _make_memory("plain", "generic note", ContentType.FACT),
            "named": _make_memory("named", "Maria approved the plan", ContentType.FACT),
        }
        results = await hybrid_search(
            query="What did Maria decide",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
        )
        assert results[0]["id"] == "named"
        assert results[0]["boost_multiplier"] > 1.0

    async def test_boost_disabled_keeps_cosine_order(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        """With feature boost off, the proper-noun mention does not jump rank."""
        mock_vector_store.search.return_value = [
            {
                "id": "plain",
                "score": 0.80,
                "payload": {"content": "generic note", "content_type": "fact"},
            },
            {
                "id": "named",
                "score": 0.79,
                "payload": {"content": "Maria approved the plan", "content_type": "fact"},
            },
        ]
        mock_metadata_store.get_memories_batch.return_value = {
            "plain": _make_memory("plain", "generic note", ContentType.FACT),
            "named": _make_memory("named", "Maria approved the plan", ContentType.FACT),
        }
        results = await hybrid_search(
            query="What did Maria decide",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            graph=None,
            limit=10,
            enable_feature_boost=False,
        )
        assert results[0]["id"] == "plain"
        assert results[0]["boost_multiplier"] == 1.0


# --- basic_search floor ----------------------------------------------------


class TestBasicSearchFloor:
    async def test_cosine_floor_drops_low_similarity(
        self, mock_embedder, mock_vector_store, mock_metadata_store
    ):
        mock_vector_store.search.return_value = [
            {"id": "hi", "score": 0.42, "payload": {"content": "good"}},
            {"id": "lo", "score": 0.08, "payload": {"content": "noise"}},
        ]
        results = await basic_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
            min_relevance=0.15,
        )
        ids = [r["id"] for r in results]
        assert ids == ["hi"]
        assert results[0]["relevance"] == 0.42

    async def test_no_floor_keeps_all(self, mock_embedder, mock_vector_store, mock_metadata_store):
        mock_vector_store.search.return_value = [
            {"id": "hi", "score": 0.42, "payload": {"content": "good"}},
            {"id": "lo", "score": 0.08, "payload": {"content": "noise"}},
        ]
        results = await basic_search(
            query="topic",
            metadata_store=mock_metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )
        assert {r["id"] for r in results} == {"hi", "lo"}


# --- exclude_content_types in the filter layers ----------------------------


class TestExcludeContentTypeFilters:
    def test_metadata_fts_filter_excludes(self):
        store = MetadataStore(Path("unused.db"))
        cfg = SessionConfig(exclude_content_types=[ContentType.RAW_EXCHANGE])
        conditions, params = store._build_filter_conditions(cfg)
        assert any("content_type NOT IN" in c for c in conditions)
        assert "raw_exchange" in params

    def test_sqlite_vec_where_excludes(self):
        cfg = SessionConfig(exclude_content_types=[ContentType.RAW_EXCHANGE])
        where, params = SqliteVecBackend._build_sql_where(cfg)
        assert "p.content_type NOT IN" in where
        assert "raw_exchange" in params

    def test_qdrant_filter_excludes(self):
        cfg = SessionConfig(exclude_content_types=[ContentType.RAW_EXCHANGE])
        flt = VectorStore._build_filter(cfg)
        # Serialise to a string and assert the excluded value shows up under a
        # MatchExcept clause (qdrant models are nested; string check is robust).
        assert "raw_exchange" in str(flt)
        assert "except" in str(flt).lower()

    def test_no_exclude_when_unset(self):
        store = MetadataStore(Path("unused.db"))
        conditions, params = store._build_filter_conditions(SessionConfig())
        assert not any("NOT IN" in c for c in conditions)


# --- Curated SessionStart briefing -----------------------------------------


class TestBriefingCuration:
    async def test_briefing_requests_only_curated_types(self):
        from memgentic.processing.context_generator import (
            BRIEFING_CONTENT_TYPES,
            generate_briefing,
        )

        store = AsyncMock()
        store.get_memories_since.return_value = []
        store.get_top_memories.return_value = []

        await generate_briefing(store, hours=48, limit=5)

        store.get_memories_since.assert_awaited_once()
        cfg = store.get_memories_since.await_args.kwargs.get("session_config")
        assert cfg is not None
        assert cfg.include_content_types == BRIEFING_CONTENT_TYPES
        # raw_exchange / conversation_summary must NOT be in the curated set.
        assert ContentType.RAW_EXCHANGE not in cfg.include_content_types
        assert ContentType.CONVERSATION_SUMMARY not in cfg.include_content_types
