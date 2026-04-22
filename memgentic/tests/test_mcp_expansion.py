"""Tests for the expansion-pass MCP tools.

Covers the four tools added after the Recall Tiers / Watchers / Chronograph
waves landed: dedupe check, overview, refresh, watchers status.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from memgentic.mcp.formatters import preview_text
from memgentic.mcp.schemas import (
    DedupeCheckInput,
    OverviewInput,
    WatchersStatusInput,
)
from memgentic.mcp.server import (
    memgentic_dedupe_check,
    memgentic_overview,
    memgentic_refresh,
    memgentic_watchers_status,
)

DIMS = 768


def _fake_embedding() -> list[float]:
    return [0.1 + i * 0.0001 for i in range(DIMS)]


def _mock_ctx(**overrides) -> MagicMock:
    state = {
        "metadata_store": overrides.get("metadata_store") or AsyncMock(),
        "vector_store": overrides.get("vector_store") or AsyncMock(),
        "embedder": overrides.get("embedder") or AsyncMock(),
        "pipeline": overrides.get("pipeline") or AsyncMock(),
        "graph": overrides.get("graph") or None,
    }
    ctx = MagicMock()
    ctx.request_context.lifespan_context = state
    return ctx


# --- schemas ---------------------------------------------------------------


def test_dedupe_check_schema_rejects_short_content():
    with pytest.raises(ValidationError):
        DedupeCheckInput(content="ab")


def test_dedupe_check_schema_rejects_unknown_scope():
    with pytest.raises(ValidationError):
        DedupeCheckInput(content="hello world", scope="workspace")


def test_dedupe_check_schema_rejects_threshold_out_of_range():
    with pytest.raises(ValidationError):
        DedupeCheckInput(content="hello world", threshold=1.5)


def test_overview_schema_rejects_zero_top_topics_limit():
    with pytest.raises(ValidationError):
        OverviewInput(top_topics_limit=0)


def test_watchers_status_schema_rejects_extra_fields():
    with pytest.raises(ValidationError):
        WatchersStatusInput(tool="claude_code")  # type: ignore[call-arg]


# --- memgentic_dedupe_check ------------------------------------------------


async def test_dedupe_check_flags_high_similarity():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    vector_store = AsyncMock()
    vector_store.search.return_value = [
        {
            "id": "mem-1",
            "score": 0.95,
            "payload": {"content": "Python uses indentation", "platform": "claude_code"},
        },
        {
            "id": "mem-2",
            "score": 0.62,
            "payload": {"content": "unrelated", "platform": "codex_cli"},
        },
    ]
    ctx = _mock_ctx(embedder=embedder, vector_store=vector_store)

    result = await memgentic_dedupe_check(
        DedupeCheckInput(content="Python uses indentation", threshold=0.90), ctx
    )

    assert result["is_duplicate"] is True
    assert result["threshold"] == 0.90
    assert len(result["matches"]) == 1
    assert result["matches"][0]["id"] == "mem-1"
    assert result["matches"][0]["similarity"] == 0.95
    assert result["matches"][0]["source"] == "claude_code"


async def test_dedupe_check_returns_empty_when_below_threshold():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    vector_store = AsyncMock()
    vector_store.search.return_value = [
        {
            "id": "mem-a",
            "score": 0.40,
            "payload": {"content": "far apart", "platform": "chatgpt"},
        }
    ]
    ctx = _mock_ctx(embedder=embedder, vector_store=vector_store)

    result = await memgentic_dedupe_check(
        DedupeCheckInput(content="brand new idea", threshold=0.90), ctx
    )

    assert result["is_duplicate"] is False
    assert result["matches"] == []


async def test_dedupe_check_handles_embedder_failure():
    embedder = AsyncMock()
    embedder.embed.side_effect = RuntimeError("ollama down")
    ctx = _mock_ctx(embedder=embedder)

    result = await memgentic_dedupe_check(DedupeCheckInput(content="something"), ctx)

    assert "error" in result


# --- memgentic_overview ----------------------------------------------------


async def test_overview_aggregates_counts(monkeypatch):
    metadata_store = AsyncMock()
    metadata_store.get_total_count.return_value = 42
    metadata_store.get_source_stats.return_value = {"claude_code": 30, "codex_cli": 12}
    coll = SimpleNamespace(id="c1", name="Work")
    metadata_store.get_collections.return_value = [coll]
    metadata_store.get_collection_memory_count.return_value = 9

    # Stub the internal async _db used by the top-topics aggregator.
    db = MagicMock()
    rows_cursor = AsyncMock()
    rows_cursor.fetchall = AsyncMock(return_value=[['["python", "auth"]'], ['["python"]']])
    db.execute = AsyncMock(return_value=rows_cursor)
    metadata_store._db = db

    # Force a deterministic storage_mb without touching settings.sqlite_path
    # (it's a computed property with no setter).
    monkeypatch.setattr("memgentic.mcp.server._path_size_mb", lambda _path: 2.0)

    # Stub the watcher store so the test doesn't touch ~/.memgentic.
    class _DummyStatus:
        enabled = True

    class _DummyStore:
        def get_status(self, tool):  # noqa: D401 - test double
            return _DummyStatus() if tool == "claude_code" else None

    monkeypatch.setattr("memgentic.daemon.watcher_state.WatcherStateStore", lambda: _DummyStore())
    monkeypatch.setattr("memgentic.daemon.watchers.ALL_TOOLS", ["claude_code", "codex_cli"])

    ctx = _mock_ctx(metadata_store=metadata_store)
    result = await memgentic_overview(OverviewInput(), ctx)

    assert result["total_memories"] == 42
    assert result["sources"] == {"claude_code": 30, "codex_cli": 12}
    assert result["collections"] == {"Work": 9}
    assert result["top_topics"][0] == {"topic": "python", "count": 2}
    assert result["storage_mb"] == 2.0
    assert result["watchers_active"] == 1
    assert "capture_profile_default" in result


# --- memgentic_refresh -----------------------------------------------------


async def test_refresh_rehydrates_capture_profile(monkeypatch):
    metadata_store = AsyncMock()
    metadata_store.get_runtime_setting.return_value = "dual"
    monkeypatch.setattr("memgentic.config.settings.default_capture_profile", "enriched")

    ctx = _mock_ctx(metadata_store=metadata_store)
    result = await memgentic_refresh(ctx)

    assert result["refreshed"] is True
    assert "reopened_at" in result
    from memgentic.config import settings as live_settings

    assert live_settings.default_capture_profile == "dual"


async def test_refresh_ignores_unknown_profile(monkeypatch):
    metadata_store = AsyncMock()
    metadata_store.get_runtime_setting.return_value = "bogus"
    monkeypatch.setattr("memgentic.config.settings.default_capture_profile", "raw")

    ctx = _mock_ctx(metadata_store=metadata_store)
    result = await memgentic_refresh(ctx)

    assert result["refreshed"] is True
    from memgentic.config import settings as live_settings

    assert live_settings.default_capture_profile == "raw"


# --- memgentic_watchers_status --------------------------------------------


async def test_watchers_status_filters_disabled_when_asked(monkeypatch):
    """``include_disabled=False`` must hide both uninstalled and installed-but-disabled rows."""

    class _Status:
        def __init__(self, enabled):
            self.enabled = enabled
            self.installed_at = "2026-04-20T00:00:00+00:00"
            self.last_error = None
            self.last_error_at = None

    class _Store:
        def get_status(self, tool):
            if tool == "claude_code":
                return _Status(True)
            if tool == "codex_cli":
                return _Status(False)  # installed but disabled
            return None  # uninstalled

        def total_captured(self, tool):
            return 0

        def last_captured_at(self, tool):
            return None

    monkeypatch.setattr("memgentic.daemon.watcher_state.WatcherStateStore", lambda: _Store())
    monkeypatch.setattr(
        "memgentic.daemon.watchers.ALL_TOOLS",
        ["claude_code", "codex_cli", "gemini_cli"],
    )
    monkeypatch.setattr("memgentic.daemon.watchers.classify_tool", lambda tool: "hook")

    ctx = _mock_ctx()
    result = await memgentic_watchers_status(WatchersStatusInput(include_disabled=False), ctx)
    names = [w["tool"] for w in result["watchers"]]
    assert names == ["claude_code"]  # disabled codex_cli + uninstalled gemini_cli hidden


async def test_watchers_status_reports_installed_tools(monkeypatch):
    class _Status:
        def __init__(self, enabled):
            self.enabled = enabled
            self.installed_at = "2026-04-20T00:00:00+00:00"
            self.last_error = None
            self.last_error_at = None

    class _Store:
        def get_status(self, tool):
            return _Status(True) if tool == "claude_code" else None

        def total_captured(self, tool):
            return 10 if tool == "claude_code" else 0

        def last_captured_at(self, tool):
            return "2026-04-21T00:00:00+00:00" if tool == "claude_code" else None

    monkeypatch.setattr("memgentic.daemon.watcher_state.WatcherStateStore", lambda: _Store())
    monkeypatch.setattr("memgentic.daemon.watchers.ALL_TOOLS", ["claude_code", "codex_cli"])
    monkeypatch.setattr("memgentic.daemon.watchers.classify_tool", lambda tool: "hook")

    ctx = _mock_ctx()

    # include_disabled=False filters out uninstalled rows.
    result = await memgentic_watchers_status(WatchersStatusInput(include_disabled=False), ctx)
    assert [w["tool"] for w in result["watchers"]] == ["claude_code"]

    # include_disabled=True (default) returns all rows.
    result_all = await memgentic_watchers_status(WatchersStatusInput(), ctx)
    assert len(result_all["watchers"]) == 2


# --- doc freshness ---------------------------------------------------------


def test_mcp_docs_are_fresh():
    """Generator output must match committed docs/MCP-TOOLS.md."""
    import asyncio
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    script_dir = repo_root / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        import generate_mcp_docs as gen  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(script_dir))

    tools = asyncio.run(gen._collect_tools())
    generated = gen.render(tools)
    on_disk = (repo_root / "docs" / "MCP-TOOLS.md").read_text(encoding="utf-8")
    assert on_disk == generated, (
        "docs/MCP-TOOLS.md is stale. Run: python scripts/generate_mcp_docs.py"
    )


# --- formatter sanity ------------------------------------------------------


def test_preview_text_truncates_with_ellipsis():
    text = "abc " * 200
    preview = preview_text(text, length=50)
    assert len(preview) == 50
    assert preview.endswith("…")


def test_preview_text_handles_none():
    assert preview_text(None) == ""
