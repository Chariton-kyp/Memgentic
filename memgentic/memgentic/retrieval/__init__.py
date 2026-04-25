"""Retrieval primitives — fusion, reranking, hybrid search.

This package will host the Plan 12 cascade orchestrator and its sub-
strategies (Layer S/P direct, dense, BM25, graph PPR, reranker). PR-D
adds the first piece: reciprocal rank fusion, used to combine dense
vector hits with BM25/FTS5 hits into a single hybrid ranking.

Design notes (Plan 12 §7 PR-D / §3.2 cascade Stage 1+2):
- Each candidate strategy returns ``(memory_id, score)`` lists.
- Fusion combines them at memory granularity. Session aggregation is
  a separate concern (``benchmarks/lib/scorers.py``) and runs after
  fusion when the benchmark requires it.
- All functions here are pure — no I/O, no DB access — so they can be
  unit-tested without an Ollama server or sqlite-vec disk.
"""

from memgentic.retrieval.hybrid import (
    reciprocal_rank_fusion,
    weighted_score_fusion,
)

__all__ = [
    "reciprocal_rank_fusion",
    "weighted_score_fusion",
]
