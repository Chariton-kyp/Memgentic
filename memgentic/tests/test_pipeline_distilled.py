"""Pipeline populates Memory.distilled from grounded distillation facts.

The enriched ingest already distills atomic facts; we persist them on
``Memory.distilled`` when (and only when) they are lexically grounded in the
verbatim source. Hallucinated or empty distillations leave ``distilled`` None.
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


async def _ingest_with_distillation(tmp_path, monkeypatch, *, chunk_text, facts):
    """Ingest one chunk through a fake intelligence graph that returns ``facts``.

    Returns the list of stored memories so the caller can assert on .distilled.
    """

    class _FakeGraph:
        async def ainvoke(self, state):
            return {
                "classified_chunks": [
                    {
                        "content_type": "fact",
                        "confidence": 0.9,
                        "distillation": {
                            "facts": facts,
                            "is_valuable": True,
                            "value_score": 0.9,
                        },
                    }
                ],
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

    chunks = [ConversationChunk(content=chunk_text, content_type=ContentType.FACT)]
    return await pipe.ingest_conversation(
        chunks=chunks, platform=Platform.CLAUDE_CODE, session_id="s1"
    )


async def test_grounded_distillation_populates_distilled(tmp_path, monkeypatch):
    memories = await _ingest_with_distillation(
        tmp_path,
        monkeypatch,
        chunk_text="Human: We deployed v2 to production at 14:00 UTC after testing.",
        facts=["Deployed v2 to production at 14:00 UTC."],
    )
    assert len(memories) == 1
    assert memories[0].distilled == "Deployed v2 to production at 14:00 UTC."


async def test_hallucinated_distillation_leaves_distilled_none(tmp_path, monkeypatch):
    memories = await _ingest_with_distillation(
        tmp_path,
        monkeypatch,
        chunk_text="Human: We deployed v2 to production today.",
        facts=["The capital of France is Paris and the moon is made of cheese."],
    )
    assert len(memories) == 1
    assert memories[0].distilled is None


async def test_empty_distillation_leaves_distilled_none(tmp_path, monkeypatch):
    memories = await _ingest_with_distillation(
        tmp_path,
        monkeypatch,
        chunk_text="Human: We deployed v2 to production today.",
        facts=[],
    )
    assert len(memories) == 1
    assert memories[0].distilled is None
