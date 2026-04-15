"""Tests for health check endpoint."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health_check(client: AsyncClient):
    """GET /api/v1/health returns 200 with version and status."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert "storage_backend" in data
