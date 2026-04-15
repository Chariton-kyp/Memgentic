"""Memgentic adapters — parse conversations from different AI tools.

Provides a registry of all available adapters for daemon watching
and bulk import operations.
"""

from __future__ import annotations

from memgentic.adapters.aider import AiderAdapter
from memgentic.adapters.antigravity import AntigravityAdapter
from memgentic.adapters.base import BaseAdapter
from memgentic.adapters.chatgpt_import import ChatGPTImportAdapter
from memgentic.adapters.claude_code import ClaudeCodeAdapter
from memgentic.adapters.claude_web_import import ClaudeWebImportAdapter
from memgentic.adapters.codex_cli import CodexCliAdapter
from memgentic.adapters.copilot_cli import CopilotCliAdapter
from memgentic.adapters.cursor import CursorAdapter
from memgentic.adapters.gemini_cli import GeminiCliAdapter

__all__ = [
    "AiderAdapter",
    "AntigravityAdapter",
    "BaseAdapter",
    "ChatGPTImportAdapter",
    "ClaudeCodeAdapter",
    "ClaudeWebImportAdapter",
    "CodexCliAdapter",
    "CopilotCliAdapter",
    "CursorAdapter",
    "GeminiCliAdapter",
    "get_daemon_adapters",
    "get_import_adapters",
]


def get_daemon_adapters() -> list[BaseAdapter]:
    """Get adapters that support file-watching (have watch_paths).

    These are used by the daemon to monitor directories for new conversations.
    Aider is excluded — it has no fixed watch_paths (project-specific).
    """
    return [
        ClaudeCodeAdapter(),
        GeminiCliAdapter(),
        CodexCliAdapter(),
        CopilotCliAdapter(),
        AntigravityAdapter(),
    ]


def get_import_adapters() -> list[BaseAdapter]:
    """Get all adapters including import-only ones.

    Import-only adapters (no watch_paths) are used by the import-existing
    command and the REST API import endpoints.
    """
    return get_daemon_adapters() + [
        AiderAdapter(),
        ChatGPTImportAdapter(),
        ClaudeWebImportAdapter(),
        CursorAdapter(),
    ]
