"""Idempotent install/uninstall helpers for Watchers.

This module is the single source of truth for the ``memgentic watchers
install|uninstall`` commands and their REST counterparts. It edits each
tool's native config file idempotently: running twice leaves the settings
identical, running ``uninstall`` removes every line we added without
touching the user's own entries.

The helpers also mirror the install state into
:class:`WatcherStateStore` so the status list, dashboard, and CLI all
read from a single source of truth.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog

from memgentic.daemon.watcher_state import WatcherStateStore

logger = structlog.get_logger()


# Tools the installer understands — superset of file-watcher tools + hooks.
INSTALLABLE_TOOLS = {
    "claude_code",
    "codex",
    "gemini_cli",
    "antigravity",
    "aider",
    "copilot_cli",
}

_HOOK_MARKER = "memgentic"


@dataclass
class InstallResult:
    tool: str
    changed: bool
    message: str


def _hooks_repo_dir() -> Path:
    """Return the repo-level ``hooks/`` directory that ships bash scripts."""
    # Walk up from this file to the repo root. We live at
    # ``memgentic/memgentic/daemon/watcher_install.py`` so repo root is
    # three parents up.
    return Path(__file__).resolve().parents[3] / "hooks"


def _hooks_install_root() -> Path:
    """Where installed hook scripts live on disk (portable per-user)."""
    return Path.home() / ".memgentic" / "hooks"


def _python_exe() -> str:
    return sys.executable or "python3"


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _ensure_hook_scripts_copied(tool: str) -> Path:
    """Copy shipped hook scripts into ~/.memgentic/hooks/<tool>/."""
    src_dir = _hooks_repo_dir() / tool
    dst_dir = _hooks_install_root() / tool
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not src_dir.exists():
        return dst_dir
    for item in src_dir.iterdir():
        if not item.is_file():
            continue
        dst = dst_dir / item.name
        shutil.copy2(item, dst)
        import contextlib as _ctx

        with _ctx.suppress(OSError):
            os.chmod(dst, 0o755)
    return dst_dir


def install_claude_code(state_store: WatcherStateStore) -> InstallResult:
    """Add Stop, PreCompact, SessionStart hooks to Claude Code settings."""
    scripts_dir = _ensure_hook_scripts_copied("claude_code")
    settings_path = _claude_settings_path()

    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    if not isinstance(data, dict):
        data = {}

    hooks = data.setdefault("hooks", {})
    python = _python_exe()

    # Map Claude Code hook event -> shell invocation. We prefer the bash
    # script on POSIX (so users can customise it) and fall back to calling
    # the Python hook directly on Windows.
    if sys.platform == "win32":
        session_start_py = Path(__file__).resolve().parents[1] / "hooks" / "session_start.py"
        commands = {
            "Stop": f'"{python}" -m memgentic.hooks.socket_post checkpoint claude_code',
            "PreCompact": f'"{python}" -m memgentic.hooks.socket_post compact claude_code',
            "SessionStart": f'"{python}" "{session_start_py}"',
        }
    else:
        commands = {
            "Stop": f'bash "{scripts_dir / "memgentic_checkpoint.sh"}"',
            "PreCompact": f'bash "{scripts_dir / "memgentic_compact.sh"}"',
            "SessionStart": f'bash "{scripts_dir / "memgentic_session.sh"}"',
        }

    changed = False
    for event, command in commands.items():
        event_hooks = hooks.setdefault(event, [])
        if any(
            _HOOK_MARKER in h.get("command", "")
            for matcher in event_hooks
            for h in matcher.get("hooks", [])
        ):
            continue
        event_hooks.append({"hooks": [{"type": "command", "command": command}]})
        changed = True

    if changed:
        settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    state_store.upsert_status("claude_code", enabled=True, clear_error=True)
    return InstallResult(
        tool="claude_code",
        changed=changed,
        message=f"{'installed' if changed else 'already installed'} (settings: {settings_path})",
    )


def uninstall_claude_code(state_store: WatcherStateStore) -> InstallResult:
    settings_path = _claude_settings_path()
    if not settings_path.exists():
        state_store.remove_tool("claude_code")
        return InstallResult("claude_code", False, "settings file not found")

    data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        state_store.remove_tool("claude_code")
        return InstallResult("claude_code", False, "no hooks section")

    changed = False
    for event, matchers in list(hooks.items()):
        if not isinstance(matchers, list):
            continue
        filtered = []
        for matcher in matchers:
            inner = matcher.get("hooks", []) if isinstance(matcher, dict) else []
            kept = [h for h in inner if _HOOK_MARKER not in h.get("command", "")]
            if kept != inner:
                changed = True
            if kept:
                filtered.append({**matcher, "hooks": kept})
        if filtered:
            hooks[event] = filtered
        else:
            hooks.pop(event, None)
            changed = True

    if changed:
        settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    state_store.remove_tool("claude_code")
    return InstallResult(
        tool="claude_code",
        changed=changed,
        message=f"{'uninstalled' if changed else 'nothing to remove'}",
    )


# ---------------------------------------------------------------------------
# Codex CLI
# ---------------------------------------------------------------------------


def _codex_settings_path() -> Path:
    return Path.home() / ".codex" / "hooks.json"


def install_codex(state_store: WatcherStateStore) -> InstallResult:
    scripts_dir = _ensure_hook_scripts_copied("codex")
    settings_path = _codex_settings_path()
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
    if not isinstance(data, dict):
        data = {}

    python = _python_exe()
    if sys.platform == "win32":
        commands = {
            "Stop": f'"{python}" -m memgentic.hooks.socket_post checkpoint codex',
            "PreCompact": f'"{python}" -m memgentic.hooks.socket_post compact codex',
        }
    else:
        commands = {
            "Stop": f'bash "{scripts_dir / "memgentic_checkpoint.sh"}"',
            "PreCompact": f'bash "{scripts_dir / "memgentic_compact.sh"}"',
        }

    entries = data.setdefault("hooks", [])
    changed = False
    for event, command in commands.items():
        already = any(
            isinstance(entry, dict)
            and entry.get("event") == event
            and _HOOK_MARKER in entry.get("command", "")
            for entry in entries
        )
        if already:
            continue
        entries.append({"event": event, "command": command, "source": "memgentic"})
        changed = True

    if changed:
        settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    state_store.upsert_status("codex", enabled=True, clear_error=True)
    return InstallResult(
        tool="codex",
        changed=changed,
        message=f"{'installed' if changed else 'already installed'} (settings: {settings_path})",
    )


def uninstall_codex(state_store: WatcherStateStore) -> InstallResult:
    settings_path = _codex_settings_path()
    if not settings_path.exists():
        state_store.remove_tool("codex")
        return InstallResult("codex", False, "settings file not found")
    data = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        state_store.remove_tool("codex")
        return InstallResult("codex", False, "invalid settings file")
    entries = data.get("hooks") or []
    filtered = [
        e for e in entries if not (isinstance(e, dict) and _HOOK_MARKER in e.get("command", ""))
    ]
    changed = len(filtered) != len(entries)
    if changed:
        data["hooks"] = filtered
        settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    state_store.remove_tool("codex")
    return InstallResult(
        tool="codex",
        changed=changed,
        message=f"{'uninstalled' if changed else 'nothing to remove'}",
    )


# ---------------------------------------------------------------------------
# File-watcher tools (no external config to edit — install flips the flag)
# ---------------------------------------------------------------------------


def install_file_watcher(tool: str, state_store: WatcherStateStore) -> InstallResult:
    state_store.upsert_status(tool, enabled=True, clear_error=True)
    return InstallResult(tool=tool, changed=True, message="file watcher enabled")


def uninstall_file_watcher(tool: str, state_store: WatcherStateStore) -> InstallResult:
    state_store.remove_tool(tool)
    return InstallResult(tool=tool, changed=True, message="file watcher disabled")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def install(tool: str, state_store: WatcherStateStore | None = None) -> InstallResult:
    if tool not in INSTALLABLE_TOOLS:
        return InstallResult(tool=tool, changed=False, message=f"unknown tool {tool!r}")
    store = state_store or WatcherStateStore()
    if tool == "claude_code":
        return install_claude_code(store)
    if tool == "codex":
        return install_codex(store)
    return install_file_watcher(tool, store)


def uninstall(tool: str, state_store: WatcherStateStore | None = None) -> InstallResult:
    if tool not in INSTALLABLE_TOOLS:
        return InstallResult(tool=tool, changed=False, message=f"unknown tool {tool!r}")
    store = state_store or WatcherStateStore()
    if tool == "claude_code":
        return uninstall_claude_code(store)
    if tool == "codex":
        return uninstall_codex(store)
    return uninstall_file_watcher(tool, store)


__all__ = [
    "InstallResult",
    "INSTALLABLE_TOOLS",
    "install",
    "uninstall",
    "install_claude_code",
    "uninstall_claude_code",
    "install_codex",
    "uninstall_codex",
]
