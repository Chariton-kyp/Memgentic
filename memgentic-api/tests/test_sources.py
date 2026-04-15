"""Tests for source platform endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def test_list_sources_empty(client: AsyncClient):
    """GET /api/v1/sources returns empty sources when no memories exist."""
    resp = await client.get("/api/v1/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sources"] == []
    assert data["total"] == 0


async def test_list_sources_with_data(seeded_client: AsyncClient):
    """GET /api/v1/sources returns per-platform stats for seeded memories."""
    resp = await seeded_client.get("/api/v1/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3

    platforms = {s["platform"] for s in data["sources"]}
    assert "claude_code" in platforms
    assert "chatgpt" in platforms

    # claude_code has 2 memories, chatgpt has 1
    for src in data["sources"]:
        if src["platform"] == "claude_code":
            assert src["count"] == 2
        elif src["platform"] == "chatgpt":
            assert src["count"] == 1

    # Percentages should sum to ~100
    total_pct = sum(s["percentage"] for s in data["sources"])
    assert 99.0 <= total_pct <= 101.0
