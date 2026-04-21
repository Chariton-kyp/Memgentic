"""Tests for the ``/api/v1/persona`` endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from memgentic.persona.loader import PERSONA_ENV_VAR
from memgentic.persona.schema import IdentityBlock, Persona


@pytest.fixture(autouse=True)
def _isolated_persona(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the persona path to a tmp file so tests don't touch $HOME."""
    target = tmp_path / "persona.yaml"
    monkeypatch.setenv(PERSONA_ENV_VAR, str(target))
    return target


async def test_get_persona_returns_default_when_missing(client: AsyncClient):
    resp = await client.get("/api/v1/persona")
    assert resp.status_code == 200
    data = resp.json()
    assert data["identity"]["name"] == "Assistant"
    assert data["version"] == 1


async def test_put_persona_validates_and_persists(client: AsyncClient):
    body = {
        "identity": {"name": "Atlas", "role": "AI for Alice"},
        "people": [{"name": "Alice", "relationship": "creator"}],
    }
    resp = await client.put("/api/v1/persona", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["identity"]["name"] == "Atlas"
    assert data["metadata"]["generated_by"] == "edited"

    # Round-trips
    resp2 = await client.get("/api/v1/persona")
    assert resp2.status_code == 200
    assert resp2.json()["identity"]["name"] == "Atlas"


async def test_put_persona_400_on_invalid_body(client: AsyncClient):
    resp = await client.put("/api/v1/persona", json={"identity": {}})
    assert resp.status_code == 400


async def test_put_persona_400_on_unknown_field(client: AsyncClient):
    resp = await client.put(
        "/api/v1/persona",
        json={"identity": {"name": "Atlas"}, "bogus_field": "x"},
    )
    assert resp.status_code == 400


async def test_patch_persona_merges_nested(client: AsyncClient):
    await client.put(
        "/api/v1/persona",
        json={"identity": {"name": "Atlas", "tone": "warm"}},
    )
    resp = await client.patch(
        "/api/v1/persona",
        json={"identity": {"role": "AI for Alice"}},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["identity"]["name"] == "Atlas"
    assert data["identity"]["tone"] == "warm"
    assert data["identity"]["role"] == "AI for Alice"


async def test_patch_persona_null_deletes_key(client: AsyncClient):
    await client.put(
        "/api/v1/persona",
        json={"identity": {"name": "Atlas", "tone": "warm"}},
    )
    resp = await client.patch(
        "/api/v1/persona",
        json={"identity": {"tone": None}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["identity"].get("tone") is None


async def test_bootstrap_returns_proposed_persona(client: AsyncClient):
    fake = Persona(identity=IdentityBlock(name="Atlas"))
    with patch(
        "memgentic_api.routes.persona.persona_bootstrap",
        new=AsyncMock(return_value=fake),
    ):
        resp = await client.post("/api/v1/persona/bootstrap", json={"source": "recent"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["persona"]["identity"]["name"] == "Atlas"


async def test_bootstrap_503_when_llm_unavailable(client: AsyncClient):
    with patch(
        "memgentic_api.routes.persona.persona_bootstrap",
        new=AsyncMock(return_value=None),
    ):
        resp = await client.post("/api/v1/persona/bootstrap", json={})
    assert resp.status_code == 503


async def test_bootstrap_accept_persists(client: AsyncClient):
    body = {"persona": {"identity": {"name": "Atlas"}}}
    resp = await client.post("/api/v1/persona/bootstrap/accept", json=body)
    assert resp.status_code == 200
    assert resp.json()["metadata"]["generated_by"] == "bootstrap"

    # Verify the persisted file reflects this
    resp2 = await client.get("/api/v1/persona")
    assert resp2.json()["identity"]["name"] == "Atlas"


async def test_bootstrap_accept_400_on_invalid(client: AsyncClient):
    resp = await client.post(
        "/api/v1/persona/bootstrap/accept",
        json={"persona": {"identity": {}}},
    )
    assert resp.status_code == 400


async def test_persona_schema_returns_json_schema(client: AsyncClient):
    resp = await client.get("/api/v1/persona/schema")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["title"] == "Persona"
    assert "properties" in schema
    assert "identity" in schema["properties"]
