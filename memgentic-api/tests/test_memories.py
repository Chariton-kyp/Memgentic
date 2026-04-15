"""Tests for memory CRUD and search endpoints."""

from __future__ import annotations

from httpx import AsyncClient

# --- List memories ---


async def test_list_memories_empty(client: AsyncClient):
    """GET /api/v1/memories returns empty list when no memories exist."""
    resp = await client.get("/api/v1/memories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["memories"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


async def test_list_memories_with_data(seeded_client: AsyncClient):
    """GET /api/v1/memories returns seeded memories."""
    resp = await seeded_client.get("/api/v1/memories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["memories"]) == 3


async def test_list_memories_pagination(seeded_client: AsyncClient):
    """GET /api/v1/memories respects page and page_size."""
    resp = await seeded_client.get("/api/v1/memories", params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["memories"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] == 3

    # Second page should have 1 memory
    resp2 = await seeded_client.get("/api/v1/memories", params={"page": 2, "page_size": 2})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["memories"]) == 1


# --- Get single memory ---


async def test_get_memory_found(seeded_client: AsyncClient):
    """GET /api/v1/memories/{id} returns the memory when it exists."""
    memory_id = seeded_client.sample_ids[0]  # type: ignore[attr-defined]
    resp = await seeded_client.get(f"/api/v1/memories/{memory_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == memory_id
    assert "content" in data
    assert data["source"]["platform"] == "claude_code"


async def test_get_memory_not_found(client: AsyncClient):
    """GET /api/v1/memories/{id} returns 404 for unknown ID."""
    resp = await client.get("/api/v1/memories/nonexistent-id-12345")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Memory not found"


# --- Create memory ---


async def test_create_memory(client: AsyncClient):
    """POST /api/v1/memories creates and returns a new memory."""
    payload = {
        "content": "Rust ownership model prevents memory leaks",
        "content_type": "fact",
        "topics": ["rust", "memory"],
        "entities": ["Rust"],
        "source": "claude_code",
    }
    resp = await client.post("/api/v1/memories", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == payload["content"]
    assert data["content_type"] == "fact"
    assert data["platform"] == "claude_code"
    assert "rust" in data["topics"]
    assert data["id"]  # non-empty UUID


async def test_create_memory_defaults(client: AsyncClient):
    """POST /api/v1/memories uses sensible defaults for optional fields."""
    payload = {"content": "A simple fact with minimal fields"}
    resp = await client.post("/api/v1/memories", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["content_type"] == "fact"
    assert data["platform"] == "unknown"
    assert data["topics"] == []


async def test_create_memory_validation_too_short(client: AsyncClient):
    """POST /api/v1/memories rejects content shorter than 3 chars."""
    resp = await client.post("/api/v1/memories", json={"content": "ab"})
    assert resp.status_code == 422


# --- Update memory ---


async def test_update_memory_topics(seeded_client: AsyncClient):
    """PATCH /api/v1/memories/{id} updates topics."""
    memory_id = seeded_client.sample_ids[0]  # type: ignore[attr-defined]
    resp = await seeded_client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"topics": ["updated-topic"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["topics"] == ["updated-topic"]


async def test_update_memory_status(seeded_client: AsyncClient):
    """PATCH /api/v1/memories/{id} updates status."""
    memory_id = seeded_client.sample_ids[1]  # type: ignore[attr-defined]
    resp = await seeded_client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"status": "archived"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


async def test_update_memory_not_found(client: AsyncClient):
    """PATCH /api/v1/memories/{id} returns 404 for unknown ID."""
    resp = await client.patch(
        "/api/v1/memories/nonexistent-id",
        json={"topics": ["x"]},
    )
    assert resp.status_code == 404


# --- Delete (archive) memory ---


async def test_delete_memory(seeded_client: AsyncClient):
    """DELETE /api/v1/memories/{id} returns 204 and archives the memory."""
    memory_id = seeded_client.sample_ids[2]  # type: ignore[attr-defined]
    resp = await seeded_client.delete(f"/api/v1/memories/{memory_id}")
    assert resp.status_code == 204

    # Confirm the memory is now archived (GET still returns it but status=archived)
    get_resp = await seeded_client.get(f"/api/v1/memories/{memory_id}")
    # Archived memories may return 404 from the list (filtered by active),
    # but get_memory returns them since it doesn't filter by status.
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "archived"


async def test_delete_memory_not_found(client: AsyncClient):
    """DELETE /api/v1/memories/{id} returns 404 for unknown ID."""
    resp = await client.delete("/api/v1/memories/nonexistent-id")
    assert resp.status_code == 404


# --- Semantic search ---


async def test_semantic_search(seeded_client: AsyncClient):
    """POST /api/v1/memories/search returns results with scores."""
    payload = {"query": "Python indentation", "limit": 5}
    resp = await seeded_client.post("/api/v1/memories/search", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Python indentation"
    assert isinstance(data["results"], list)
    assert data["total"] == len(data["results"])
    # Each result should have memory + score
    if data["results"]:
        item = data["results"][0]
        assert "memory" in item
        assert "score" in item


async def test_semantic_search_empty_store(client: AsyncClient):
    """POST /api/v1/memories/search on empty store returns empty results."""
    payload = {"query": "anything at all", "limit": 5}
    resp = await client.post("/api/v1/memories/search", json=payload)
    assert resp.status_code == 200
    assert resp.json()["results"] == []


# --- Keyword search ---


async def test_keyword_search(seeded_client: AsyncClient):
    """POST /api/v1/memories/keyword-search returns FTS5 matches."""
    payload = {"query": "Python", "limit": 10}
    resp = await seeded_client.post("/api/v1/memories/keyword-search", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Python"
    assert isinstance(data["results"], list)
    # At least one memory mentions Python
    assert data["total"] >= 1


async def test_keyword_search_no_match(seeded_client: AsyncClient):
    """POST /api/v1/memories/keyword-search with unmatched query returns empty."""
    payload = {"query": "xyznonexistent", "limit": 10}
    resp = await seeded_client.post("/api/v1/memories/keyword-search", json=payload)
    assert resp.status_code == 200
    assert resp.json()["results"] == []


async def test_keyword_search_validation(client: AsyncClient):
    """POST /api/v1/memories/keyword-search rejects query shorter than 2 chars."""
    resp = await client.post("/api/v1/memories/keyword-search", json={"query": "x"})
    assert resp.status_code == 422
