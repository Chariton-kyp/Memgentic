"""Tests for batch memory update and delete endpoints."""

from __future__ import annotations

from httpx import AsyncClient

# Semantically DISTINCT contents — write-time dedup (cosine>0.90 AND high text
# overlap) collapses near-identical inserts, so seed memories must differ in
# substance, not just an index, for batch/pagination tests to see N rows.
_DISTINCT_CONTENTS = [
    "Postgres uses MVCC to isolate concurrent transactions",
    "React reconciles the UI through a virtual DOM diff",
    "Kubernetes bin-packs pods onto nodes by their resource requests",
    "Rust's borrow checker enforces memory safety at compile time",
    "GraphQL lets a client request exactly the fields it needs",
    "Redis persists data with RDB snapshots and the append-only log",
]


async def _seed_memories(client: AsyncClient, count: int = 3) -> list[str]:
    """Create ``count`` distinct memories and return their IDs."""
    ids: list[str] = []
    for i in range(count):
        resp = await client.post(
            "/api/v1/memories",
            json={
                "content": _DISTINCT_CONTENTS[i % len(_DISTINCT_CONTENTS)],
                "source": "claude_code",
                "topics": ["seed"],
            },
        )
        assert resp.status_code == 201
        ids.append(resp.json()["id"])
    return ids


async def test_batch_update_status(client: AsyncClient):
    """POST /api/v1/memories/batch-update archives multiple memories."""
    ids = await _seed_memories(client, count=3)

    resp = await client.post(
        "/api/v1/memories/batch-update",
        json={
            "memory_ids": ids,
            "updates": {"status": "archived"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 3

    # Verify each memory is now archived
    for memory_id in ids:
        get_resp = await client.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "archived"


async def test_batch_update_topics(client: AsyncClient):
    """POST /api/v1/memories/batch-update rewrites topics on multiple memories."""
    ids = await _seed_memories(client, count=2)

    resp = await client.post(
        "/api/v1/memories/batch-update",
        json={
            "memory_ids": ids,
            "updates": {"topics": ["batch", "updated"]},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    for memory_id in ids:
        get_resp = await client.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["topics"] == ["batch", "updated"]


async def test_batch_update_invalid_status(client: AsyncClient):
    """POST /api/v1/memories/batch-update rejects an invalid status."""
    ids = await _seed_memories(client, count=1)
    resp = await client.post(
        "/api/v1/memories/batch-update",
        json={
            "memory_ids": ids,
            "updates": {"status": "not-a-real-status"},
        },
    )
    assert resp.status_code == 422


async def test_batch_delete(client: AsyncClient):
    """POST /api/v1/memories/batch-delete archives all requested memories."""
    ids = await _seed_memories(client, count=3)

    resp = await client.post(
        "/api/v1/memories/batch-delete",
        json={"memory_ids": ids},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 3

    for memory_id in ids:
        get_resp = await client.get(f"/api/v1/memories/{memory_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "archived"


async def test_batch_delete_empty_body(client: AsyncClient):
    """POST /api/v1/memories/batch-delete with an empty ID list returns 422."""
    resp = await client.post(
        "/api/v1/memories/batch-delete",
        json={"memory_ids": []},
    )
    assert resp.status_code == 422
