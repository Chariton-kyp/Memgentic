"""Basic search — vector-only semantic search without hybrid RRF fusion.

Used when intelligence extras are not installed. Provides semantic search
via Qdrant without keyword or graph-based boosting.
"""

from __future__ import annotations

import structlog

from memgentic.config import MemgenticSettings
from memgentic.models import SessionConfig
from memgentic.processing.embedder import Embedder
from memgentic.retrieval.reranker import Reranker, maybe_rerank
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

logger = structlog.get_logger()


async def basic_search(
    query: str,
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    session_config: SessionConfig | None = None,
    limit: int = 10,
    user_id: str = "",
    *,
    min_relevance: float = 0.0,
    settings: MemgenticSettings | None = None,
    reranker: Reranker | None = None,
) -> list[dict]:
    """Search memories using vector similarity only.

    This is the fallback search used when intelligence extras are not installed.
    It provides semantic search via Qdrant without keyword (FTS5) or
    knowledge graph boosting.

    Args:
        min_relevance: drop results whose cosine similarity is below this
            floor. Default 0.0 = no filter. The MCP recall tool passes
            ``settings.recall_min_relevance`` (≈0.15) so clearly off-topic
            hits are trimmed. Cosine from normalised embeddings already lives
            in ~[0, 1], so no separate normalisation is needed here.
        settings: optional settings; required for reranking config.
        reranker: optional cross-encoder reranker. When supplied AND
            ``settings.enable_reranker`` is set, the top ``reranker_top_k``
            candidates are re-scored, reordered by the absolute rerank score
            (written back as ``relevance``), and any below
            ``reranker_min_score`` are dropped. A ``None`` reranker or an
            unreachable server is a graceful no-op (cosine order preserved).

    Returns:
        List of dicts with ``id``, ``score``, ``relevance``, and ``payload``
        keys, sorted by descending similarity. ``score`` is the raw cosine
        similarity from the vector backend (range roughly [-1, 1] for
        normalised embeddings). ``relevance`` mirrors the cosine so the field
        name is consistent with hybrid search for the display layer.
    """
    query_embedding = await embedder.embed_query(query)

    # When reranking is active, pull a wider candidate pool (≥ reranker_top_k)
    # so the cross-encoder can reorder beyond the first ``limit`` cosine hits;
    # ``maybe_rerank`` truncates back to ``limit``.
    do_rerank = bool(reranker is not None and settings is not None and settings.enable_reranker)
    fetch_limit = (
        max(limit, settings.reranker_top_k) if (do_rerank and settings is not None) else limit
    )
    results = await vector_store.search(
        query_embedding, session_config, limit=fetch_limit, user_id=user_id
    )

    if not results:
        return []

    out: list[dict] = []
    for r in results:
        score = round(float(r.get("score", 0.0)), 4)
        if min_relevance > 0.0 and score < min_relevance:
            continue
        out.append(
            {
                "id": r["id"],
                "score": score,
                "relevance": score,
                "payload": r.get("payload", {}),
            }
        )

    # Optional absolute relevance gate — graceful no-op when off/unreachable.
    out = await maybe_rerank(query, out, reranker=reranker, settings=settings, limit=limit)
    return out
