"""Basic search — vector-only semantic search without hybrid RRF fusion.

Used when intelligence extras are not installed. Provides semantic search
via Qdrant without keyword or graph-based boosting.
"""

from __future__ import annotations

import structlog

from memgentic.models import SessionConfig
from memgentic.processing.embedder import Embedder
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
) -> list[dict]:
    """Search memories using vector similarity only.

    This is the fallback search used when intelligence extras are not installed.
    It provides semantic search via Qdrant without keyword (FTS5) or
    knowledge graph boosting.

    Returns:
        List of dicts with ``id``, ``score``, and ``payload`` keys,
        sorted by descending similarity. ``score`` is the raw cosine
        similarity from the vector backend (range roughly [-1, 1] for
        normalised embeddings); callers MUST NOT assume a [0, 1] scale.
    """
    query_embedding = await embedder.embed_query(query)
    results = await vector_store.search(
        query_embedding, session_config, limit=limit, user_id=user_id
    )

    if not results:
        return []

    return [
        {
            "id": r["id"],
            "score": round(float(r.get("score", 0.0)), 4),
            "payload": r.get("payload", {}),
        }
        for r in results
    ]
