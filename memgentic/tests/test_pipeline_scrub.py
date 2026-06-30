"""Phase 0 security regression: chunk content fed to the LLM intelligence graph
must be credential-scrubbed.

Bug: ``scrub_text`` mutates ``memory.content`` (pipeline.py:333-335) but the
intelligence ``intel_state`` is built from the UNSCRUBBED ``chunk.content``
(pipeline.py:371). With ``GOOGLE_API_KEY`` set, raw secrets reach cloud Gemini.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import ContentType, ConversationChunk, Platform
from memgentic.processing import pipeline as pmod
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore

DIMS = 768


def _emb(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


async def test_chunks_scrubbed_before_intelligence_graph(tmp_path, monkeypatch):
    captured: dict = {}

    class _FakeGraph:
        async def ainvoke(self, state):
            captured["contents"] = [c["content"] for c in state["chunks"]]
            return {
                "classified_chunks": [],
                "all_topics": [],
                "all_entities": [],
                "summary": "",
            }

    monkeypatch.setattr(pmod, "build_intelligence_graph", lambda **_: _FakeGraph())
    monkeypatch.setattr(pmod, "HAS_INTELLIGENCE", True)

    settings = MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=DIMS,
        enable_credential_scrubbing=True,
    )
    ms = MetadataStore(settings.sqlite_path)
    await ms.initialize()

    embedder = AsyncMock()
    embedder.embed_batch.side_effect = lambda texts: [_emb(0.1 * i) for i in range(len(texts))]
    embedder.embed_batch_documents = embedder.embed_batch
    vector_store = AsyncMock()

    class _LLM:
        available = True

    pipe = IngestionPipeline(
        settings=settings,
        metadata_store=ms,
        vector_store=vector_store,
        embedder=embedder,
        llm_client=_LLM(),
    )

    secret = "AKIAIOSFODNN7EXAMPLE"
    chunks = [
        ConversationChunk(
            content=f"Human: deploy with AWS key {secret} now please",
            content_type=ContentType.FACT,
        )
    ]
    await pipe.ingest_conversation(chunks=chunks, platform=Platform.CLAUDE_CODE, session_id="s1")

    assert "contents" in captured, "intelligence graph was not invoked"
    assert all(secret not in c for c in captured["contents"]), (
        f"raw secret reached the LLM intelligence graph: {captured['contents']}"
    )
