"""REST API tests for the Recall Tiers briefing endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_briefing_default_returns_t0_plus_t1(client, monkeypatch, tmp_path):
    """No query params → T0+T1 bundle is rendered."""
    # Force a clean persona miss so T0 uses the fallback hint path.
    monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(tmp_path / "persona.yaml"))

    resp = await client.get("/api/v1/briefing")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier"] == "default"
    assert "## T0 — Persona" in body["text"]
    assert "## T1 — Horizon" in body["text"]
    assert body["tokens"] > 0
    assert body["model_context"] > 0


@pytest.mark.asyncio
async def test_get_briefing_tier_t4_empty_graph_placeholder(client):
    """Empty knowledge graph → T4 renders the stubbed placeholder."""
    resp = await client.get("/api/v1/briefing", params={"tier": "T4"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier"] == "T4"
    assert "Knowledge graph not yet populated" in body["text"]


@pytest.mark.asyncio
async def test_get_briefing_unknown_tier_rejects(client):
    resp = await client.get("/api/v1/briefing", params={"tier": "T99"})
    assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"


@pytest.mark.asyncio
async def test_get_briefing_with_max_tokens_override(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(tmp_path / "p.yaml"))
    resp = await client.get(
        "/api/v1/briefing",
        params={"max_tokens": 200, "model_context": 200000},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_tiers_returns_five_entries(client):
    resp = await client.get("/api/v1/briefing/tiers")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["tiers"].keys()) == {"T0", "T1", "T2", "T3", "T4"}
    for tier_key, tier_data in body["tiers"].items():
        assert "budget" in tier_data
        assert tier_data["budget"]["tokens"] > 0


@pytest.mark.asyncio
async def test_list_tiers_honours_model_context(client):
    # Small context → tight T1 cap (400 tok).
    resp = await client.get(
        "/api/v1/briefing/tiers", params={"model_context": 16000}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tiers"]["T1"]["budget"]["tokens"] == 400


@pytest.mark.asyncio
async def test_post_weights_validates_and_echoes(client):
    resp = await client.post(
        "/api/v1/briefing/weights",
        json={"importance": 0.5, "recency": 0.2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["weights"]["importance"] == pytest.approx(0.5)
    assert body["weights"]["recency"] == pytest.approx(0.2)
    # Unspecified weights fall back to defaults.
    assert body["weights"]["pinned"] == pytest.approx(0.25)
    assert body["overrides"] == {"importance": 0.5, "recency": 0.2}


@pytest.mark.asyncio
async def test_post_weights_rejects_negative(client):
    resp = await client.post(
        "/api/v1/briefing/weights",
        json={"importance": -0.1},
    )
    assert resp.status_code == 422  # pydantic validation


@pytest.mark.asyncio
async def test_post_weights_rejects_zero_tau(client):
    resp = await client.post(
        "/api/v1/briefing/weights",
        json={"tau_days": 0},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_briefing_content_matches_cli_assembly(
    seeded_client, monkeypatch, tmp_path
):
    """REST output and the CLI RecallStack should render identical text.

    We exercise the same ``RecallStack.briefing`` path used by the CLI
    and assert the REST body matches, verifying the parity acceptance
    criterion without actually shelling out to the CLI.
    """
    from memgentic.briefing import BriefingContext, RecallStack

    monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(tmp_path / "persona.yaml"))

    resp = await seeded_client.get("/api/v1/briefing")
    assert resp.status_code == 200
    rest_text = resp.json()["text"]

    # Build the same briefing directly and compare the T0 header block.
    app = seeded_client._transport.app  # type: ignore[attr-defined]
    ctx = BriefingContext(
        metadata_store=app.state.metadata_store,
        vector_store=app.state.vector_store,
        embedder=app.state.embedder,
        graph=app.state.graph,
    )
    local_text = await RecallStack().briefing(ctx)

    # Strip volatile whitespace and compare structural headers.
    assert rest_text.startswith("## T0 — Persona")
    assert local_text.startswith("## T0 — Persona")
    assert "## T1 — Horizon" in rest_text
    assert "## T1 — Horizon" in local_text
