"""Tests for collection CRUD and membership endpoints."""

from __future__ import annotations

from httpx import AsyncClient

# --- Create ---


async def test_create_collection(client: AsyncClient):
    """POST /api/v1/collections creates and returns a new collection."""
    payload = {
        "name": "Learning",
        "description": "Things I'm learning about",
        "color": "#3B82F6",
        "icon": "book",
    }
    resp = await client.post("/api/v1/collections", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Learning"
    assert data["description"] == "Things I'm learning about"
    assert data["color"] == "#3B82F6"
    assert data["icon"] == "book"
    assert data["memory_count"] == 0
    assert data["id"]  # non-empty UUID


async def test_create_collection_invalid(client: AsyncClient):
    """POST /api/v1/collections with empty name returns 422."""
    resp = await client.post("/api/v1/collections", json={"name": ""})
    assert resp.status_code == 422


# --- List ---


async def test_list_collections_empty(client: AsyncClient):
    """GET /api/v1/collections returns an empty list."""
    resp = await client.get("/api/v1/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["collections"] == []
    assert data["total"] == 0


async def test_list_collections_after_create(client: AsyncClient):
    """After creating 2 collections, list returns both."""
    for name in ("Alpha", "Beta"):
        await client.post("/api/v1/collections", json={"name": name})

    resp = await client.get("/api/v1/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    names = {c["name"] for c in data["collections"]}
    assert names == {"Alpha", "Beta"}


# --- Update ---


async def test_update_collection(client: AsyncClient):
    """PATCH /api/v1/collections/{id} updates name and color."""
    create_resp = await client.post("/api/v1/collections", json={"name": "Original"})
    collection_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/collections/{collection_id}",
        json={"name": "Renamed", "color": "#EF4444"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["name"] == "Renamed"
    assert data["color"] == "#EF4444"


async def test_update_collection_not_found(client: AsyncClient):
    """PATCH /api/v1/collections/{id} returns 404 for an unknown id."""
    resp = await client.patch(
        "/api/v1/collections/nonexistent-id",
        json={"name": "New Name"},
    )
    assert resp.status_code == 404


# --- Delete ---


async def test_delete_collection(client: AsyncClient):
    """DELETE /api/v1/collections/{id} returns 204 and the collection is gone."""
    create_resp = await client.post("/api/v1/collections", json={"name": "To Delete"})
    collection_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/collections/{collection_id}")
    assert del_resp.status_code == 204

    # Subsequent operations on the deleted collection should 404
    update_resp = await client.patch(
        f"/api/v1/collections/{collection_id}",
        json={"name": "Should Not Exist"},
    )
    assert update_resp.status_code == 404


async def test_delete_collection_not_found(client: AsyncClient):
    """DELETE /api/v1/collections/{id} returns 404 for unknown id."""
    resp = await client.delete("/api/v1/collections/nonexistent-id")
    assert resp.status_code == 404


# --- Membership ---


async def test_add_memory_to_collection(client: AsyncClient):
    """POST /api/v1/collections/{id}/memories adds a memory and list reflects it."""
    # Create a collection
    coll_resp = await client.post("/api/v1/collections", json={"name": "My Stack"})
    collection_id = coll_resp.json()["id"]

    # Create a memory
    mem_resp = await client.post(
        "/api/v1/memories",
        json={
            "content": "Python is a great language for scripting",
            "content_type": "fact",
            "source": "claude_code",
        },
    )
    memory_id = mem_resp.json()["id"]

    # Add the memory to the collection
    add_resp = await client.post(
        f"/api/v1/collections/{collection_id}/memories",
        json={"memory_id": memory_id},
    )
    assert add_resp.status_code == 201
    assert add_resp.json()["memory_id"] == memory_id

    # Verify membership via list
    list_resp = await client.get(f"/api/v1/collections/{collection_id}/memories")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] == 1
    assert data["memories"][0]["id"] == memory_id


async def test_remove_memory_from_collection(client: AsyncClient):
    """DELETE /api/v1/collections/{id}/memories/{mid} removes the membership."""
    coll_resp = await client.post("/api/v1/collections", json={"name": "Temp"})
    collection_id = coll_resp.json()["id"]

    mem_resp = await client.post(
        "/api/v1/memories",
        json={"content": "A short fact to add and remove", "source": "claude_code"},
    )
    memory_id = mem_resp.json()["id"]

    await client.post(
        f"/api/v1/collections/{collection_id}/memories",
        json={"memory_id": memory_id},
    )

    del_resp = await client.delete(f"/api/v1/collections/{collection_id}/memories/{memory_id}")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/v1/collections/{collection_id}/memories")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0


async def test_collection_memories_list_pagination(client: AsyncClient):
    """GET /api/v1/collections/{id}/memories respects pagination."""
    coll_resp = await client.post("/api/v1/collections", json={"name": "Paginated"})
    collection_id = coll_resp.json()["id"]

    # Create 3 memories and add them to the collection
    memory_ids = []
    for i in range(3):
        resp = await client.post(
            "/api/v1/memories",
            json={
                "content": f"Distinct memory number {i} for pagination tests",
                "source": "claude_code",
            },
        )
        memory_ids.append(resp.json()["id"])
        await client.post(
            f"/api/v1/collections/{collection_id}/memories",
            json={"memory_id": memory_ids[-1]},
        )

    # Page 1 of size 2
    page1 = await client.get(
        f"/api/v1/collections/{collection_id}/memories",
        params={"page": 1, "page_size": 2},
    )
    assert page1.status_code == 200
    data1 = page1.json()
    assert data1["total"] == 3
    assert len(data1["memories"]) == 2
    assert data1["page"] == 1
    assert data1["page_size"] == 2

    # Page 2 of size 2 should have the remaining memory
    page2 = await client.get(
        f"/api/v1/collections/{collection_id}/memories",
        params={"page": 2, "page_size": 2},
    )
    assert page2.status_code == 200
    data2 = page2.json()
    assert len(data2["memories"]) == 1
    assert data2["page"] == 2


async def test_add_memory_to_unknown_collection(client: AsyncClient):
    """POST membership on unknown collection returns 404."""
    mem_resp = await client.post(
        "/api/v1/memories",
        json={"content": "Orphan memory for membership test", "source": "claude_code"},
    )
    memory_id = mem_resp.json()["id"]
    resp = await client.post(
        "/api/v1/collections/nonexistent-id/memories",
        json={"memory_id": memory_id},
    )
    assert resp.status_code == 404
