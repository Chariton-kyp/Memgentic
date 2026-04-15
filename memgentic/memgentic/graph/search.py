"""Hybrid search — combines semantic, keyword, and graph search."""

from __future__ import annotations

import asyncio
import math
import time as _t
from datetime import UTC, datetime

from memgentic.config import MemgenticSettings
from memgentic.graph.knowledge import KnowledgeGraph, RustKnowledgeGraph
from memgentic.models import ContentType, SessionConfig
from memgentic.observability import record_counter, record_histogram, trace_span
from memgentic.processing.embedder import Embedder
from memgentic.processing.query import parse_query_intent
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore


async def hybrid_search(
    query: str,
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    graph: KnowledgeGraph | RustKnowledgeGraph | None = None,
    session_config: SessionConfig | None = None,
    limit: int = 10,
    rrf_k: int = 60,
    settings: MemgenticSettings | None = None,
    user_id: str = "",
) -> list[dict]:
    """Merge results from semantic, keyword, and graph search using RRF.

    Combines three retrieval engines to maximise recall and precision:

    1. **Semantic search** (Qdrant): embeds the query and performs cosine
       similarity search over stored memory vectors.
    2. **Keyword search** (SQLite FTS5): full-text search on memory content,
       topics, and entities — catches exact-match terms that semantic search
       may miss.
    3. **Graph search** (NetworkX): performs BFS from query terms in the
       entity/topic co-occurrence graph to find related memory IDs.

    Scoring uses Reciprocal Rank Fusion (RRF): each engine contributes
    ``1 / (k + rank)`` per result, where *k* defaults to 60. RRF is
    rank-based, so it naturally handles different score scales across
    engines without calibration. After fusion, scores are weighted by
    memory importance and decayed by age (configurable half-life), then
    normalized to a 0-1 range.

    Args:
        query: The search query string.
        metadata_store: SQLite metadata store for keyword search and memory
            lookups.
        vector_store: Qdrant vector store for semantic search.
        embedder: Embedding model client to vectorize the query.
        graph: Optional knowledge graph for relationship-based boosting.
        session_config: Optional session-level source filters.
        limit: Maximum number of results to return.
        rrf_k: RRF smoothing constant (default 60). Higher values reduce
            the score gap between adjacent ranks.
        settings: Optional settings for temporal decay configuration.

    Returns:
        List of dicts, each with ``id``, ``score`` (0-1 normalized), and
        ``payload`` keys, sorted by descending score.
    """
    with trace_span("search.hybrid", query_len=len(query)):
        _search_start = _t.perf_counter()
        results = await _hybrid_search_impl(
            query=query,
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedder=embedder,
            graph=graph,
            session_config=session_config,
            limit=limit,
            rrf_k=rrf_k,
            settings=settings,
            user_id=user_id,
        )
        record_histogram(
            "memgentic.search.duration_seconds",
            _t.perf_counter() - _search_start,
        )
        record_counter("memgentic.search.results", value=len(results))
        return results


async def _hybrid_search_impl(
    query: str,
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    graph: KnowledgeGraph | RustKnowledgeGraph | None = None,
    session_config: SessionConfig | None = None,
    limit: int = 10,
    rrf_k: int = 60,
    settings: MemgenticSettings | None = None,
    user_id: str = "",
) -> list[dict]:
    # Detect query intent — extracts implicit filters and a cleaned query.
    # Only substitute the cleaned query when intent rewrote it; otherwise pass
    # the user's query through unchanged so existing call sites stay stable.
    intent = parse_query_intent(query)
    search_query = query
    if intent.implied_content_types or intent.time_filter_since:
        search_query = intent.clean_query or query

    # Merge implied content types into session config if not already set
    if intent.implied_content_types:
        if session_config is None:
            session_config = SessionConfig()
        if not session_config.include_content_types:
            valid: list[ContentType] = []
            for ct in intent.implied_content_types:
                try:
                    valid.append(ContentType(ct))
                except ValueError:
                    continue
            if valid:
                session_config.include_content_types = valid

    # Embed the cleaned query
    query_embedding = await embedder.embed(search_query)

    # Run semantic + keyword in parallel
    semantic_results, keyword_results = await asyncio.gather(
        vector_store.search(query_embedding, session_config, limit=limit * 2, user_id=user_id),
        metadata_store.search_fulltext(query, limit=limit * 2, user_id=user_id),
    )

    # Graph-boosted memory IDs
    graph_boosted_ids: set[str] = set()
    if graph and graph.node_count > 0:
        for term in query.lower().split():
            result = await graph.query_neighbors(term, depth=1)
            if not result.get("not_found"):
                for n in result.get("neighbors", []):
                    for mid in graph.get_node_memory_ids(n["name"]):
                        graph_boosted_ids.add(mid)

    # RRF scoring — each retrieval method contributes 1/(k + rank)
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    # Semantic results (already sorted by similarity)
    for rank, r in enumerate(semantic_results):
        mid = r["id"]
        scores[mid] = scores.get(mid, 0) + 1.0 / (rrf_k + rank + 1)
        payloads[mid] = r.get("payload", {})

    # Keyword results (already sorted by FTS5 relevance)
    for rank, mem in enumerate(keyword_results):
        mid = mem.id
        scores[mid] = scores.get(mid, 0) + 1.0 / (rrf_k + rank + 1)
        # Populate payload from keyword-only hits so we don't return empty
        # dicts for memories that the semantic search missed.
        if mid not in payloads:
            payloads[mid] = {
                "content": mem.content,
                "content_type": mem.content_type.value,
                "platform": mem.source.platform.value,
                "created_at": mem.created_at.isoformat() if mem.created_at else "",
                "topics": list(mem.topics or []),
                "session_title": mem.source.session_title or "",
            }

    # Graph-boosted (treated as rank-0 results)
    for mid in graph_boosted_ids:
        scores[mid] = scores.get(mid, 0) + 1.0 / (rrf_k + 1)

    # Apply importance_score weighting and temporal decay
    half_life = settings.memory_half_life_days if settings else 90
    now = datetime.now(UTC)
    all_mids = list(scores.keys())
    try:
        memories_map = await metadata_store.get_memories_batch(all_mids)
    except Exception:
        memories_map = {}
    if not isinstance(memories_map, dict):
        memories_map = {}
    for mid in all_mids:
        memory = memories_map.get(mid)
        if memory and hasattr(memory, "importance_score"):
            importance = memory.importance_score
            age_days = (now - memory.created_at).total_seconds() / 86400.0
            decay_factor = math.pow(0.5, age_days / half_life) if half_life > 0 else 1.0
            scores[mid] = scores[mid] * importance * decay_factor
            # Backfill payload for graph-only / missing IDs to avoid silent
            # data loss in returned results.
            if mid not in payloads or not payloads[mid]:
                payloads[mid] = {
                    "content": memory.content,
                    "content_type": memory.content_type.value,
                    "platform": memory.source.platform.value,
                    "created_at": memory.created_at.isoformat() if memory.created_at else "",
                    "topics": list(memory.topics or []),
                    "session_title": memory.source.session_title or "",
                }

    # Normalize to 0-1 range
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    max_score = ranked[0][1] if ranked else 1.0
    if max_score == 0:
        max_score = 1.0
    return [
        {"id": mid, "score": round(score / max_score, 4), "payload": payloads.get(mid, {})}
        for mid, score in ranked
    ]
