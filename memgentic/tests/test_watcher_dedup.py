"""Tests for the Watchers semantic dedup layer.

We stub the embedder and vector store so the threshold logic can be
exercised without Ollama or Qdrant, matching the test style of
``test_metadata_store.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from memgentic.daemon.dedup import (
    DEFAULT_SKIP_THRESHOLD,
    EXACT_RESEND_THRESHOLD,
    SemanticDeduper,
    _cosine,
)
from memgentic.models import ContentType, ConversationChunk, Platform


@dataclass
class _StubEmbedder:
    embedding: list[float]

    async def embed(self, text: str) -> list[float]:  # noqa: D401
        return list(self.embedding)


@dataclass
class _StubVectorStore:
    hits: list[dict]
    captured_filters: list[Any] | None = None

    async def search(
        self, query_embedding, session_config=None, limit: int = 10, user_id: str = ""
    ):
        if self.captured_filters is None:
            self.captured_filters = []
        self.captured_filters.append(session_config)
        return list(self.hits)


def _chunk(text: str = "hello world") -> ConversationChunk:
    return ConversationChunk(
        content=text,
        content_type=ContentType.RAW_EXCHANGE,
        topics=[],
        entities=[],
        confidence=1.0,
    )


def test_cosine_exact() -> None:
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert _cosine(a, b) == pytest.approx(1.0)


def test_cosine_orthogonal() -> None:
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_handles_degenerate() -> None:
    assert _cosine([], [1, 2]) == 0.0
    assert _cosine([0, 0], [0, 0]) == 0.0


@pytest.mark.asyncio
async def test_skips_near_duplicate_same_session() -> None:
    embedder = _StubEmbedder([1.0, 0.0])
    store = _StubVectorStore(
        hits=[
            {
                "id": "mem-1",
                "score": 0.95,
                "payload": {"source_metadata": {"session_id": "sess-1"}},
            }
        ]
    )
    deduper = SemanticDeduper(embedder, store, threshold=DEFAULT_SKIP_THRESHOLD)  # type: ignore[arg-type]
    kept, decisions = await deduper.filter_chunks(
        [_chunk()],
        platform=Platform.GEMINI_CLI,
        session_id="sess-1",
    )
    assert kept == []
    assert decisions[0].skip is True
    assert decisions[0].score == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_keeps_different_session_hit() -> None:
    embedder = _StubEmbedder([1.0, 0.0])
    store = _StubVectorStore(
        hits=[
            {
                "id": "mem-x",
                "score": 0.99,
                "payload": {"source_metadata": {"session_id": "other"}},
            }
        ]
    )
    deduper = SemanticDeduper(embedder, store)  # type: ignore[arg-type]
    kept, _ = await deduper.filter_chunks(
        [_chunk()],
        platform=Platform.CLAUDE_CODE,
        session_id="mine",
    )
    assert len(kept) == 1


@pytest.mark.asyncio
async def test_keeps_below_threshold() -> None:
    embedder = _StubEmbedder([1.0, 0.0])
    store = _StubVectorStore(
        hits=[
            {
                "id": "m",
                "score": 0.5,
                "payload": {"source_metadata": {"session_id": "s"}},
            }
        ]
    )
    deduper = SemanticDeduper(embedder, store)  # type: ignore[arg-type]
    kept, decisions = await deduper.filter_chunks(
        [_chunk()],
        platform=Platform.GEMINI_CLI,
        session_id="s",
    )
    assert len(kept) == 1
    assert decisions[0].skip is False


@pytest.mark.asyncio
async def test_empty_input_is_noop() -> None:
    embedder = _StubEmbedder([1.0])
    store = _StubVectorStore(hits=[])
    deduper = SemanticDeduper(embedder, store)  # type: ignore[arg-type]
    kept, decisions = await deduper.filter_chunks([], platform=Platform.GEMINI_CLI, session_id=None)
    assert kept == []
    assert decisions == []


@pytest.mark.asyncio
async def test_exact_resend_threshold_value() -> None:
    # Sanity: the "exact resend" constant stays >= the skip threshold.
    assert EXACT_RESEND_THRESHOLD >= DEFAULT_SKIP_THRESHOLD
