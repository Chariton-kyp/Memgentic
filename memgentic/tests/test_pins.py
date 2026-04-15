"""Tests for pinning memories."""

from __future__ import annotations

from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.storage.metadata import MetadataStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(memory_id: str, content: str = "content") -> Memory:
    return Memory(
        id=memory_id,
        content=content,
        content_type=ContentType.DECISION,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPinUnpin:
    async def test_pin_memory(self, metadata_store: MetadataStore):
        memory = _make_memory("mem-1", content="important decision")
        await metadata_store.save_memory(memory)

        await metadata_store.pin_memory(memory.id)

        got = await metadata_store.get_memory(memory.id)
        assert got is not None
        assert got.is_pinned is True
        assert got.pinned_at is not None

    async def test_unpin_memory(self, metadata_store: MetadataStore):
        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)
        await metadata_store.pin_memory(memory.id)

        await metadata_store.unpin_memory(memory.id)

        got = await metadata_store.get_memory(memory.id)
        assert got is not None
        assert got.is_pinned is False
        assert got.pinned_at is None

    async def test_pin_is_idempotent(self, metadata_store: MetadataStore):
        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)

        await metadata_store.pin_memory(memory.id)
        await metadata_store.pin_memory(memory.id)

        got = await metadata_store.get_memory(memory.id)
        assert got is not None
        assert got.is_pinned is True


class TestListPinnedMemories:
    async def test_list_pinned_memories(self, metadata_store: MetadataStore):
        # Save 3 memories, pin 2 of them
        for i in range(3):
            m = _make_memory(f"mem-{i}", content=f"memory {i}")
            await metadata_store.save_memory(m)

        await metadata_store.pin_memory("mem-0")
        await metadata_store.pin_memory("mem-2")

        pinned = await metadata_store.get_pinned_memories()
        assert len(pinned) == 2
        assert {m.id for m in pinned} == {"mem-0", "mem-2"}
        assert all(m.is_pinned for m in pinned)

    async def test_empty_pinned_list(self, metadata_store: MetadataStore):
        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)

        pinned = await metadata_store.get_pinned_memories()
        assert pinned == []

    async def test_pinned_memories_respects_limit(self, metadata_store: MetadataStore):
        for i in range(5):
            m = _make_memory(f"mem-{i}", content=f"memory {i}")
            await metadata_store.save_memory(m)
            await metadata_store.pin_memory(m.id)

        pinned = await metadata_store.get_pinned_memories(limit=2)
        assert len(pinned) == 2


class TestSaveMemoryPreservesPinState:
    """Regression: save_memory must preserve is_pinned/pinned_at on updates."""

    async def test_save_memory_preserves_pin_state(self, metadata_store: MetadataStore):
        memory = _make_memory("mem-1", content="original")
        await metadata_store.save_memory(memory)
        await metadata_store.pin_memory(memory.id)

        # Re-fetch to grab the pinned state, then modify content and re-save
        got = await metadata_store.get_memory(memory.id)
        assert got is not None
        assert got.is_pinned is True

        got.content = "updated content"
        await metadata_store.save_memory(got)

        reloaded = await metadata_store.get_memory(memory.id)
        assert reloaded is not None
        assert reloaded.content == "updated content"
        assert reloaded.is_pinned is True
        assert reloaded.pinned_at is not None

    async def test_save_memory_with_is_pinned_false_unpins(self, metadata_store: MetadataStore):
        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)
        await metadata_store.pin_memory(memory.id)

        got = await metadata_store.get_memory(memory.id)
        assert got is not None
        got.is_pinned = False
        got.pinned_at = None
        await metadata_store.save_memory(got)

        reloaded = await metadata_store.get_memory(memory.id)
        assert reloaded is not None
        assert reloaded.is_pinned is False
