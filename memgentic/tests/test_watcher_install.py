"""Tests for ``memgentic watchers install`` / ``uninstall``.

We redirect the home-directory-resolving helpers onto a ``tmp_path`` so
the tests never touch the user's real Claude Code / Codex settings file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memgentic.daemon.watcher_install import (
    InstallResult,
    install,
    uninstall,
)
from memgentic.daemon.watcher_state import WatcherStateStore


@pytest.fixture()
def isolate_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point every ``Path.home()`` lookup at a temp dir."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def store(tmp_path: Path) -> WatcherStateStore:
    return WatcherStateStore(tmp_path / "watcher_state.sqlite")


def test_claude_code_install_is_idempotent(isolate_home: Path, store: WatcherStateStore) -> None:
    settings_path = isolate_home / ".claude" / "settings.json"

    r1 = install("claude_code", store)
    assert isinstance(r1, InstallResult)
    assert r1.changed is True
    assert settings_path.exists()

    r2 = install("claude_code", store)
    assert r2.changed is False
    assert "already installed" in r2.message.lower() or "already" in r2.message.lower()

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data["hooks"]
    # Each event should have exactly one memgentic entry.
    for event in ("Stop", "PreCompact", "SessionStart"):
        matchers = hooks[event]
        memgentic_entries = [
            h
            for matcher in matchers
            for h in matcher.get("hooks", [])
            if "memgentic" in h.get("command", "")
        ]
        assert len(memgentic_entries) == 1

    status = store.get_status("claude_code")
    assert status is not None and status.enabled is True


def test_claude_code_preserves_user_hooks(isolate_home: Path, store: WatcherStateStore) -> None:
    settings_path = isolate_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo user-stop"}]}]}}
        ),
        encoding="utf-8",
    )

    install("claude_code", store)
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    stop_entries = [
        h.get("command", "") for matcher in data["hooks"]["Stop"] for h in matcher.get("hooks", [])
    ]
    assert any("user-stop" in cmd for cmd in stop_entries)
    assert any("memgentic" in cmd for cmd in stop_entries)


def test_claude_code_uninstall_removes_only_memgentic(
    isolate_home: Path, store: WatcherStateStore
) -> None:
    settings_path = isolate_home / ".claude" / "settings.json"
    install("claude_code", store)
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo keep-me"}]})
    settings_path.write_text(json.dumps(data), encoding="utf-8")

    result = uninstall("claude_code", store)
    assert result.changed is True

    data2 = json.loads(settings_path.read_text(encoding="utf-8"))
    commands = [
        h.get("command", "")
        for matcher in data2.get("hooks", {}).get("Stop", [])
        for h in matcher.get("hooks", [])
    ]
    assert any("keep-me" in cmd for cmd in commands)
    assert not any("memgentic" in cmd for cmd in commands)
    assert store.get_status("claude_code") is None


def test_codex_install_and_uninstall(isolate_home: Path, store: WatcherStateStore) -> None:
    codex_path = isolate_home / ".codex" / "hooks.json"

    install("codex", store)
    assert codex_path.exists()

    # Idempotent
    r2 = install("codex", store)
    assert r2.changed is False

    data = json.loads(codex_path.read_text(encoding="utf-8"))
    entries = data["hooks"]
    assert any(e.get("event") == "Stop" and "memgentic" in e.get("command", "") for e in entries)
    assert any(
        e.get("event") == "PreCompact" and "memgentic" in e.get("command", "") for e in entries
    )

    # Add a user-defined entry, then uninstall, then verify it survives.
    data["hooks"].append({"event": "Stop", "command": "echo ours"})
    codex_path.write_text(json.dumps(data), encoding="utf-8")

    result = uninstall("codex", store)
    assert result.changed is True
    data_after = json.loads(codex_path.read_text(encoding="utf-8"))
    remaining = [e for e in data_after["hooks"] if "memgentic" not in e.get("command", "")]
    assert len(remaining) == 1
    assert remaining[0]["command"] == "echo ours"


def test_file_watcher_install_flips_flag(isolate_home: Path, store: WatcherStateStore) -> None:
    result = install("gemini_cli", store)
    assert result.changed is True
    status = store.get_status("gemini_cli")
    assert status is not None and status.enabled is True

    uninstall("gemini_cli", store)
    assert store.get_status("gemini_cli") is None


def test_unknown_tool_is_reported(store: WatcherStateStore) -> None:
    result = install("unknown_tool_xyz", store)
    assert result.changed is False
    assert "unknown" in result.message.lower()
