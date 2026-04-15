"""Tests for memory pin/unpin endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def _create_memory(client: AsyncClient, content: str) -> str:
    """Create a memory and return its ID."""
    resp = await client.post(
        "/api/v1/memories",
        json={"content": content, "source": "claude_code"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_pin_memory(client: AsyncClient):
    """POST /api/v1/memories/{id}/pin pins the memory."""
    memory_id = await _create_memory(client, "A memory worth pinning for later reference")
    resp = await client.post(f"/api/v1/memories/{memory_id}/pin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_pinned"] is True
    assert data["pinned_at"] is not None


async def test_unpin_memory(client: AsyncClient):
    """DELETE /api/v1/memories/{id}/pin unpins the memory."""
    memory_id = await _create_memory(client, "A memory that will be pinned then unpinned")
    await client.post(f"/api/v1/memories/{memory_id}/pin")

    resp = await client.delete(f"/api/v1/memories/{memory_id}/pin")
    assert resp.status_code == 200
    assert resp.json()["is_pinned"] is False


async def test_pin_memory_not_found(client: AsyncClient):
    """POST /api/v1/memories/{id}/pin returns 404 for an unknown memory."""
    resp = await client.post("/api/v1/memories/nonexistent-id/pin")
    assert resp.status_code == 404


async def test_unpin_memory_not_found(client: AsyncClient):
    """DELETE /api/v1/memories/{id}/pin returns 404 for an unknown memory."""
    resp = await client.delete("/api/v1/memories/nonexistent-id/pin")
    assert resp.status_code == 404


async def test_list_pinned_memories(client: AsyncClient):
    """GET /api/v1/memories/pinned returns only pinned memories."""
    # Initially empty
    empty_resp = await client.get("/api/v1/memories/pinned")
    assert empty_resp.status_code == 200
    assert empty_resp.json()["total"] == 0

    # Create and pin two memories
    id1 = await _create_memory(client, "First pinnable memory about architecture decisions")
    id2 = await _create_memory(client, "Second pinnable memory about deployment strategies")
    # Create one that stays unpinned
    await _create_memory(client, "Third memory that remains unpinned")

    await client.post(f"/api/v1/memories/{id1}/pin")
    await client.post(f"/api/v1/memories/{id2}/pin")

    resp = await client.get("/api/v1/memories/pinned")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    pinned_ids = {m["id"] for m in data["memories"]}
    assert pinned_ids == {id1, id2}


async def test_pin_persists_after_update(client: AsyncClient):
    """Pinning survives a PATCH update (regression test for save_memory)."""
    memory_id = await _create_memory(client, "Memory to verify pin survives update cycle")

    # Pin it
    pin_resp = await client.post(f"/api/v1/memories/{memory_id}/pin")
    assert pin_resp.json()["is_pinned"] is True

    # Patch topics — must NOT reset is_pinned
    patch_resp = await client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"topics": ["newly-added-topic"]},
    )
    assert patch_resp.status_code == 200
    patch_data = patch_resp.json()
    assert patch_data["topics"] == ["newly-added-topic"]
    assert patch_data["is_pinned"] is True
    assert patch_data["pinned_at"] is not None

    # And the pinned list still contains it
    pinned_list = await client.get("/api/v1/memories/pinned")
    assert pinned_list.json()["total"] == 1
    assert pinned_list.json()["memories"][0]["id"] == memory_id
