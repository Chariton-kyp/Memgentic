# ADR-004: Hybrid Search Design — Semantic + Keyword + Graph with RRF

## Status

Accepted (2026-03-20)

## Context

Pure semantic search misses exact keyword matches (e.g., searching for "Qdrant" may return results about "vector databases" but miss documents that literally mention "Qdrant" without semantic overlap). Pure keyword search misses conceptual similarity. Neither captures relationship context (e.g., that "FastAPI" and "Pydantic" frequently co-occur in the same conversations).

Memgentic needs a search strategy that combines all three signals without requiring careful weight tuning.

## Decision

Use a **three-engine hybrid search** with **Reciprocal Rank Fusion (RRF)** scoring:

1. **Semantic search (Qdrant)**: Embedding similarity via cosine distance. Captures conceptual matches.
2. **Keyword search (SQLite FTS5)**: Full-text search on content, topics, and entities. Captures exact term matches.
3. **Graph search (NetworkX)**: Entity/topic co-occurrence graph. BFS from query terms to find related memory IDs. Captures relationship context.

**RRF formula**: Each engine contributes `1 / (k + rank)` per result (k=60 by default). Scores are summed across engines and normalized to 0-1 range. RRF is rank-based, so it naturally handles different score scales across engines without calibration.

Additional scoring factors: importance score weighting and temporal decay (half-life of 90 days) are applied after RRF fusion.

## Consequences

- **Positive**: Robust retrieval that handles keyword, conceptual, and relational queries. RRF requires no weight tuning. Each engine runs independently, enabling parallel execution.
- **Negative**: Three search calls per query add latency (mitigated by `asyncio.gather`). Graph search quality depends on graph density. RRF parameter k=60 is a reasonable default but not tuned per-domain.
- **Mitigated**: Semantic and keyword searches run in parallel. Graph search is O(nodes) at depth 1. The k parameter is configurable.
