"""REST coverage for the capture profile feature.

- POST /api/v1/memories accepts ``capture_profile`` and echoes it back.
- GET /api/v1/settings/capture-profile reports the current default.
- PUT /api/v1/settings/capture-profile persists a new default and is
  reflected on the next GET.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_memory_respects_raw_profile(client: AsyncClient):
    resp = await client.post(
        "/api/v1/memories",
        json={
            "content": "A verbatim fact that must not be enriched",
            "content_type": "fact",
            "topics": ["should-be-dropped"],
            "capture_profile": "raw",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["capture_profile"] == "raw"
    assert body["topics"] == []  # raw strips caller-provided topics


async def test_create_memory_defaults_to_enriched(client: AsyncClient):
    resp = await client.post(
        "/api/v1/memories",
        json={
            "content": "Without profile, defaults to enriched",
            "topics": ["t1"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["capture_profile"] == "enriched"
    assert body["dual_sibling_id"] is None


async def test_create_memory_dual_links_sibling(client: AsyncClient):
    resp = await client.post(
        "/api/v1/memories",
        json={
            "content": "Dual profile stores both representations",
            "capture_profile": "dual",
        },
    )
    assert resp.status_code == 201, resp.text
    primary = resp.json()
    assert primary["capture_profile"] == "dual"
    assert primary["dual_sibling_id"] is not None

    sibling = await client.get(f"/api/v1/memories/{primary['dual_sibling_id']}")
    assert sibling.status_code == 200
    sib_body = sibling.json()
    assert sib_body["capture_profile"] == "dual"
    assert sib_body["dual_sibling_id"] == primary["id"]
    # Sibling is the raw side of the pair — no enrichment metadata.
    assert sib_body["topics"] == []


async def test_capture_profile_setting_roundtrip(client: AsyncClient):
    # Default from config baseline
    get1 = await client.get("/api/v1/settings/capture-profile")
    assert get1.status_code == 200
    assert get1.json()["profile"] == "enriched"

    # Persist a change
    put = await client.put(
        "/api/v1/settings/capture-profile",
        json={"profile": "raw"},
    )
    assert put.status_code == 200
    assert put.json()["profile"] == "raw"

    # Next GET must reflect the override
    get2 = await client.get("/api/v1/settings/capture-profile")
    assert get2.status_code == 200
    assert get2.json()["profile"] == "raw"


async def test_capture_profile_setting_rejects_invalid_value(client: AsyncClient):
    resp = await client.put(
        "/api/v1/settings/capture-profile",
        json={"profile": "nope"},
    )
    assert resp.status_code == 422
