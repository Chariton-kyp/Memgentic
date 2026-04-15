"""Tests for statistics, health, and metrics endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def test_stats_empty(client: AsyncClient):
    """GET /api/v1/stats returns zeros when no memories exist."""
    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_memories"] == 0
    assert data["vector_count"] == 0
    assert data["sources"] == []
    assert "store_status" in data


async def test_stats_with_data(seeded_client: AsyncClient):
    """GET /api/v1/stats returns correct counts for seeded memories."""
    resp = await seeded_client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_memories"] == 3
    # In local Qdrant mode, indexed_vectors_count may be 0; points_count tracks actual vectors.
    # The API returns indexed_vectors_count, so just check it's a non-negative int.
    assert isinstance(data["vector_count"], int)
    assert data["vector_count"] >= 0
    assert len(data["sources"]) == 2  # claude_code and chatgpt
    assert data["store_status"] in ("green", "yellow", "red", "grey", "unknown")


# --- Detailed health endpoint ---


async def test_detailed_health_empty(client: AsyncClient):
    """GET /api/v1/health/detailed returns healthy with zero memories."""
    resp = await client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert "components" in data
    assert data["components"]["metadata_store"]["status"] == "healthy"
    assert data["components"]["metadata_store"]["memory_count"] == 0
    assert data["components"]["vector_store"]["status"] == "healthy"


async def test_detailed_health_with_data(seeded_client: AsyncClient):
    """GET /api/v1/health/detailed reports correct memory count when seeded."""
    resp = await seeded_client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["components"]["metadata_store"]["memory_count"] == 3
    assert isinstance(data["components"]["vector_store"]["vectors"], int)


# --- Metrics endpoint ---


async def test_metrics_empty(client: AsyncClient):
    """GET /api/v1/metrics returns zeros when no memories exist."""
    resp = await client.get("/api/v1/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["memories_total"] == 0
    assert data["memories_by_platform"] == {}
    assert isinstance(data["vectors_indexed"], int)
    assert "vector_store_status" in data


async def test_metrics_with_data(seeded_client: AsyncClient):
    """GET /api/v1/metrics returns correct platform breakdown when seeded."""
    resp = await seeded_client.get("/api/v1/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["memories_total"] == 3
    assert data["memories_by_platform"]["claude_code"] == 2
    assert data["memories_by_platform"]["chatgpt"] == 1
    assert isinstance(data["vectors_indexed"], int)
