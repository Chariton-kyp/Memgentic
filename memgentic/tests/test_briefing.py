"""Tests for cross-agent briefing (get_memories_since)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SessionConfig,
    SourceMetadata,
)
from memgentic.storage.metadata import MetadataStore


def _make_memory(
    id: str,
    content: str = "test content",
    platform: Platform = Platform.CLAUDE_CODE,
    content_type: ContentType = ContentType.FACT,
    created_at: datetime | None = None,
    topics: list[str] | None = None,
) -> Memory:
    return Memory(
        id=id,
        content=content,
        content_type=content_type,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
        topics=topics or [],
        created_at=created_at or datetime.now(UTC),
    )


class TestGetMemoriesSince:
    """Tests for MetadataStore.get_memories_since()."""

    async def test_returns_memories_after_cutoff(self, metadata_store: MetadataStore):
        """Memories created after the cutoff are returned; older ones are not."""
        now = datetime.now(UTC)
        old = _make_memory(id="old-1", created_at=now - timedelta(hours=48))
        recent = _make_memory(id="recent-1", created_at=now - timedelta(hours=2))

        await metadata_store.save_memory(old)
        await metadata_store.save_memory(recent)

        cutoff = now - timedelta(hours=24)
        results = await metadata_store.get_memories_since(cutoff)

        ids = [m.id for m in results]
        assert "recent-1" in ids
        assert "old-1" not in ids

    async def test_empty_result(self, metadata_store: MetadataStore):
        """Returns empty list when no memories exist after cutoff."""
        now = datetime.now(UTC)
        old = _make_memory(id="old-2", created_at=now - timedelta(hours=48))
        await metadata_store.save_memory(old)

        cutoff = now - timedelta(hours=1)
        results = await metadata_store.get_memories_since(cutoff)
        assert results == []

    async def test_respects_limit(self, metadata_store: MetadataStore):
        """Limit parameter caps the number of returned memories."""
        now = datetime.now(UTC)
        for i in range(10):
            m = _make_memory(id=f"lim-{i}", created_at=now - timedelta(minutes=i))
            await metadata_store.save_memory(m)

        cutoff = now - timedelta(hours=1)
        results = await metadata_store.get_memories_since(cutoff, limit=3)
        assert len(results) == 3

    async def test_platform_filtering_via_session_config(self, metadata_store: MetadataStore):
        """Session config filters are applied to the since query."""
        now = datetime.now(UTC)
        claude_mem = _make_memory(
            id="claude-1", platform=Platform.CLAUDE_CODE, created_at=now - timedelta(hours=1)
        )
        chatgpt_mem = _make_memory(
            id="chatgpt-1", platform=Platform.CHATGPT, created_at=now - timedelta(hours=1)
        )
        await metadata_store.save_memory(claude_mem)
        await metadata_store.save_memory(chatgpt_mem)

        cutoff = now - timedelta(hours=24)

        # Only Claude Code
        config = SessionConfig(include_sources=[Platform.CLAUDE_CODE])
        results = await metadata_store.get_memories_since(cutoff, session_config=config)
        ids = [m.id for m in results]
        assert "claude-1" in ids
        assert "chatgpt-1" not in ids

    async def test_excludes_archived_memories(self, metadata_store: MetadataStore):
        """Archived memories are excluded even if they are recent."""
        from memgentic.models import MemoryStatus

        now = datetime.now(UTC)
        active = _make_memory(id="active-1", created_at=now - timedelta(hours=1))
        archived = _make_memory(id="archived-1", created_at=now - timedelta(hours=1))
        archived.status = MemoryStatus.ARCHIVED

        await metadata_store.save_memory(active)
        await metadata_store.save_memory(archived)

        cutoff = now - timedelta(hours=24)
        results = await metadata_store.get_memories_since(cutoff)
        ids = [m.id for m in results]
        assert "active-1" in ids
        assert "archived-1" not in ids

    async def test_get_top_memories_by_importance(self, metadata_store: MetadataStore):
        """get_top_memories returns highest-importance active memories."""
        now = datetime.now(UTC)
        low = _make_memory(id="top-low", created_at=now - timedelta(days=30))
        low.importance_score = 0.1
        high = _make_memory(id="top-high", created_at=now - timedelta(days=30))
        high.importance_score = 0.9
        mid = _make_memory(id="top-mid", created_at=now - timedelta(days=30))
        mid.importance_score = 0.5

        for m in (low, high, mid):
            await metadata_store.save_memory(m)

        results = await metadata_store.get_top_memories(limit=2)
        ids = [m.id for m in results]
        assert ids == ["top-high", "top-mid"]

    async def test_generate_briefing_fallback_to_top(self, metadata_store: MetadataStore):
        """generate_briefing falls back to top memories when none are recent."""
        from memgentic.processing.context_generator import generate_briefing

        now = datetime.now(UTC)
        old_important = _make_memory(
            id="fb-1",
            content="Critical architectural decision we made long ago",
            created_at=now - timedelta(days=90),
        )
        old_important.importance_score = 0.95
        await metadata_store.save_memory(old_important)

        # No recent memories within 24h, so fallback should kick in.
        briefing = await generate_briefing(metadata_store, hours=24, limit=5)
        assert "Critical architectural decision" in briefing

    async def test_ordered_by_created_at_desc(self, metadata_store: MetadataStore):
        """Results are ordered newest first."""
        now = datetime.now(UTC)
        m1 = _make_memory(id="order-1", created_at=now - timedelta(hours=3))
        m2 = _make_memory(id="order-2", created_at=now - timedelta(hours=1))
        m3 = _make_memory(id="order-3", created_at=now - timedelta(hours=2))

        await metadata_store.save_memory(m1)
        await metadata_store.save_memory(m2)
        await metadata_store.save_memory(m3)

        cutoff = now - timedelta(hours=24)
        results = await metadata_store.get_memories_since(cutoff)
        ids = [m.id for m in results]
        assert ids == ["order-2", "order-3", "order-1"]
