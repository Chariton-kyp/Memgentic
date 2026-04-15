---
name: memgentic
description: >-
  Universal AI memory — recall past decisions, learnings, and context
  from all your AI conversations (Claude Code, Gemini CLI, ChatGPT, Aider, etc.)
context: fork
---

# Memgentic — Universal AI Memory Layer

Memgentic captures knowledge from all your AI tools and makes it searchable.
Every memory carries full provenance: which tool, which session, when it happened.

## When to Use

Search memory **before** doing work, not after:

- **Starting a new task** — Check for prior decisions, context, or related work.
- **Making architectural decisions** — Check if this was discussed before.
- **Debugging** — Search for related past issues and solutions.
- **User asks about history** — "what did we decide about...", "remember when...",
  "how did we handle..."
- **Encountering unfamiliar code** — Check for context on why it was written that way.
- **Setting up or configuring something** — Check for user preferences and conventions.

When in doubt, search. It costs little and prevents repeated work.

## CLI Commands

### Semantic Search (primary)

```bash
# Search memories by meaning
memgentic search "database migration strategy"

# Compact output — fewer tokens, good for scanning
memgentic search "database migration strategy" --format compact

# Filter by platform
memgentic search "auth implementation" -s claude_code
memgentic search "API design" -s chatgpt

# Filter by content type
memgentic search "why we chose PostgreSQL" -t decision
memgentic search "user coding style" -t preference
```

### Store a Memory

```bash
# Save an important fact or decision
memgentic remember "We chose Qdrant over Pinecone for local-first vector storage"

# Memory type is auto-classified from content
memgentic remember "Always use UV for package management"
```

### Other Commands

```bash
# See which platforms have memories and how many
memgentic sources

# Generate standalone context file with recent activity
memgentic update-context

# Explore knowledge graph around an entity
memgentic graph "authentication"

# Check system health
memgentic doctor
```

## MCP Tools

If the Memgentic MCP server is running, these tools are available directly:

| Tool | Purpose |
|------|---------|
| `memgentic_recall` | Semantic search with source filtering |
| `memgentic_remember` | Store a new memory |
| `memgentic_search` | Full-text keyword search |
| `memgentic_recent` | Recent memories by timestamp |
| `memgentic_briefing` | Cross-agent briefing of recent activity |
| `memgentic_sources` | List platforms and memory counts |
| `memgentic_configure_session` | Set session-level source filters |
| `memgentic_stats` | Memory statistics and analytics |
| `memgentic_forget` | Archive (soft-delete) a memory |
| `memgentic_export` | Export memories as JSON |

### MCP Examples

```
memgentic_recall(query="authentication flow", limit=5)
memgentic_recall(query="auth", sources=["claude_code", "chatgpt"])
memgentic_remember(content="Project uses JWT with refresh tokens", memory_type="decision")
memgentic_search(query="PostgreSQL", content_type="decision")
memgentic_configure_session(exclude_sources=["codex_cli"])
memgentic_briefing(hours=24)
```

## Efficient Retrieval Strategy

Minimize token usage with a progressive approach:

1. **Start compact** — Use `--format compact` for an overview of what exists.
2. **Narrow down** — Add platform filter (`-s claude_code`) or type filter (`-t decision`)
   when you know what you are looking for.
3. **Full detail** — Drop `--format compact` only when you need the complete memory content.
4. **Limit results** — Use `--limit` to cap the number of results returned.

```bash
# Step 1: Quick scan
memgentic search "deployment" --format compact --limit 10

# Step 2: Found relevant results, get details from a specific platform
memgentic search "deployment" -s claude_code --limit 3
```

## Memory Types

Memories are classified into types for filtering:

| Type | Contains |
|------|----------|
| `decision` | Architectural and technical decisions with rationale |
| `learning` | Things learned during development |
| `preference` | User preferences, conventions, coding style |
| `fact` | General knowledge and project context |
| `bug_fix` | Bug fixes, root causes, and solutions |
| `conversation_summary` | Summaries of complete sessions |

Filter by type to get precise results:

```bash
memgentic search "database" -t decision    # Only decisions about databases
memgentic search "testing" -t preference   # Only testing preferences
memgentic search "auth" -t bug_fix         # Only auth-related bug fixes
```

## Cross-Platform Context

Memgentic captures from multiple AI tools. Each memory records its source platform:

| Platform | Source ID |
|----------|-----------|
| Claude Code | `claude_code` |
| Gemini CLI | `gemini_cli` |
| ChatGPT | `chatgpt` |
| Aider | `aider` |
| Codex CLI | `codex_cli` |
| Copilot CLI | `copilot_cli` |
| Claude Web/Desktop | `claude_web` |
| Antigravity | `antigravity` |

Use source filtering to scope searches:

```bash
# What did we discuss in Claude Code about this project?
memgentic search "project architecture" -s claude_code

# What did ChatGPT suggest about this topic?
memgentic search "caching strategy" -s chatgpt

# See all available sources
memgentic sources
```

## Capture Methods

Memories enter the system through:

- **auto_daemon** — File watcher captures conversations automatically in the background.
- **mcp_tool** — Stored via MCP tool calls during AI sessions.
- **cli** — Manually saved via `memgentic remember`.
- **json_import** — Bulk imported from conversation exports (ChatGPT, Claude Web).

## Setup

```bash
# Check prerequisites
memgentic doctor

# Interactive setup (model selection, configuration)
memgentic setup

# Import existing conversations from all detected AI tools
memgentic import-existing

# Start background capture daemon
memgentic daemon

# Start MCP server for AI tool integration
memgentic serve
```
