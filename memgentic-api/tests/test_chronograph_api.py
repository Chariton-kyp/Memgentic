"""REST endpoint tests for the Chronograph routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.graph import reset_chronograph_cache
from memgentic.graph.temporal import Chronograph
from memgentic.storage.metadata import MetadataStore

from memgentic_api.routes import chronograph as chronograph_routes

EMBEDDING_DIM = 768


@pytest.fixture()
async def client(tmp_path: Path):
    """FastAPI app wired only for Chronograph routes."""
    reset_chronograph_cache()
    settings = MemgenticSettings(
        data_dir=tmp_path / "mneme_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        embedding_dimensions=EMBEDDING_DIM,
    )
    # Ensure the module-level get_chronograph lands on our tmp DB.
    cg = Chronograph(settings.data_dir / "chronograph.sqlite")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await cg.initialize()

    # Route dependency calls ``get_chronograph()`` which uses the default
    # settings-derived path. Patch the module cache so we hand back our
    # pre-initialised instance.
    from memgentic.graph import temporal as _t

    _t._instances[str(cg._db_path.resolve())] = cg

    metadata_store = MetadataStore(settings.sqlite_path)
    await metadata_store.initialize()

    app = FastAPI()
    app.state.metadata_store = metadata_store
    app.state.vector_store = AsyncMock()
    app.include_router(chronograph_routes.router, prefix="/api/v1")

    # Point the global settings at our tmp data_dir so get_chronograph()
    # inside the routes resolves to the same file.
    from memgentic import config as _cfg

    _cfg.settings.data_dir = settings.data_dir

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    await metadata_store.close()
    await cg.close()
    reset_chronograph_cache()


async def test_stats_endpoint(client: AsyncClient):
    r = await client.get("/api/v1/chronograph")
    assert r.status_code == 200
    body = r.json()
    assert body["entities"] == 0
    assert body["triples"] == 0


async def test_create_and_list_triple(client: AsyncClient):
    r = await client.post(
        "/api/v1/chronograph/triples",
        json={
            "subject": "Kai",
            "predicate": "Works On",
            "object": "Orion",
            "valid_from": "2025-06-01",
            "status": "accepted",
        },
    )
    assert r.status_code == 201
    triple = r.json()
    assert triple["predicate"] == "works_on"
    assert triple["status"] == "accepted"

    r = await client.get("/api/v1/chronograph/triples?subject=Kai")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1


async def test_validation_queue_accept_reject(client: AsyncClient):
    # Create a proposed triple
    r = await client.post(
        "/api/v1/chronograph/triples",
        json={
            "subject": "Ada",
            "predicate": "owns",
            "object": "analytical engine",
            "proposer": "llm",
            "status": "proposed",
            "confidence": 0.7,
        },
    )
    assert r.status_code == 201
    triple_id = r.json()["id"]

    # Proposed queue has it
    r = await client.get("/api/v1/chronograph/proposed")
    assert r.status_code == 200
    assert any(t["id"] == triple_id for t in r.json()["triples"])

    # Accept
    r = await client.post(f"/api/v1/chronograph/triples/{triple_id}/accept")
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert r.json()["confidence"] == 1.0


async def test_patch_triple_non_identity(client: AsyncClient):
    r = await client.post(
        "/api/v1/chronograph/triples",
        json={
            "subject": "Kai",
            "predicate": "likes",
            "object": "Python",
            "status": "proposed",
            "confidence": 0.6,
        },
    )
    triple_id = r.json()["id"]

    r = await client.patch(
        f"/api/v1/chronograph/triples/{triple_id}",
        json={"confidence": 0.95},
    )
    assert r.status_code == 200
    assert r.json()["confidence"] == pytest.approx(0.95)


async def test_invalidate_endpoint_closes_window(client: AsyncClient):
    r = await client.post(
        "/api/v1/chronograph/triples",
        json={
            "subject": "Kai",
            "predicate": "works_on",
            "object": "Orion",
            "valid_from": "2024-01-01",
            "status": "accepted",
        },
    )
    triple_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/chronograph/triples/{triple_id}/invalidate",
        json={"ended": "2026-03-01"},
    )
    assert r.status_code == 200
    assert r.json()["valid_to"] == "2026-03-01"


async def test_timeline_endpoint(client: AsyncClient):
    for from_date, obj in [("2024-01-01", "Orion"), ("2026-01-01", "Helios")]:
        await client.post(
            "/api/v1/chronograph/triples",
            json={
                "subject": "Kai",
                "predicate": "works_on",
                "object": obj,
                "valid_from": from_date,
                "status": "accepted",
            },
        )
    r = await client.get("/api/v1/chronograph/timeline?entity=Kai")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    # Chronological order: Orion (2024) before Helios (2026)
    assert [t["object"] for t in body["triples"]] == ["orion", "helios"]


async def test_missing_triple_returns_404(client: AsyncClient):
    r = await client.post("/api/v1/chronograph/triples/does-not-exist/accept")
    assert r.status_code == 404
    r = await client.patch(
        "/api/v1/chronograph/triples/does-not-exist",
        json={"confidence": 0.1},
    )
    assert r.status_code == 404
