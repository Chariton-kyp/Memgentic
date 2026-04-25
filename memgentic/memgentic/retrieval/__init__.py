"""Retrieval primitives — fusion, reranking, hybrid search.

This package hosts the Plan 12 cascade orchestrator and its sub-
strategies (Layer S/P direct, dense, BM25, graph PPR, reranker).

PR-D adds reciprocal rank fusion (combine dense vector + BM25/FTS5).
PR-E adds the cross-encoder reranker interface + a llama-cpp-based
Qwen3-Reranker implementation.

Design notes (Plan 12 §7 / §3.2 cascade Stage 1+2):
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
    # PR-D: fusion primitives
    "reciprocal_rank_fusion",
    "weighted_score_fusion",
    # PR-E: reranker interface + implementations
    "LlamaCppReranker",
    "MockReranker",
    "RerankCandidate",
    "Reranker",
    "RerankResult",
]
