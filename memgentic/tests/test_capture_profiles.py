"""Tests for the capture profile feature (raw / enriched / dual).

Covers:
    - Migration 8 applies cleanly and makes the new columns queryable.
    - Pipeline ``raw`` profile never invokes LLM intelligence and produces
      rows with the neutral importance + empty topics/entities contract.
    - Pipeline ``enriched`` profile (default) preserves the pre-refactor
      behaviour for regression safety.
    - Pipeline ``dual`` profile writes paired rows with cross-referenced
      ``dual_sibling_id`` on both sides.
    - ``ingest_single`` honours the profile choice for single writes.
    - Runtime settings persistence (set/get) via ``MetadataStore``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import ContentType, ConversationChunk, Platform
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore

DIMS = 768


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


@pytest.fixture()
def profile_settings(tmp_path) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=DIMS,
        enable_write_time_dedup=False,
    )


@pytest.fixture()
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_batch.side_effect = lambda texts: [
        _fake_embedding(0.1 * i) for i in range(len(texts))
    ]
    return embedder


@pytest.fixture()
def mock_vector_store():
    vs = AsyncMock()
    vs.upsert_memory = AsyncMock()
    vs.upsert_memories_batch = AsyncMock()
    return vs


@pytest.fixture()
def sentinel_llm_client():
    """An LLM client that would explode if anyone tried to use it.

    Used to verify that ``raw`` ingestion never touches the intelligence
    pipeline — if the code forgets the guard and accesses ``.available`` or
    dispatches a LangGraph call, the test will fail loudly.
    """

    class _Sentinel:
        @property
        def available(self) -> bool:  # pragma: no cover - defensive
            raise AssertionError("raw profile must not check LLM availability")

    return _Sentinel()


@pytest.fixture()
async def raw_pipeline(
    profile_settings: MemgenticSettings,
    metadata_store: MetadataStore,
    mock_embedder,
    mock_vector_store,
    sentinel_llm_client,
):
    return IngestionPipeline(
        settings=profile_settings,
        metadata_store=metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
        llm_client=sentinel_llm_client,
    )


@pytest.fixture()
async def dual_pipeline(
    profile_settings: MemgenticSettings,
    metadata_store: MetadataStore,
    mock_embedder,
    mock_vector_store,
):
    # No LLM client — dual path still works; enriched step is just a no-LLM pass.
    return IngestionPipeline(
        settings=profile_settings,
        metadata_store=metadata_store,
        vector_store=mock_vector_store,
        embedder=mock_embedder,
    )


@pytest.fixture()
def chunks_for_profile_tests() -> list[ConversationChunk]:
    return [
        ConversationChunk(
            content="We chose Qdrant because of its local file mode for offline dev.",
            content_type=ContentType.DECISION,
            topics=["qdrant", "architecture"],
            entities=["Memgentic"],
            confidence=0.9,
        ),
        ConversationChunk(
            content="Embeddings are generated via Qwen3-Embedding-0.6B with 768d MRL.",
            content_type=ContentType.FACT,
            topics=["embeddings", "qwen3"],
            entities=["Ollama"],
            confidence=0.95,
        ),
    ]


class TestMigration008:
    async def test_new_columns_are_queryable(self, metadata_store: MetadataStore):
        """Migration 8 must expose ``capture_profile``/``dual_sibling_id``."""
        assert metadata_store._db is not None
        cursor = await metadata_store._db.execute("PRAGMA table_info(memories)")
        columns = {row["name"] for row in await cursor.fetchall()}
        assert "capture_profile" in columns
        assert "dual_sibling_id" in columns

    async def test_existing_memory_defaults_to_enriched(
        self,
        metadata_store: MetadataStore,
        sample_memory,
    ):
        await metadata_store.save_memory(sample_memory)
        got = await metadata_store.get_memory(sample_memory.id)
        assert got is not None
        # Model default is 'enriched'; migration default mirrors that.
        assert got.capture_profile == "enriched"
        assert got.dual_sibling_id is None

    async def test_runtime_settings_kv_roundtrip(self, metadata_store: MetadataStore):
        assert await metadata_store.get_runtime_setting("default_capture_profile") is None
        await metadata_store.set_runtime_setting("default_capture_profile", "raw")
        assert await metadata_store.get_runtime_setting("default_capture_profile") == "raw"


class TestRawProfile:
    async def test_raw_skips_llm_and_sets_neutral_importance(
        self,
        raw_pipeline: IngestionPipeline,
        chunks_for_profile_tests: list[ConversationChunk],
        metadata_store: MetadataStore,
    ):
        memories = await raw_pipeline.ingest_conversation(
            chunks=chunks_for_profile_tests,
            platform=Platform.CLAUDE_CODE,
            capture_profile="raw",
        )

        assert len(memories) == 2
        for mem in memories:
            assert mem.capture_profile == "raw"
            assert mem.topics == []
            assert mem.entities == []
            assert mem.importance_score == 0.5
            # Stored verbatim
            stored = await metadata_store.get_memory(mem.id)
            assert stored is not None
            assert stored.capture_profile == "raw"
            assert stored.content == mem.content

    async def test_raw_single_ingest_strips_topics(
        self,
        raw_pipeline: IngestionPipeline,
        metadata_store: MetadataStore,
    ):
        memory = await raw_pipeline.ingest_single(
            content="Verbatim fact without enrichment",
            content_type=ContentType.FACT,
            platform=Platform.CLAUDE_CODE,
            topics=["should-be-dropped"],
            entities=["also-dropped"],
            capture_profile="raw",
        )
        assert memory.capture_profile == "raw"
        assert memory.topics == []
        assert memory.entities == []
        assert memory.importance_score == 0.5
        stored = await metadata_store.get_memory(memory.id)
        assert stored is not None
        assert stored.topics == []


class TestEnrichedProfile:
    async def test_enriched_preserves_existing_behaviour(
        self,
        dual_pipeline: IngestionPipeline,
        chunks_for_profile_tests: list[ConversationChunk],
        metadata_store: MetadataStore,
    ):
        memories = await dual_pipeline.ingest_conversation(
            chunks=chunks_for_profile_tests,
            platform=Platform.CLAUDE_CODE,
            capture_profile="enriched",
        )
        assert len(memories) == 2
        for mem in memories:
            assert mem.capture_profile == "enriched"
        # Without an LLM client the topics flow straight from the chunk — the
        # pre-refactor default behaviour we must not regress.
        assert memories[0].topics == ["qdrant", "architecture"]

    async def test_default_from_config_respected(
        self,
        profile_settings: MemgenticSettings,
        metadata_store: MetadataStore,
        mock_embedder,
        mock_vector_store,
        chunks_for_profile_tests: list[ConversationChunk],
    ):
        profile_settings.default_capture_profile = "raw"
        pipeline = IngestionPipeline(
            settings=profile_settings,
            metadata_store=metadata_store,
            vector_store=mock_vector_store,
            embedder=mock_embedder,
        )
        memories = await pipeline.ingest_conversation(
            chunks=chunks_for_profile_tests,
            platform=Platform.CLAUDE_CODE,
        )
        assert all(m.capture_profile == "raw" for m in memories)


class TestDualProfile:
    async def test_dual_writes_paired_siblings(
        self,
        dual_pipeline: IngestionPipeline,
        chunks_for_profile_tests: list[ConversationChunk],
        metadata_store: MetadataStore,
    ):
        memories = await dual_pipeline.ingest_conversation(
            chunks=chunks_for_profile_tests,
            platform=Platform.CLAUDE_CODE,
            capture_profile="dual",
        )
        # Two enriched + two raw siblings.
        assert len(memories) == 4
        # Enriched rows come first, raw siblings appended.
        enriched = memories[: len(chunks_for_profile_tests)]
        raws = memories[len(chunks_for_profile_tests) :]
        for enr, raw in zip(enriched, raws, strict=True):
            assert enr.capture_profile == "dual"
            assert raw.capture_profile == "dual"
            assert enr.dual_sibling_id == raw.id
            assert raw.dual_sibling_id == enr.id
            assert raw.topics == []
            assert raw.entities == []
            # Both sides reference the same chunk content (metadata diverges).
            assert raw.content == enr.content

            # Verify persistence — both rows round-trip with sibling linked.
            stored_enr = await metadata_store.get_memory(enr.id)
            stored_raw = await metadata_store.get_memory(raw.id)
            assert stored_enr is not None and stored_raw is not None
            assert stored_enr.dual_sibling_id == raw.id
            assert stored_raw.dual_sibling_id == enr.id

    async def test_dual_single_ingest_pairs_memories(
        self,
        dual_pipeline: IngestionPipeline,
        metadata_store: MetadataStore,
    ):
        memory = await dual_pipeline.ingest_single(
            content="User prefers pnpm over npm",
            content_type=ContentType.PREFERENCE,
            platform=Platform.CLAUDE_CODE,
            topics=["package-manager"],
            capture_profile="dual",
        )
        assert memory.capture_profile == "dual"
        assert memory.dual_sibling_id is not None
        sibling = await metadata_store.get_memory(memory.dual_sibling_id)
        assert sibling is not None
        assert sibling.capture_profile == "dual"
        assert sibling.dual_sibling_id == memory.id
        assert sibling.topics == []
