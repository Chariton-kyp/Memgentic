"""Tests for collection CRUD and membership operations."""

from __future__ import annotations

from memgentic.models import (
    CaptureMethod,
    Collection,
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
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
    )


def _make_collection(name: str = "Project X", **kwargs) -> Collection:
    return Collection(name=name, **kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCollectionCRUD:
    async def test_create_and_get_collection(self, metadata_store: MetadataStore):
        collection = _make_collection(
            name="Project Alpha", description="Main app", color="#FF0000", icon="rocket"
        )
        await metadata_store.create_collection(collection)

        got = await metadata_store.get_collection(collection.id)
        assert got is not None
        assert got.id == collection.id
        assert got.name == "Project Alpha"
        assert got.description == "Main app"
        assert got.color == "#FF0000"
        assert got.icon == "rocket"

    async def test_get_collection_not_found(self, metadata_store: MetadataStore):
        assert await metadata_store.get_collection("nonexistent") is None

    async def test_list_collections(self, metadata_store: MetadataStore):
        for i, name in enumerate(["Alpha", "Beta", "Gamma"]):
            c = _make_collection(name=name, position=float(i))
            await metadata_store.create_collection(c)

        collections = await metadata_store.get_collections()
        assert len(collections) == 3
        # Ordered by position
        assert [c.name for c in collections] == ["Alpha", "Beta", "Gamma"]

    async def test_update_collection(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Original")
        await metadata_store.create_collection(collection)

        await metadata_store.update_collection(
            collection.id, name="Updated", description="New description", color="#00FF00"
        )

        got = await metadata_store.get_collection(collection.id)
        assert got is not None
        assert got.name == "Updated"
        assert got.description == "New description"
        assert got.color == "#00FF00"

    async def test_update_collection_ignores_unknown_fields(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Original")
        await metadata_store.create_collection(collection)

        # Should no-op for fields not in the allow-list
        await metadata_store.update_collection(collection.id, not_a_field="oops")

        got = await metadata_store.get_collection(collection.id)
        assert got is not None
        assert got.name == "Original"

    async def test_delete_collection(self, metadata_store: MetadataStore):
        collection = _make_collection(name="To delete")
        await metadata_store.create_collection(collection)

        await metadata_store.delete_collection(collection.id)

        got = await metadata_store.get_collection(collection.id)
        assert got is None


class TestCollectionMembership:
    async def test_add_memory_to_collection(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Test")
        await metadata_store.create_collection(collection)

        memory = _make_memory("mem-1", content="first memory")
        await metadata_store.save_memory(memory)

        await metadata_store.add_memory_to_collection(collection.id, memory.id)

        memories = await metadata_store.get_collection_memories(collection.id)
        assert len(memories) == 1
        assert memories[0].id == memory.id

    async def test_collection_with_multiple_memories(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Multi")
        await metadata_store.create_collection(collection)

        memory_ids = ["mem-a", "mem-b", "mem-c"]
        for i, mid in enumerate(memory_ids):
            await metadata_store.save_memory(_make_memory(mid, content=f"memory {i}"))
            await metadata_store.add_memory_to_collection(collection.id, mid, position=float(i))

        memories = await metadata_store.get_collection_memories(collection.id)
        assert len(memories) == 3
        assert {m.id for m in memories} == set(memory_ids)

        count = await metadata_store.get_collection_memory_count(collection.id)
        assert count == 3

    async def test_remove_memory_from_collection(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Temp")
        await metadata_store.create_collection(collection)

        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)
        await metadata_store.add_memory_to_collection(collection.id, memory.id)

        assert await metadata_store.get_collection_memory_count(collection.id) == 1

        await metadata_store.remove_memory_from_collection(collection.id, memory.id)
        assert await metadata_store.get_collection_memory_count(collection.id) == 0

    async def test_add_same_memory_twice_is_idempotent(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Dedupe")
        await metadata_store.create_collection(collection)

        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)
        await metadata_store.add_memory_to_collection(collection.id, memory.id)
        await metadata_store.add_memory_to_collection(collection.id, memory.id)

        assert await metadata_store.get_collection_memory_count(collection.id) == 1

    async def test_memory_in_multiple_collections(self, metadata_store: MetadataStore):
        coll_a = _make_collection(name="A")
        coll_b = _make_collection(name="B")
        await metadata_store.create_collection(coll_a)
        await metadata_store.create_collection(coll_b)

        memory = _make_memory("mem-shared")
        await metadata_store.save_memory(memory)

        await metadata_store.add_memory_to_collection(coll_a.id, memory.id)
        await metadata_store.add_memory_to_collection(coll_b.id, memory.id)

        collections = await metadata_store.get_memory_collections(memory.id)
        assert len(collections) == 2
        assert {c.name for c in collections} == {"A", "B"}

    async def test_delete_collection_cascades_memberships(self, metadata_store: MetadataStore):
        collection = _make_collection(name="Cascade")
        await metadata_store.create_collection(collection)

        memory = _make_memory("mem-1")
        await metadata_store.save_memory(memory)
        await metadata_store.add_memory_to_collection(collection.id, memory.id)

        await metadata_store.delete_collection(collection.id)

        # Memory itself still exists, but membership is gone
        assert await metadata_store.get_memory(memory.id) is not None
        assert await metadata_store.get_collection_memory_count(collection.id) == 0
