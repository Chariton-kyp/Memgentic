"""Light tests for the Watchers orchestrator's classification helpers."""

from __future__ import annotations

from memgentic.daemon.watchers import (
    ALL_TOOLS,
    FILE_WATCHER_TOOLS,
    HOOK_TOOLS,
    IMPORT_TOOLS,
    MCP_TOOLS,
    classify_tool,
)


def test_all_tools_partitioned() -> None:
    all_from_partitions = HOOK_TOOLS | MCP_TOOLS | IMPORT_TOOLS | FILE_WATCHER_TOOLS
    assert set(ALL_TOOLS) == all_from_partitions


def test_classify_tool_routes_known_tools() -> None:
    assert classify_tool("claude_code") == "hook"
    assert classify_tool("codex") == "hook"
    assert classify_tool("gemini_cli") == "file_watcher"
    assert classify_tool("antigravity") == "file_watcher"
    assert classify_tool("cursor") == "mcp"
    assert classify_tool("chatgpt") == "import"


def test_classify_tool_unknown() -> None:
    assert classify_tool("pepsi_cli") == "unknown"


def test_file_watcher_tools_match_registry() -> None:
    # Sanity: the tuple is in sync with the registry in file_watchers/__init__.
    from memgentic.daemon.file_watchers import FILE_WATCHERS

    assert frozenset(FILE_WATCHERS.keys()) == FILE_WATCHER_TOOLS
