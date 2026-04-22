"""Tests for ``memgentic/daemon/watcher_state.py``.

Verifies that :class:`WatcherStateStore` tracks per-file offsets, enable
flags, errors, and tail logs correctly under realistic multi-tool usage.
"""

from __future__ import annotations

from pathlib import Path

from memgentic.daemon.watcher_state import WatcherStateStore


def test_store_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "watcher_state.sqlite"
    WatcherStateStore(db)
    assert db.exists()


def test_offset_roundtrip(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    assert store.get_offset("gemini_cli", "sess-1", "/tmp/a.json") == 0

    store.update_state(
        tool="gemini_cli",
        session_id="sess-1",
        file_path="/tmp/a.json",
        new_offset=1024,
        captured_increment=2,
    )

    assert store.get_offset("gemini_cli", "sess-1", "/tmp/a.json") == 1024

    store.update_state(
        tool="gemini_cli",
        session_id="sess-1",
        file_path="/tmp/a.json",
        new_offset=2048,
        captured_increment=1,
    )
    assert store.get_offset("gemini_cli", "sess-1", "/tmp/a.json") == 2048
    assert store.total_captured("gemini_cli") == 3


def test_reset_file_clears_offset(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    store.update_state(
        tool="aider",
        session_id="proj",
        file_path="/tmp/.aider.chat.history.md",
        new_offset=500,
        captured_increment=1,
    )
    store.reset_file("aider", "proj", "/tmp/.aider.chat.history.md")
    assert store.get_offset("aider", "proj", "/tmp/.aider.chat.history.md") == 0


def test_status_upsert_and_enable(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    assert store.get_status("claude_code") is None

    store.upsert_status("claude_code", enabled=True)
    status = store.get_status("claude_code")
    assert status is not None and status.enabled is True

    store.set_enabled("claude_code", False)
    status = store.get_status("claude_code")
    assert status is not None and status.enabled is False

    store.upsert_status("claude_code", enabled=True, clear_error=True)
    status = store.get_status("claude_code")
    assert status is not None and status.enabled is True and status.last_error is None


def test_error_recording(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    store.record_error("gemini_cli", "boom")
    status = store.get_status("gemini_cli")
    assert status is not None
    assert status.last_error == "boom"
    assert status.last_error_at is not None


def test_remove_tool_is_complete(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    store.upsert_status("aider", enabled=True)
    store.update_state(
        tool="aider",
        session_id="p",
        file_path="/tmp/x",
        new_offset=10,
        captured_increment=1,
    )
    store.append_log("aider", "hello")
    store.remove_tool("aider")
    assert store.get_status("aider") is None
    assert store.list_states("aider") == []
    assert store.tail_logs("aider") == []


def test_logs_ring_is_bounded(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    for i in range(550):
        store.append_log("claude_code", f"entry {i}")
    entries = store.tail_logs("claude_code", limit=600)
    assert len(entries) <= 500
    # Most recent first
    assert entries[0].message.startswith("entry 549")


def test_list_statuses_sorted(tmp_path: Path) -> None:
    store = WatcherStateStore(tmp_path / "w.db")
    store.upsert_status("aider", enabled=True)
    store.upsert_status("claude_code", enabled=False)
    tools = [s.tool for s in store.list_statuses()]
    assert tools == sorted(tools)
