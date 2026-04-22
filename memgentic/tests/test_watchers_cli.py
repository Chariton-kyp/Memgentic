"""Smoke tests for the ``memgentic watchers`` CLI subgroup."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from memgentic.cli import main
from memgentic.daemon.watcher_state import WatcherStateStore


@pytest.fixture()
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_watchers_status_renders(isolated_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["watchers", "status"])
    assert result.exit_code == 0
    # Every known tool name should appear somewhere in the rendered table.
    for tool in ("claude_code", "codex", "gemini_cli", "aider", "antigravity"):
        assert tool in result.output


def test_watchers_install_and_uninstall_idempotent(isolated_home: Path) -> None:
    runner = CliRunner()

    r1 = runner.invoke(main, ["watchers", "install", "--tool", "claude_code"])
    assert r1.exit_code == 0
    assert "claude_code" in r1.output

    r2 = runner.invoke(main, ["watchers", "install", "--tool", "claude_code"])
    assert r2.exit_code == 0
    # Second run: the installer reports noop (no changes).
    assert "noop" in r2.output or "already" in r2.output.lower()

    # Uninstall should succeed and remove the watcher_status row.
    r3 = runner.invoke(main, ["watchers", "uninstall", "--tool", "claude_code"])
    assert r3.exit_code == 0

    store = WatcherStateStore(isolated_home / ".memgentic" / "watcher_state.sqlite")
    assert store.get_status("claude_code") is None


def test_watchers_install_codex_idempotent(isolated_home: Path) -> None:
    runner = CliRunner()
    r1 = runner.invoke(main, ["watchers", "install", "--tool", "codex"])
    r2 = runner.invoke(main, ["watchers", "install", "--tool", "codex"])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    assert "codex" in r1.output


def test_watchers_enable_disable(isolated_home: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["watchers", "install", "--tool", "gemini_cli"])
    r_disable = runner.invoke(main, ["watchers", "disable", "--tool", "gemini_cli"])
    assert r_disable.exit_code == 0
    r_enable = runner.invoke(main, ["watchers", "enable", "--tool", "gemini_cli"])
    assert r_enable.exit_code == 0

    store = WatcherStateStore(isolated_home / ".memgentic" / "watcher_state.sqlite")
    status = store.get_status("gemini_cli")
    assert status is not None and status.enabled is True


def test_watchers_logs_empty(isolated_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["watchers", "logs", "--tool", "aider"])
    assert result.exit_code == 0
    assert "No log entries" in result.output


def test_watchers_install_rejects_unknown(isolated_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["watchers", "install", "--tool", "nope"])
    assert result.exit_code != 0
    assert "Unknown tool" in result.output
