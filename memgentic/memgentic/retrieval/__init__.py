"""Retrieval primitives — fusion, reranking, hybrid search.

This package hosts the cascade orchestrator and its sub-strategies
(direct lookup, dense vector, BM25/FTS5, graph PPR, reranker).

Design notes:
- Each candidate strategy returns ``(memory_id, score)`` lists.
- Fusion combines them at memory granularity. Session aggregation is
  a separate concern (``benchmarks/lib/scorers.py``) and runs after
  fusion when the benchmark requires it.
- The reranker re-scores top-N candidates with a cross-encoder for
  fine-grained matches the bi-encoder embedder cannot catch.
- All fusion functions here are pure — no I/O, no DB access — so they
  can be unit-tested without an Ollama server or sqlite-vec disk.
  Reranker implementations may be heavy (load GGUFs) and gate
  themselves with a Protocol so tests use ``MockReranker``.
"""

from memgentic.retrieval.hybrid import (
    reciprocal_rank_fusion,
    weighted_score_fusion,
)
from memgentic.retrieval.reranker import (
    LlamaCppReranker,
    MockReranker,
    RerankCandidate,
    Reranker,
    RerankResult,
)

__all__ = [
    "reciprocal_rank_fusion",
    "weighted_score_fusion",
    "LlamaCppReranker",
    "MockReranker",
    "RerankCandidate",
    "Reranker",
    "RerankResult",
]
