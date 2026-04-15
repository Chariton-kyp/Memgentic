"""Tests for import/export endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def test_import_json(client: AsyncClient):
    """POST /api/v1/import/json imports multiple memories."""
    payload = {
        "memories": [
            {
                "content": "Go uses goroutines for concurrency",
                "content_type": "fact",
                "topics": ["go", "concurrency"],
                "entities": ["Go"],
                "source": "claude_code",
            },
            {
                "content": "Docker containers share the host kernel",
                "content_type": "learning",
                "topics": ["docker", "containers"],
                "entities": ["Docker"],
                "source": "chatgpt",
            },
        ]
    }
    resp = await client.post("/api/v1/import/json", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["imported"] == 2
    assert data["errors"] == 0
    assert data["total"] == 2

    # Verify they appear in the list
    list_resp = await client.get("/api/v1/memories")
    assert list_resp.json()["total"] == 2


async def test_import_json_empty(client: AsyncClient):
    """POST /api/v1/import/json with empty array imports nothing."""
    resp = await client.post("/api/v1/import/json", json={"memories": []})
    assert resp.status_code == 201
    data = resp.json()
    assert data["imported"] == 0
    assert data["total"] == 0


async def test_export_json_empty(client: AsyncClient):
    """GET /api/v1/export returns empty list when no memories exist."""
    resp = await client.get("/api/v1/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["memories"] == []


async def test_export_json_with_data(seeded_client: AsyncClient):
    """GET /api/v1/export returns all seeded memories."""
    resp = await seeded_client.get("/api/v1/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert len(data["memories"]) == 3

    # Each exported memory should have required fields
    mem = data["memories"][0]
    assert "id" in mem
    assert "content" in mem
    assert "content_type" in mem
    assert "platform" in mem
    assert "capture_method" in mem
    assert "topics" in mem
    assert "created_at" in mem


async def test_import_then_export_roundtrip(client: AsyncClient):
    """Import memories, then export and verify they match."""
    import_payload = {
        "memories": [
            {
                "content": "TypeScript adds static typing to JavaScript",
                "content_type": "fact",
                "topics": ["typescript"],
                "entities": ["TypeScript", "JavaScript"],
                "source": "claude_code",
            },
        ]
    }
    import_resp = await client.post("/api/v1/import/json", json=import_payload)
    assert import_resp.json()["imported"] == 1

    export_resp = await client.get("/api/v1/export")
    data = export_resp.json()
    assert data["count"] == 1
    assert data["memories"][0]["content"] == "TypeScript adds static typing to JavaScript"
