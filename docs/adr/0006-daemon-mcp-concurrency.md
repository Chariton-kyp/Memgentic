# ADR 0006 — Daemon + MCP Server Concurrency Model

**Status:** Accepted
**Date:** 2026-04-09

## Context

Memgentic has two long-running processes that share the same SQLite and
Qdrant stores:

1. The **daemon** (`memgentic daemon`) — watches files and writes new memories.
2. The **MCP server** (`memgentic serve`) — serves read and write operations to
   AI tools via the Model Context Protocol.

In local-first mode (the default for single-user installations), both
processes access:

- **SQLite** at `~/.memgentic/data/memgentic.db` (file-based)
- **Qdrant** at `~/.memgentic/data/qdrant/` (file-based, single-writer)

## Problem

Qdrant's local file mode does **not** support multiple writers. If both the
daemon and MCP server try to write to Qdrant simultaneously, one will fail
with a lock error (or, worse, corrupt state).

SQLite supports concurrent readers plus one writer via WAL mode (enabled in
Phase 0). That side is fine.

## Decision

**For single-user local mode (the default):**

- Users run **either** `memgentic daemon` **or** `memgentic serve` at one
  time, not both.
- The MCP server can still handle captures via the `memgentic_remember()`
  tool call — the daemon is optional.
- Bulk backfill uses the one-shot `memgentic import-existing` command when
  catch-up is needed.

**For power users who want both processes always-on:**

- Set `MEMGENTIC_STORAGE_BACKEND=qdrant` and
  `MEMGENTIC_QDRANT_URL=http://localhost:6333`, and run Qdrant as a separate
  process (Docker Compose or native install).
- Qdrant server mode supports concurrent writers.
- Both the daemon and the MCP server connect to the same Qdrant server.
- The `make dev` Docker Compose setup is the recommended always-on path.

**Enforcement:** The `memgentic daemon` command acquires a PID lock at
`<data_dir>/.daemon.pid` on startup via `memgentic.utils.process_lock`. If
another Memgentic process already holds the lock, the daemon refuses to
start with a clear error message. The lock is **skipped** when
`storage_backend == "qdrant"` (server mode), because concurrent writers are
safe in that configuration.

## Consequences

**Positive:**

- Clear single-user local story: one writer process at a time.
- Power-user story: run Qdrant as a server for always-on capture + MCP.
- No silent corruption from concurrent writers into local Qdrant.
- The lock uses a tiny, dependency-free utility that's trivially testable.

**Negative:**

- Local-mode users must choose between always-on capture (daemon) and
  on-demand MCP (serve), unless they adopt Docker Compose.
- Stale lock files (e.g. from a crashed process) require manual removal. A
  future improvement could auto-expire locks whose PID is no longer alive.
