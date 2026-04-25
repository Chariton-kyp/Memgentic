"""Retrieval primitives — fusion, reranking, hybrid search.

This package will host the Plan 12 cascade orchestrator and its sub-
strategies (Layer S/P direct, dense, BM25, graph PPR, reranker). PR-E
adds the reranker interface + a llama-cpp-based Qwen3-Reranker
implementation. PR-D (separate branch) adds RRF/weighted-score fusion
and will conflict on this file at merge time — resolve by combining
both ``__all__`` lists.
"""

from memgentic.retrieval.reranker import (
    LlamaCppReranker,
    MockReranker,
    RerankCandidate,
    Reranker,
    RerankResult,
)

__all__ = [
    "LlamaCppReranker",
    "MockReranker",
    "RerankCandidate",
    "Reranker",
    "RerankResult",
]
