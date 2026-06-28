"""W4 — reductive dream: consolidation now REDUCES the active count.

A successful INSERT_INSIGHT archives the source memories it explicitly
supersedes; MERGE/SUPERSEDE drop consumed vectors. All of this honors the
absolute safety rules — pinned and mcp_tool sources are never archived /
superseded.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from memgentic.models import (
    CaptureMethod,
    ContentType,
    DreamPatch,
    DreamPatchAction,
    DreamRun,
    DreamStatus,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.processing.dream import apply_dream
from memgentic.storage.metadata import MetadataStore


def _mem(
    mid: str,
    content: str = "x",
    *,
    capture_method: CaptureMethod = CaptureMethod.AUTO_DAEMON,
    is_pinned: bool = False,
) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(platform=Platform.CLAUDE_CODE, capture_method=capture_method),
        is_pinned=is_pinned,
    )


async def _seed(
    store: MetadataStore,
    action: DreamPatchAction,
    *,
    targets: list[str] | None = None,
    metadata: dict | None = None,
    content: str | None = None,
) -> DreamRun:
    run = DreamRun(project="test", status=DreamStatus.COMPLETED)
    await store.create_dream_run(run)
    patch = DreamPatch(
        dream_id=run.id,
        action=action,
        target_memory_ids=targets or [],
        new_metadata=metadata,
        new_content=content,
        evidence="test",
    )
    await store.create_dream_patches([patch])
    return run


class TestInsertInsightReductive:
    async def test_archives_superseded_sources_and_reduces_active_count(
        self, metadata_store: MetadataStore
    ):
        await metadata_store.save_memory(_mem("src1", "we use postgres"))
        await metadata_store.save_memory(_mem("src2", "we use postgres 18"))
        assert await metadata_store.get_total_count() == 2

        run = await _seed(
            metadata_store,
            DreamPatchAction.INSERT_INSIGHT,
            metadata={"supersedes": ["src1", "src2"], "topics": ["db"]},
            content="Project standardized on PostgreSQL 18.",
        )
        vector_store = AsyncMock()
        report = await apply_dream(run.id, metadata_store=metadata_store, vector_store=vector_store)

        assert len(report.inserted_memories) == 1
        assert sorted(report.archived_memories) == ["src1", "src2"]
        # Sources archived, vectors dropped.
        assert (await metadata_store.get_memory("src1")).status == MemoryStatus.ARCHIVED
        assert (await metadata_store.get_memory("src2")).status == MemoryStatus.ARCHIVED
        assert vector_store.delete_memory.await_count == 2
        # Net effect: insight(+1) - 2 archived sources = active count DOWN.
        assert await metadata_store.get_total_count() == 1

    async def test_skips_pinned_and_mcp_tool_sources(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_mem("plain", "plain source"))
        await metadata_store.save_memory(_mem("pinned", "pinned source", is_pinned=True))
        await metadata_store.save_memory(
            _mem("mcp", "owner remember", capture_method=CaptureMethod.MCP_TOOL)
        )

        run = await _seed(
            metadata_store,
            DreamPatchAction.INSERT_INSIGHT,
            metadata={"supersedes": ["plain", "pinned", "mcp"]},
            content="Consolidated insight.",
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)

        assert report.archived_memories == ["plain"]
        assert report.skipped_protected == 2
        assert (await metadata_store.get_memory("plain")).status == MemoryStatus.ARCHIVED
        # Protected sources untouched.
        assert (await metadata_store.get_memory("pinned")).status == MemoryStatus.ACTIVE
        assert (await metadata_store.get_memory("mcp")).status == MemoryStatus.ACTIVE

    async def test_citation_targets_stay_active(self, metadata_store: MetadataStore):
        """Regression guard: target_memory_ids are CITATIONS, not consumed
        sources — without an explicit supersedes they must remain active."""
        await metadata_store.save_memory(_mem("cite", "evidence"))
        run = await _seed(
            metadata_store,
            DreamPatchAction.INSERT_INSIGHT,
            targets=["cite"],
            metadata={"topics": ["x"]},
            content="Insight citing evidence.",
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)
        assert report.archived_memories == []
        assert (await metadata_store.get_memory("cite")).status == MemoryStatus.ACTIVE


class TestMergeReductiveSafety:
    async def test_merge_skips_protected_sources(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_mem("canonical", "canonical fact"))
        await metadata_store.save_memory(_mem("dup-plain", "dup fact"))
        await metadata_store.save_memory(_mem("dup-pinned", "dup fact", is_pinned=True))
        await metadata_store.save_memory(
            _mem("dup-mcp", "dup fact", capture_method=CaptureMethod.MCP_TOOL)
        )

        run = await _seed(
            metadata_store,
            DreamPatchAction.MERGE,
            targets=["canonical", "dup-plain", "dup-pinned", "dup-mcp"],
        )
        vector_store = AsyncMock()
        report = await apply_dream(run.id, metadata_store=metadata_store, vector_store=vector_store)

        # Only the non-protected duplicate is superseded; vector dropped once.
        assert report.superseded_memories == ["dup-plain"]
        assert report.skipped_protected == 2
        assert (await metadata_store.get_memory("dup-plain")).status == MemoryStatus.SUPERSEDED
        assert (await metadata_store.get_memory("dup-pinned")).status == MemoryStatus.ACTIVE
        assert (await metadata_store.get_memory("dup-mcp")).status == MemoryStatus.ACTIVE
        assert (await metadata_store.get_memory("canonical")).status == MemoryStatus.ACTIVE
        vector_store.delete_memory.assert_awaited_once_with("dup-plain")
