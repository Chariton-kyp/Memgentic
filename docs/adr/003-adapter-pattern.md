# ADR-003: Adapter Pattern — Abstract Base Class + Registry

## Status

Accepted (2026-03-15)

## Context

Memgentic captures conversations from many AI tools (Claude Code, Gemini CLI, ChatGPT, Aider, Codex CLI, Copilot CLI, Antigravity), each with a different file format, directory structure, and conversation schema. The system needs a clean way to:

- Add support for new AI tools without modifying core pipeline code.
- Allow the daemon to discover which directories to watch.
- Enable the import command to find and process all existing conversations.
- Share common logic (topic extraction, content classification) across adapters.

## Decision

Use an **abstract base class** (`BaseAdapter`) with a **registry pattern** for adapter discovery.

- **BaseAdapter ABC**: Defines the contract — `platform`, `watch_paths`, `file_patterns`, `parse_file()`, `get_session_id()`, `get_session_title()`. All adapters implement these.
- **Shared utilities on the base class**: `discover_files()`, `_classify_content()`, `_extract_topics()` provide common functionality that adapters inherit.
- **Registry module** (`adapters/registry.py`): Auto-discovers adapter classes, provides `get_daemon_adapters()` and `get_import_adapters()` entry points for the daemon and import command respectively.
- **One file per adapter**: Each adapter lives in its own module (e.g., `claude_code.py`, `aider.py`), keeping format-specific parsing isolated.

## Consequences

- **Positive**: Adding a new AI tool requires only one new file implementing `BaseAdapter` — no changes to the pipeline, daemon, or CLI. Clean separation of concerns. Daemon automatically picks up new adapters via the registry.
- **Negative**: Slight indirection through the registry. Each adapter must duplicate some boilerplate (property declarations).
- **Mitigated**: The base class provides sensible defaults and shared utilities, minimizing per-adapter boilerplate.
