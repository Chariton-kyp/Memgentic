"""Delta-aware file watchers for tools without hook APIs.

Each watcher subscribes to a tool's native conversation directory, tails
append-only files, and converts new bytes into ``ConversationChunk`` objects
via the corresponding adapter. Offsets are tracked in
``~/.memgentic/watcher_state.sqlite`` so a restart resumes instead of
re-ingesting whole files.

Registry
--------
The dict :data:`FILE_WATCHERS` maps tool name -> factory callable. The
Watchers orchestrator walks this map to bring up watchers for every tool
that has ``watcher_status.enabled = TRUE``. New watchers only need to
register themselves here.
"""

from __future__ import annotations

from collections.abc import Callable

from memgentic.daemon.file_watchers.aider import AiderFileWatcher
from memgentic.daemon.file_watchers.antigravity import AntigravityFileWatcher
from memgentic.daemon.file_watchers.base import BaseFileWatcher, WatcherContext
from memgentic.daemon.file_watchers.copilot_cli import CopilotCliFileWatcher
from memgentic.daemon.file_watchers.gemini_cli import GeminiCliFileWatcher

FileWatcherFactory = Callable[[WatcherContext], BaseFileWatcher]

FILE_WATCHERS: dict[str, FileWatcherFactory] = {
    "gemini_cli": GeminiCliFileWatcher,
    "antigravity": AntigravityFileWatcher,
    "aider": AiderFileWatcher,
    "copilot_cli": CopilotCliFileWatcher,
}


def available_tools() -> list[str]:
    """Return the list of tool names that have a file-watcher implementation."""
    return sorted(FILE_WATCHERS.keys())


__all__ = [
    "BaseFileWatcher",
    "WatcherContext",
    "FILE_WATCHERS",
    "FileWatcherFactory",
    "available_tools",
]
