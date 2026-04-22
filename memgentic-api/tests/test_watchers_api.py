"""Tests for the /api/v1/watchers REST endpoints.

The REST layer is a thin wrapper over WatcherStateStore, so we redirect
``Path.home()`` onto a tmp dir and drive the API entirely through httpx.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def isolate_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


async def test_list_watchers_reports_every_known_tool(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/watchers")
    assert resp.status_code == 200
    data = resp.json()
    tools = {w["tool"] for w in data["watchers"]}
    for expected in (
        "claude_code",
        "codex",
        "gemini_cli",
        "aider",
        "antigravity",
        "copilot_cli",
        "cursor",
        "opencode",
        "chatgpt",
        "claude_web",
    ):
        assert expected in tools


async def test_install_then_toggle_enabled(client: AsyncClient) -> None:
    # gemini_cli is a file watcher — install just flips the enabled flag.
    install_resp = await client.post("/api/v1/watchers/gemini_cli/install")
    assert install_resp.status_code == 200
    body = install_resp.json()
    assert body["tool"] == "gemini_cli"
    assert body["changed"] is True

    detail = await client.get("/api/v1/watchers/gemini_cli")
    assert detail.status_code == 200
    assert detail.json()["enabled"] is True

    patch = await client.patch(
        "/api/v1/watchers/gemini_cli",
        json={"enabled": False},
    )
    assert patch.status_code == 200
    assert patch.json()["enabled"] is False


async def test_claude_code_install_is_idempotent(client: AsyncClient, tmp_path: Path) -> None:
    r1 = await client.post("/api/v1/watchers/claude_code/install")
    r2 = await client.post("/api/v1/watchers/claude_code/install")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["changed"] is True
    assert r2.json()["changed"] is False


async def test_uninstall_claude_code(client: AsyncClient) -> None:
    await client.post("/api/v1/watchers/claude_code/install")
    resp = await client.post("/api/v1/watchers/claude_code/uninstall")
    assert resp.status_code == 200

    detail = await client.get("/api/v1/watchers/claude_code")
    assert detail.status_code == 200
    assert detail.json()["installed"] is False


async def test_install_rejects_mcp_only_tool(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/watchers/cursor/install")
    assert resp.status_code == 400


async def test_logs_endpoint_returns_empty_list(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/watchers/aider/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "aider"
    assert body["entries"] == []


async def test_detail_404_for_unknown(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/watchers/not_a_tool")
    assert resp.status_code == 404
