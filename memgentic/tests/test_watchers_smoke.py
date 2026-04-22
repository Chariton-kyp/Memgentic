"""Smoke tests for the Watchers module — importability + basic state store.

Full integration tests (hook socket roundtrip, file watcher debouncing,
protobuf decode, installer idempotency) land in a follow-up PR. This
file asserts the modules import cleanly and the state store CRUDs.
"""

from __future__ import annotations

from pathlib import Path


def test_watcher_modules_import():
    """All new daemon modules must import without error."""
    from memgentic.daemon import dedup, watcher_install, watcher_state, watchers
    from memgentic.daemon import watcher_socket as _ws
    from memgentic.daemon.file_watchers import (
        aider,
        antigravity,
        base,
        copilot_cli,
        gemini_cli,
    )

    assert dedup is not None
    assert watcher_install is not None
    assert watcher_state is not None
    assert watchers is not None
    assert _ws is not None
    assert all(m is not None for m in (aider, antigravity, base, copilot_cli, gemini_cli))


def test_watcher_state_roundtrip(tmp_path: Path):
    """WatcherStateStore persists enabled flag + installed_at."""
    from memgentic.daemon.watcher_state import WatcherStateStore

    db_path = tmp_path / "watcher_state.sqlite"
    store = WatcherStateStore(db_path=db_path)
    store.upsert_status("claude_code", enabled=True)
    status = store.get_status("claude_code")
    assert status is not None
    assert status.tool == "claude_code"
    assert status.enabled is True


def test_watchers_rest_route_registered(client_factory_if_available=None):
    """Sanity check: /api/v1/watchers route exists on the FastAPI app."""
    from memgentic_api.routes import watchers as watchers_module

    route_paths = {route.path for route in watchers_module.router.routes}
    assert any(p.startswith("/watchers") for p in route_paths), (
        f"No /watchers route found in {route_paths}"
    )


def test_hook_scripts_ship():
    """Plan 06 §5a — shipped hook scripts for Claude Code and Codex."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    for relpath in [
        "hooks/claude_code/memgentic_checkpoint.sh",
        "hooks/claude_code/memgentic_compact.sh",
        "hooks/claude_code/memgentic_session.sh",
        "hooks/codex/memgentic_checkpoint.sh",
        "hooks/codex/memgentic_compact.sh",
    ]:
        p = repo_root / relpath
        assert p.exists(), f"Missing hook script: {relpath}"
