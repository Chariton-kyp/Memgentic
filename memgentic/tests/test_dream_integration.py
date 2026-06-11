"""End-to-end integration test: seed real memories, run dream, apply patches."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    DreamPatchAction,
    DreamStatus,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.processing.dream import (
    PatchSet,
    ProposedPatch,
    SignalReport,
    apply_dream,
    run_dream,
)
from memgentic.storage.metadata import MetadataStore


def _seed_memory(mid: str, content: str, project: str, topics: list[str]) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.DECISION,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
            session_id=f"sess-{mid}",
        ),
        project=project,
        topics=topics,
        confidence=0.9,
    )


@pytest.fixture()
def settings(tmp_path):
    # Force dream-related env vars off so the dev .env doesn't bleed into
    # the test process (real ANTHROPIC_API_KEY would change LLM routing).
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        collection_name="test_dream_int",
        embedding_dimensions=768,
        anthropic_api_key=None,
        dream_signal_model="",
        dream_consolidate_model="claude-sonnet-4-6",
    )


def _make_scripted_llm(patches_to_emit: list[ProposedPatch]):
    """LLM client whose Consolidate phase emits the given patches once."""
    llm = MagicMock()
    llm.available = True
    emitted = {"patch": False}

    async def _gen(prompt, schema):
        if schema is SignalReport:
            return SignalReport(), {"input_tokens": 0, "output_tokens": 0}
        if schema is PatchSet:
            if emitted["patch"]:
                return PatchSet(patches=[]), {"input_tokens": 0, "output_tokens": 0}
            emitted["patch"] = True
            return (
                PatchSet(patches=patches_to_emit),
                {"input_tokens": 0, "output_tokens": 0},
            )
        return None, {"input_tokens": 0, "output_tokens": 0}

    llm.generate_structured_with_usage = AsyncMock(side_effect=_gen)
    return llm


class TestDreamIntegration:
    """Verify the full propose-then-apply flow over a real metadata store."""

    async def test_run_then_apply_full_lifecycle(self, metadata_store: MetadataStore, settings):
        # Seed: 3 memories, two of which are duplicates about the same decision
        await metadata_store.save_memory(
            _seed_memory(
                "canonical",
                "We picked Qdrant for vector storage.",
                project="test-int",
                topics=["qdrant", "vector-db"],
            )
        )
        await metadata_store.save_memory(
            _seed_memory(
                "duplicate",
                "Decision: use Qdrant for vectors.",
                project="test-int",
                topics=["qdrant", "vector-db"],
            )
        )
        await metadata_store.save_memory(
            _seed_memory(
                "stale",
                "Old decision: use Pinecone (rolled back).",
                project="test-int",
                topics=["pinecone"],
            )
        )

        # Pre-state snapshot — used to verify run_dream alone is non-mutating
        active_before = await metadata_store.get_memories_by_filter(limit=100)
        assert len(active_before) == 3

        scripted_patches = [
            ProposedPatch(
                action=DreamPatchAction.MERGE,
                target_memory_ids=["canonical", "duplicate"],
                evidence="Both memories record the same Qdrant decision.",
            ),
            ProposedPatch(
                action=DreamPatchAction.ARCHIVE_STALE,
                target_memory_ids=["stale"],
                evidence="Pinecone decision was explicitly rolled back.",
            ),
            ProposedPatch(
                action=DreamPatchAction.INSERT_INSIGHT,
                target_memory_ids=[],
                new_content="Project consistently chooses sqlite-vec / Qdrant over hosted.",
                new_metadata={"topics": ["vector-db"], "confidence": 0.9},
                evidence="Pattern across multiple sessions.",
            ),
        ]
        llm = _make_scripted_llm(scripted_patches)

        run = await run_dream(
            project="test-int",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_llm=llm,
            consolidate_llm=llm,
            limit_sessions=5,
        )
        assert run.status == DreamStatus.COMPLETED
        assert run.input_memory_count == 3

        # Live memories untouched after dream — only patches were created
        active_after_run = [
            m
            for m in await metadata_store.get_memories_by_filter(limit=100)
            if m.status == MemoryStatus.ACTIVE
        ]
        assert {m.id for m in active_after_run} == {"canonical", "duplicate", "stale"}

        patches = await metadata_store.get_dream_patches(run.id)
        assert {p.action for p in patches} == {
            DreamPatchAction.MERGE,
            DreamPatchAction.ARCHIVE_STALE,
            DreamPatchAction.INSERT_INSIGHT,
        }

        # Apply (full, including destructive)
        report = await apply_dream(
            run.id, metadata_store=metadata_store, only_non_destructive=False
        )
        assert report.applied == 3
        assert report.superseded_memories == ["duplicate"]
        assert report.archived_memories == ["stale"]
        assert len(report.inserted_memories) == 1

        # Live state reflects the patches
        canonical = await metadata_store.get_memory("canonical")
        duplicate = await metadata_store.get_memory("duplicate")
        stale = await metadata_store.get_memory("stale")
        assert canonical is not None
        assert duplicate is not None
        assert stale is not None
        assert canonical.status == MemoryStatus.ACTIVE
        assert "duplicate" in canonical.supersedes
        assert duplicate.status == MemoryStatus.SUPERSEDED
        assert stale.status == MemoryStatus.ARCHIVED

        # The inserted insight has the right provenance markers
        new_id = report.inserted_memories[0]
        new_mem = await metadata_store.get_memory(new_id)
        assert new_mem is not None
        assert new_mem.source.platform == Platform.DREAM
        assert new_mem.source.session_id == f"dream:{run.id}"
        assert "vector-db" in new_mem.topics

    async def test_input_untouched_when_apply_not_called(
        self, metadata_store: MetadataStore, settings
    ):
        """Critical Anthropic-Dreams semantic: input is immutable until apply."""
        await metadata_store.save_memory(
            _seed_memory("a", "We use Qdrant.", project="test-int", topics=["qdrant"])
        )
        await metadata_store.save_memory(
            _seed_memory("b", "Decision: Qdrant.", project="test-int", topics=["qdrant"])
        )

        scripted = [
            ProposedPatch(
                action=DreamPatchAction.MERGE,
                target_memory_ids=["a", "b"],
                evidence="dup",
            )
        ]
        llm = _make_scripted_llm(scripted)

        run = await run_dream(
            project="test-int",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_llm=llm,
            consolidate_llm=llm,
        )
        assert run.status == DreamStatus.COMPLETED

        a = await metadata_store.get_memory("a")
        b = await metadata_store.get_memory("b")
        assert a is not None and b is not None
        assert a.status == MemoryStatus.ACTIVE
        assert b.status == MemoryStatus.ACTIVE
