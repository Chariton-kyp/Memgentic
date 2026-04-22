"""Semantic dedup layer for the Watchers pipeline.

Every Watcher (hooks, file watchers, MCP, imports) calls
:class:`SemanticDeduper` before handing chunks to the ingestion pipeline.
The deduper embeds the incoming chunk and asks the vector store for its
nearest neighbour in the same (platform, session) scope; when cosine
similarity crosses ``threshold`` (default 0.92), the chunk is dropped as a
near-duplicate without burning an LLM call.

This is the Memgentic advantage over subagent-style dedup: zero LLM cost
per dedup decision, one vector lookup instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import sqrt

import structlog

from memgentic.models import ConversationChunk, Platform, SessionConfig
from memgentic.processing.embedder import Embedder
from memgentic.storage.vectors import VectorStore

logger = structlog.get_logger()

# Sensible defaults chosen for the Watchers pipeline:
#   0.99 -> near-exact resend (e.g. hook fires twice for the same turn)
#   0.92 -> near-duplicate paraphrase in the same session
DEFAULT_SKIP_THRESHOLD = 0.92
EXACT_RESEND_THRESHOLD = 0.99


@dataclass(frozen=True)
class DedupDecision:
    """Outcome for a single chunk."""

    chunk: ConversationChunk
    skip: bool
    score: float
    matched_memory_id: str | None = None
    reason: str = ""


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    """Compute cosine similarity between two vectors.

    Kept independent of numpy so the daemon doesn't pick up a heavyweight
    dependency; the embedding dimension (768) is small enough that Python
    arithmetic is fast enough.
    """
    a_list = list(a)
    b_list = list(b)
    if not a_list or not b_list or len(a_list) != len(b_list):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a_list, b_list, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    denom = sqrt(na) * sqrt(nb)
    if denom == 0:
        return 0.0
    return dot / denom


class SemanticDeduper:
    """Drop incoming chunks that are too similar to something already stored.

    The deduper is *scoped* — it only treats vectors from the **same
    (platform, session_id)** as candidates. Cross-session dedup is handled
    later by the ingestion pipeline's own ``enable_write_time_dedup`` flag;
    here we want to catch the specific case where a hook or watcher fires
    twice for the same conversation turn.
    """

    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        *,
        threshold: float = DEFAULT_SKIP_THRESHOLD,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._threshold = threshold

    async def filter_chunks(
        self,
        chunks: list[ConversationChunk],
        *,
        platform: Platform,
        session_id: str | None,
    ) -> tuple[list[ConversationChunk], list[DedupDecision]]:
        """Return ``(kept, decisions)`` — kept is a subset of ``chunks``.

        ``decisions`` has one entry per input chunk in input order, so callers
        can emit structured logs / metrics for skipped chunks.
        """
        if not chunks:
            return [], []

        decisions: list[DedupDecision] = []
        kept: list[ConversationChunk] = []

        session_config = SessionConfig(include_sources=[platform]) if session_id else None

        for chunk in chunks:
            decision = await self._decide_single(chunk, platform, session_id, session_config)
            decisions.append(decision)
            if not decision.skip:
                kept.append(chunk)
            else:
                logger.info(
                    "watchers.dedup_skipped",
                    platform=platform.value,
                    session_id=session_id,
                    score=round(decision.score, 4),
                    matched=decision.matched_memory_id,
                )

        return kept, decisions

    async def _decide_single(
        self,
        chunk: ConversationChunk,
        platform: Platform,
        session_id: str | None,
        session_config: SessionConfig | None,
    ) -> DedupDecision:
        """Decide whether a single chunk is a near-duplicate."""
        try:
            embedding = await self._embedder.embed(chunk.content)
        except Exception as exc:  # embedding failure is non-fatal for dedup
            logger.warning("watchers.dedup_embed_failed", error=str(exc))
            return DedupDecision(
                chunk=chunk,
                skip=False,
                score=0.0,
                reason="embed_failed",
            )

        try:
            hits = await self._vector_store.search(
                query_embedding=embedding,
                session_config=session_config,
                limit=1,
            )
        except Exception as exc:
            logger.warning("watchers.dedup_search_failed", error=str(exc))
            return DedupDecision(
                chunk=chunk,
                skip=False,
                score=0.0,
                reason="search_failed",
            )

        if not hits:
            return DedupDecision(chunk=chunk, skip=False, score=0.0, reason="no_match")

        top = hits[0]
        score = float(top.get("score") or 0.0)

        # Only count same-session matches as dedup candidates. The underlying
        # vector store may return cross-session hits when the filter is
        # ambiguous; we double-check the payload here.
        payload = top.get("payload") or {}
        hit_session = payload.get("source_metadata", {}).get("session_id")
        if session_id and hit_session and hit_session != session_id:
            return DedupDecision(chunk=chunk, skip=False, score=score, reason="different_session")

        if score >= self._threshold:
            return DedupDecision(
                chunk=chunk,
                skip=True,
                score=score,
                matched_memory_id=str(top.get("id") or ""),
                reason="near_duplicate",
            )

        return DedupDecision(chunk=chunk, skip=False, score=score, reason="below_threshold")


__all__ = [
    "DedupDecision",
    "DEFAULT_SKIP_THRESHOLD",
    "EXACT_RESEND_THRESHOLD",
    "SemanticDeduper",
    "_cosine",
]
