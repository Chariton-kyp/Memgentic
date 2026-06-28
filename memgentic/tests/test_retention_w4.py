"""W4 — self-cleaning + retention: GC and bulk-clean.

Covers the absolute safety rules:
  * GC hard-deletes ONLY archived/superseded rows past the grace period, and
    NEVER active / pinned / mcp_tool rows;
  * clean dry-run reports without mutating; --apply archives non-protected
    duplicates + noise while preserving pinned + mcp_tool + the best-of-cluster.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.processing.retention import (
    is_protected,
    plan_clean,
    run_clean,
    run_gc,
)
from memgentic.storage.metadata import MetadataStore


def _mem(
    mid: str,
    content: str = "some content",
    *,
    capture_method: CaptureMethod = CaptureMethod.AUTO_DAEMON,
    is_pinned: bool = False,
    content_type: ContentType = ContentType.FACT,
    importance: float = 1.0,
) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=content_type,
        source=SourceMetadata(platform=Platform.CLAUDE_CODE, capture_method=capture_method),
        is_pinned=is_pinned,
        importance_score=importance,
    )


async def _archive_and_backdate(store: MetadataStore, mid: str, *, days: int, status: str) -> None:
    """Move a saved memory to ``status`` then backdate its updated_at by N days."""
    await store.update_memory_status(mid, status)
    iso = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    await store._db.execute(  # type: ignore[union-attr]
        "UPDATE memories SET updated_at = ? WHERE id = ?", (iso, mid)
    )
    await store._db.commit()  # type: ignore[union-attr]


@pytest.fixture()
def gc_settings(tmp_path) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_dimensions=768,
        hard_delete_archived_after_days=30,
    )


# ---------------------------------------------------------------------------
# Safety predicate
# ---------------------------------------------------------------------------


class TestIsProtected:
    def test_pinned_is_protected(self):
        assert is_protected(_mem("a", is_pinned=True)) is True

    def test_mcp_tool_is_protected(self):
        assert is_protected(_mem("a", capture_method=CaptureMethod.MCP_TOOL)) is True

    def test_plain_auto_daemon_not_protected(self):
        assert is_protected(_mem("a")) is False


# ---------------------------------------------------------------------------
# GC
# ---------------------------------------------------------------------------


class TestGC:
    async def test_gc_hard_deletes_only_expired_archived(
        self, metadata_store: MetadataStore, gc_settings
    ):
        # Expired archived + expired superseded → deletable.
        await metadata_store.save_memory(_mem("old-archived", "x"))
        await _archive_and_backdate(metadata_store, "old-archived", days=60, status="archived")
        await metadata_store.save_memory(_mem("old-superseded", "y"))
        await _archive_and_backdate(metadata_store, "old-superseded", days=45, status="superseded")
        # Recently archived → still within grace.
        await metadata_store.save_memory(_mem("fresh-archived", "z"))
        await _archive_and_backdate(metadata_store, "fresh-archived", days=2, status="archived")
        # Active old → never a candidate.
        await metadata_store.save_memory(_mem("active-old", "w"))
        await metadata_store._db.execute(  # type: ignore[union-attr]
            "UPDATE memories SET updated_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=90)).isoformat(), "active-old"),
        )
        await metadata_store._db.commit()  # type: ignore[union-attr]

        vector_store = AsyncMock()

        # Dry-run: reports candidates, mutates nothing.
        dry = await run_gc(
            metadata_store=metadata_store, settings=gc_settings, vector_store=vector_store
        )
        assert dry.applied is False
        assert sorted(dry.deleted_ids) == ["old-archived", "old-superseded"]
        assert dry.hard_deleted == 0
        vector_store.delete_memory.assert_not_called()
        assert await metadata_store.get_memory("old-archived") is not None

        # Apply: deletes exactly the expired archived/superseded rows.
        applied = await run_gc(
            metadata_store=metadata_store,
            settings=gc_settings,
            vector_store=vector_store,
            apply=True,
        )
        assert applied.hard_deleted == 2
        assert applied.vectors_deleted == 2
        assert await metadata_store.get_memory("old-archived") is None
        assert await metadata_store.get_memory("old-superseded") is None
        assert await metadata_store.get_memory("fresh-archived") is not None
        assert await metadata_store.get_memory("active-old") is not None

    async def test_gc_never_deletes_pinned_or_mcp_tool(
        self, metadata_store: MetadataStore, gc_settings
    ):
        # Both are archived AND long expired — only the safety rules protect them.
        await metadata_store.save_memory(_mem("pinned", "p", is_pinned=True))
        await _archive_and_backdate(metadata_store, "pinned", days=90, status="archived")
        await metadata_store.save_memory(_mem("mcp", "m", capture_method=CaptureMethod.MCP_TOOL))
        await _archive_and_backdate(metadata_store, "mcp", days=90, status="archived")

        report = await run_gc(metadata_store=metadata_store, settings=gc_settings, apply=True)
        assert report.candidates == 0
        assert report.hard_deleted == 0
        assert await metadata_store.get_memory("pinned") is not None
        assert await metadata_store.get_memory("mcp") is not None

    async def test_gc_disabled_when_grace_zero(self, metadata_store: MetadataStore, gc_settings):
        gc_settings.hard_delete_archived_after_days = 0
        await metadata_store.save_memory(_mem("old", "x"))
        await _archive_and_backdate(metadata_store, "old", days=90, status="archived")

        report = await run_gc(metadata_store=metadata_store, settings=gc_settings, apply=True)
        assert report.disabled is True
        assert report.hard_deleted == 0
        assert await metadata_store.get_memory("old") is not None

    async def test_hard_delete_memories_storage_guard(self, metadata_store: MetadataStore):
        """The storage layer itself refuses to delete active / pinned / mcp_tool
        rows even if their ids are passed directly (defense in depth)."""
        await metadata_store.save_memory(_mem("active", "a"))  # active
        await metadata_store.save_memory(_mem("pinned-arch", "p", is_pinned=True))
        await metadata_store.update_memory_status("pinned-arch", "archived")
        await metadata_store.save_memory(
            _mem("mcp-arch", "m", capture_method=CaptureMethod.MCP_TOOL)
        )
        await metadata_store.update_memory_status("mcp-arch", "archived")

        deleted = await metadata_store.hard_delete_memories(["active", "pinned-arch", "mcp-arch"])
        assert deleted == 0
        for mid in ("active", "pinned-arch", "mcp-arch"):
            assert await metadata_store.get_memory(mid) is not None

    async def test_hard_delete_scrubs_dangling_provenance_refs(self, metadata_store: MetadataStore):
        """After hard-deleting id X, a surviving row that had supersedes=[X, Y]
        now has supersedes=[Y] (X scrubbed, Y preserved). (Fix I1)"""
        # Create two deletable memories (archived, not pinned, not mcp_tool).
        await metadata_store.save_memory(_mem("x", "x content"))
        await metadata_store.save_memory(_mem("y", "y content"))
        await metadata_store.update_memory_status("x", "archived")
        # y stays active — should NOT be scrubbed from the array.

        # A surviving row whose supersedes list references both x and y.
        survivor = _mem("survivor", "surviving content")
        survivor = survivor.model_copy(update={"supersedes": ["x", "y"]})
        await metadata_store.save_memory(survivor)

        deleted = await metadata_store.hard_delete_memories(["x"])
        assert deleted == 1

        updated = await metadata_store.get_memory("survivor")
        assert updated is not None
        assert updated.supersedes == ["y"]  # x scrubbed; y (alive) preserved
        # y itself must still exist in the store.
        assert await metadata_store.get_memory("y") is not None


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------


class TestPlanClean:
    def test_keeps_best_and_preserves_protected_duplicates(self):
        dup = "We use Traefik 3 as the edge router."
        pinned = _mem("pinned", dup, is_pinned=True, importance=0.2)
        mcp = _mem("mcp", dup, capture_method=CaptureMethod.MCP_TOOL, importance=0.2)
        plain1 = _mem("plain1", dup, importance=0.5)
        plain2 = _mem("plain2", dup, importance=0.9)

        plan = plan_clean([pinned, mcp, plain1, plain2])
        archived = {m.id for m in plan.dup_archive}
        # Pinned wins as keeper; mcp preserved; both plain rows archived.
        assert archived == {"plain1", "plain2"}
        assert plan.preserved_mcp_tool == 1
        assert plan.dup_clusters == 1

    def test_no_duplicates_no_archival(self):
        plan = plan_clean([_mem("a", "alpha unique"), _mem("b", "beta unique")])
        assert plan.dup_archive == []
        assert plan.dup_clusters == 0

    def test_noise_archived_but_genuine_kept(self):
        noise = _mem("noise", "You are a summarizer that condenses logs.")
        genuine = _mem("genuine", "We decided to adopt FastAPI for the API layer.")
        plan = plan_clean([noise, genuine])
        ids = {m.id for m in plan.noise_archive}
        assert "noise" in ids
        assert "genuine" not in ids

    def test_pinned_noise_is_preserved(self):
        pinned_noise = _mem("pn", "You are a summarizer.", is_pinned=True)
        plan = plan_clean([pinned_noise])
        assert plan.noise_archive == []


class TestRunClean:
    async def test_clean_dry_run_reports_without_mutating(self, metadata_store: MetadataStore):
        dup = "We use Valkey for the cache layer."
        await metadata_store.save_memory(_mem("a", dup))
        await metadata_store.save_memory(_mem("b", dup))

        report = await run_clean(metadata_store=metadata_store, apply=False)
        assert report.applied is False
        assert report.total_archived == 1  # one of the two duplicates
        # Nothing mutated.
        assert await metadata_store.get_total_count() == 2

    async def test_clean_apply_archives_dups_preserving_protected(
        self, metadata_store: MetadataStore
    ):
        dup = "Embeddings model is bge-m3 with a bge reranker."
        await metadata_store.save_memory(_mem("pinned", dup, is_pinned=True))
        await metadata_store.save_memory(_mem("mcp", dup, capture_method=CaptureMethod.MCP_TOOL))
        await metadata_store.save_memory(_mem("plain1", dup))
        await metadata_store.save_memory(_mem("plain2", dup))

        vector_store = AsyncMock()
        report = await run_clean(
            metadata_store=metadata_store, vector_store=vector_store, apply=True
        )
        assert report.applied is True
        assert sorted(report.archived_ids) == ["plain1", "plain2"]

        # The two plain duplicates are archived; protected + keeper stay active.
        assert (await metadata_store.get_memory("plain1")).status == MemoryStatus.ARCHIVED
        assert (await metadata_store.get_memory("plain2")).status == MemoryStatus.ARCHIVED
        assert (await metadata_store.get_memory("pinned")).status == MemoryStatus.ACTIVE
        assert (await metadata_store.get_memory("mcp")).status == MemoryStatus.ACTIVE
        # Vectors of archived rows dropped from recall.
        assert vector_store.delete_memory.await_count == 2
