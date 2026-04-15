"""Tests for ingestion job endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def test_list_ingestion_jobs_empty(client: AsyncClient):
    """GET /api/v1/ingestion/jobs returns an empty list when no jobs exist."""
    resp = await client.get("/api/v1/ingestion/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["jobs"] == []
    assert data["total"] == 0


async def test_get_ingestion_job_not_found(client: AsyncClient):
    """GET /api/v1/ingestion/jobs/{id} returns 404 for unknown job ID."""
    resp = await client.get("/api/v1/ingestion/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ingestion job not found"


async def test_cancel_ingestion_job_not_found(client: AsyncClient):
    """POST /api/v1/ingestion/jobs/{id}/cancel returns 404 for unknown job ID."""
    resp = await client.post("/api/v1/ingestion/jobs/does-not-exist/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Ingestion job not found"


async def test_list_ingestion_jobs_pagination(client: AsyncClient):
    """GET /api/v1/ingestion/jobs accepts limit and offset query params."""
    resp = await client.get(
        "/api/v1/ingestion/jobs",
        params={"limit": 10, "offset": 0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "total" in data
