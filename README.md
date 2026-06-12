# Memgentic

> **Universal AI memory layer — your second brain across every AI tool.**

[![PyPI version](https://img.shields.io/pypi/v/memgentic.svg)](https://pypi.org/project/memgentic/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)
[![CI](https://github.com/Chariton-kyp/memgentic/actions/workflows/ci.yml/badge.svg)](https://github.com/Chariton-kyp/memgentic/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-1000+-brightgreen)](memgentic/tests)

Memgentic captures knowledge from every AI tool you use, then makes it searchable, shareable, and distributable across all of them. **One memory layer. Every AI tool. Local-first.**

Named after Mneme, the Greek Titaness of memory and mother of the Muses.

---

## What is Memgentic?

Every conversation with an AI assistant is **ephemeral**. What Claude figured out yesterday is gone today. What ChatGPT learned, Cursor doesn't know. Your architecture decisions, debug sessions, and hard-won insights are scattered across a dozen tools that can't talk to each other.

**Memgentic is the missing layer.** It silently watches every AI tool you use, extracts the signal from the noise, and builds a unified, searchable memory graph that follows you across Claude Code, Cursor, Gemini CLI, Codex, ChatGPT, Aider, and more. Then it turns that memory into **Skills** — reusable knowledge templates that get automatically distributed to every AI tool via the open Agent Skills standard.

**Capture once. Remember everywhere.**

### Key features

- **Captures from 11+ AI tools automatically** — Claude Code, Cursor, Gemini CLI, Codex CLI, Copilot CLI, Aider, ChatGPT, Antigravity, Claude Web, OpenCode
- **Cross-tool continuation** — stop in Claude Code, reopen in Codex or Gemini CLI, and resume from the latest source-backed handoff context
- **Transparent memory inventory** — inspect exactly what is stored and what memory has already been loaded into the current agent context
- **Universal skill distribution** — create a skill once, push it to 26+ AI tools via the Agent Skills open standard
- **Local-first** — your memories live on your machine, no cloud required, no telemetry, no tracking
- **Rust native acceleration** — optional PyO3 module makes hot paths 5-50x faster (auto-detected, pure Python fallback)
- **Hybrid search** — semantic vectors + FTS5 keyword + knowledge graph, fused with RRF
- **Credential scrubbing** — 15+ patterns (API keys, tokens, PEM, JWT) redacted before storage
- **Write-time dedup + noise filtering** — only the stuff worth remembering gets stored
- **Knowledge graph** — entity co-occurrence graph for associative recall
- **MCP server + REST API + Dashboard** — use it however you like

---

## Quick Start

```bash
# 1. Install
pip install memgentic

# 2. Full onboarding — detects AI tools, configures models, sets up MCP and hooks
memgentic init

# 3. Start the capture daemon
memgentic daemon
```

That's it. Your Claude Code, Cursor, Gemini CLI, and Codex now have shared cross-tool memory via MCP.

> **Tip:** Already installed and just want to change the embedding model or storage backend?
> Run `memgentic setup` (model/backend reconfiguration only, no tool detection).

---

## The Dashboard

A live second brain for your AI work. Browse, search, organize, and curate your memories.

> Run it locally with `make dashboard` after `make install`.

| Feature | What it does |
|---|---|
| **Pinned row** | Star important memories for permanent quick access at the top |
| **Memory grid** | Source-badged cards with topics, confidence, and quick actions |
| **Collections sidebar** | User-defined groups for organizing by project, context, or topic |
| **Upload modal** | Write text, drop files (`.md`/`.txt`/`.pdf`), or import from URL |
| **Skills page** | Master-detail editor with file tree and per-tool distribution status |
| **Command palette** | Cmd+K global semantic search across every memory and skill |
| **Activity feed** | Real-time event log via WebSocket |
| **Memory detail** | Inline editing, related memories via vector similarity |

---

## Skills: Universal Knowledge Across Every AI Tool

Memgentic is a **universal skill manager**. Write a skill once, and it's automatically distributed to every AI tool you use via the open [Agent Skills standard](https://agentskills.io) (26+ tools).

```
~/.claude/skills/deploy-runbook/SKILL.md         → Claude Code
~/.codex/skills/deploy-runbook/SKILL.md          → Codex CLI
~/.cursor/rules/deploy-runbook/SKILL.md          → Cursor
~/.config/opencode/skills/deploy-runbook/SKILL.md → OpenCode
```

Add a skill from the dashboard, **import one from any GitHub repo**, or let Memgentic's LLM auto-extract skills from your existing memories. The daemon keeps every tool's copy in sync automatically.

A `SKILL.md` file uses the standard YAML frontmatter format:

```markdown
---
name: deploy-runbook
description: Production deployment checklist
version: 1.0.0
tags: [deploy, ops]
---

# Deployment Runbook

## Pre-deployment
...
```

---

## How It Works

```
   ┌──────────────┐       ┌──────────┐       ┌──────────────┐       ┌──────────────┐
   │  AI Tools    │       │          │       │  Pipeline    │       │              │
   │  Claude Code │       │          │       │              │       │  SQLite+FTS5 │
   │  Cursor      │  ───> │  Daemon  │  ───> │  Scrub →     │  ───> │  Qdrant      │
   │  Gemini CLI  │       │  Watcher │       │  Filter →    │       │  NetworkX    │
   │  Codex CLI   │       │          │       │  Embed →     │       │              │
   │  11+ others  │       │          │       │  Distill →   │       │              │
   └──────────────┘       └──────────┘       │  Dedup →     │       └──────┬───────┘
                                             │  Store       │              │
                                             └──────────────┘              │
                                                                            │
                    ┌───────────────────────────┬──────────────────────────┤
                    │                           │                          │
              ┌─────▼──────┐             ┌─────▼──────┐            ┌──────▼──────┐
              │ MCP Server │             │  REST API  │            │  Dashboard  │
              │  30+ tools │             │  FastAPI   │            │  Next.js 16 │
              └─────┬──────┘             └────────────┘            └─────────────┘
                    │
              ┌─────▼──────────────────────────────────┐
              │ Back to AI Tools (recall + skills)     │
              └────────────────────────────────────────┘
```

---

## Tool Integrations

This table pairs **capture** and **skill-injection** scopes per tool. The capture-mechanism breakdown (hook vs. file watcher vs. MCP vs. one-shot import) lives in the [Watchers matrix](#watchers--cross-tool-automatic-capture) section.

| Tool | Capture | Skill injection |
|------|---------|-----------|
| Claude Code | Daemon | `~/.claude/skills/` + MCP + SessionStart hook |
| Codex CLI | Daemon | `~/.codex/skills/` + MCP + AGENTS.md |
| Cursor | Daemon | `~/.cursor/rules/` + MCP |
| Gemini CLI | Daemon | MCP + GEMINI.md |
| OpenCode | Daemon | `~/.config/opencode/skills/` |
| Aider | Import | Context file |
| ChatGPT (export) | Import (JSON) | — |
| Copilot CLI | Daemon | — |
| Antigravity | Daemon | — |
| Claude Web (export) | Import (JSON) | — |

---

## CLI Usage

```bash
# Semantic + keyword + graph hybrid search
memgentic search "database migration" -s claude_code -t decision

# Store a memory manually
memgentic remember "We chose PostgreSQL over MongoDB for consistency"

# Skills
memgentic skill list
memgentic skill import https://github.com/owner/repo/tree/main/skill-name

# Health check
memgentic doctor

# See all commands
memgentic --help
```

---

## Recall Tiers — tier-aware briefing

Memgentic's briefing is a structured, token-budgeted stack rather than a flat dump. Five tiers, each loaded on demand:

| Tier | Name | Loaded by default | Source |
|---|---|---|---|
| **T0** | Persona | yes | `~/.memgentic/persona.yaml` (identity, people, projects, preferences) |
| **T1** | Horizon | yes | top-N memories + top-3 skills (importance × recency × pinned × cluster × skill-link, MMR-selected) |
| **T2** | Orbit | on match | memories filtered by collection / topic |
| **T3** | Deep Recall | explicit | hybrid semantic + FTS5 search |
| **T4** | Atlas | on KG query | Chronograph graph traversal |

The default `memgentic_briefing()` call returns **T0 + T1** under ~900 tokens (adaptive to the target model's context window). Deeper tiers are one call away.

**Example — agent wakes up and asks for a briefing:**

```jsonc
// MCP call
{
  "name": "memgentic_briefing",
  "arguments": { "collection": "journaling-app", "model_context": 200000 }
}
```

**Sketch of the returned text:**

```
## T0 — Persona
You are Atlas, personal AI assistant for Alice.
Tone: warm, direct, remembers everything.
Active projects: journaling-app (next.js + postgres).
Remember: code stack choices, naming conventions, decisions with rationale.
Avoid: apology-heavy responses, unrelated refactors during bug fixes.

## T1 — Horizon
[collection:journaling-app]
  - decided Clerk over Auth0 (pricing) — 2026-02-01, pinned
  - Kai fixed OAuth refresh flow in middleware.ts — 2026-02-08
  - migrated to PostgreSQL 18 for pgvector support — 2026-03-14, pinned
  - chose TanStack Query over SWR for shared cache semantics — 2026-03-22
[skills:top]
  - debugging/pr-review (used 34x)
  - deploy-runbook (used 21x)
  - postgres-migration-checklist (used 9x)
```

Explicit deeper calls:

```bash
memgentic briefing --tier T2 --collection journaling-app --topic auth
memgentic briefing --tier T3 --query "why graphql"
memgentic briefing --tier T4 --entity Kai
memgentic briefing --status                  # show budgets + last-run stats
memgentic briefing --weights importance=0.4,recency=0.3
```

Agents can also call `memgentic_tier_recall(tier="T3", query="...")` directly when they already know which tier they want.

---

## Watchers — cross-tool automatic capture

Each AI tool uses the capture mechanism native to it. All paths converge on the same daemon (dedup → pipeline → store). Zero tokens spent in the chat window.

| Tool | Capture mechanism | Status | Notes |
|---|---|---|---|
| Claude Code | Hook (`Stop`, `PreCompact`, `SessionStart`, `UserPromptSubmit`) | Shipped | Edits `~/.claude/settings.json`; SessionStart injects T0+T1 briefing |
| Codex CLI | Hook (`Stop`, `PreCompact`) | Shipped | Edits `~/.codex/hooks.json` |
| Gemini CLI | File watcher (JSONL tail) | Shipped | Watches `~/.gemini/tmp/*/chats/*.json`; delta-only via `last_offset` |
| Copilot CLI | File watcher (log appends) | Shipped | Parses `~/.copilot/...` log stream |
| Aider | File watcher (markdown appends) | Shipped | Parses `<project>/.aider.chat.history.md` by session header |
| ChatGPT import | One-shot import (JSON) | Shipped | `memgentic import chatgpt <export.json>` |
| Claude Web import | One-shot import (JSON) | Shipped | `memgentic import claude-web <export.json>` |
| Cursor | MCP (agent-initiated) | Shipped | No file watcher — Cursor's agent calls `memgentic_remember` / `memgentic_recall` directly |
| Antigravity | File watcher + protobuf decode | Shipped | Watches `~/.gemini/antigravity/conversations/`; schema-pinned, graceful skip on mismatch |

Manage them uniformly:

```bash
memgentic watchers install   --tool claude_code
memgentic watchers status
memgentic watchers disable   --tool copilot_cli
memgentic watchers uninstall --tool aider
memgentic watchers logs      --tool claude_code --tail 50
```

The dashboard's `/watchers` page shows the same table live (last-capture timestamp, captured count, install state, per-tool logs).

---

## MCP Tools

When Memgentic's MCP server is connected to an AI tool, the tool can call:

| Tool | Purpose |
|------|---------|
| `memgentic_handoff()` | **Cross-tool resume** — source-backed continuation brief grouped by recent source session (call this at session start) |
| `memgentic_context()` | Show what memory has been loaded into the current MCP session |
| `memgentic_inventory()` | Auditable manifest of stored memories (counts, sources, content types, paginated IDs) |
| `memgentic_recall(query)` | Semantic search with source filtering |
| `memgentic_search(query)` | Full-text keyword search |
| `memgentic_remember(content)` | Save a new memory |
| `memgentic_briefing()` | Recent cross-tool activity |
| `memgentic_recent()` | Latest memories |
| `memgentic_sources()` | List platforms and counts |
| `memgentic_expand(memory_id)` | Full content of a memory |
| `memgentic_pin(memory_id)` | Pin/unpin a memory |
| `memgentic_skills()` | List available skills |
| `memgentic_skill(name)` | Get a specific skill's content |
| `memgentic_configure_session(filters)` | Session-level source filters |
| `memgentic_stats()` | Memory statistics |
| `memgentic_export()` | Export memories as JSON |

A `continue` MCP prompt is also registered — clients that surface MCP prompts can invoke it at startup to ask the agent to call `memgentic_handoff` and resume from the latest source session.

---

## Local-first, Privacy-first

- **No telemetry.** Zero outbound calls except to Ollama (localhost) and — only if you opt in — OpenAI, Anthropic, or Gemini for intelligence extras
- **Credential scrubbing on by default.** API keys, passwords, tokens, PEM keys, JWTs — all redacted before storage
- **Write-time dedup + noise filtering.** Acknowledgments, tool output dumps, and stack traces never make it into your memory
- **Source provenance on every memory.** You always know which tool, session, and timestamp produced any piece of knowledge
- **Local SQLite + Qdrant.** Your data lives in `~/.memgentic/` and never leaves unless you export it

---

## Native Rust Acceleration

Memgentic includes an optional Rust extension module (`memgentic-native`) that accelerates CPU-bound operations 5-50x. It is **automatically detected** — no configuration needed.

| What it accelerates | Improvement |
|---|---|
| Credential scrubbing | 20-50x faster |
| Text overlap / dedup | 10-20x faster |
| Noise detection & classification | 5-10x faster |
| JSONL / ChatGPT / Protobuf parsing | 5-30x faster |
| Knowledge graph (petgraph vs NetworkX) | 10-50x faster |

If Rust is installed, `make install` builds it automatically. If not, the pure Python fallback is used and everything still works.

```bash
make native    # Build native acceleration manually
```

---

## Memgentic Guard

**Deterministic Agentic CI.** AI coding agents write a lot of your diffs now — Guard checks those diffs against **your** architectural rules before they land. It is not an LLM judge: it parses the diff, applies rules you wrote in `decisions.yaml`, and exits non-zero on a violation. Same rules, same answer, every run.

Guard only fires on **introduced** violations — a banned import that already existed on the base branch never trips the check, so dropping it into a legacy repo doesn't bury you in pre-existing noise.

### 60-second quickstart

```bash
pip install memgentic
memgentic guard init                 # writes a starter decisions.yaml (all rules commented out)
# edit decisions.yaml — uncomment + tailor the rules you want
memgentic guard                      # check your branch vs its base (default: main)
memgentic guard install-hook         # block bad commits at pre-commit time
```

### Rule types

| Type | What it checks | Languages / files |
|------|----------------|-------------------|
| `import_direction` | A layer must not import another (enforces dependency direction) | Python `import`/`from`, C# `using` |
| `banned_import` | Specific modules/packages must not be imported | Python `import`/`from`, C# `using` |
| `banned_dependency` | A package must not be added to a manifest | `pyproject.toml`, `package.json`, `requirements.txt`, `*.csproj`, `Directory.Packages.props` |
| `forbidden_path` | Files matching a glob must not be touched | any path (e.g. `**/.env`, `**/*.pem`) |

Each rule carries a `severity`: **`error`** fails the run (exit 1, blocks the commit/CI), **`warn`** prints but passes (exit 0). Exit codes: `0` clean, `1` error-severity violation, `2` guard/config error (not a git repo, malformed rules).

Don't want to write rules by hand? `memgentic guard suggest` drafts machine-checkable rules from your `AGENTS.md` / `CLAUDE.md` / ADRs using an LLM (requires the `[intelligence]` extra). It only proposes YAML to stdout — you review and save it.

Agents can self-check before proposing a diff via the MCP tool `memgentic_guard_check`.

**Not yet supported (roadmap):** TypeScript/JavaScript `import` direction, and C# project-reference (`.csproj` → `.csproj`) direction. See [`docs/guard/getting-started.md`](docs/guard/getting-started.md) for the full guide.

---

## Installation

### Default (local-first)

- **Python 3.12+**
- **Ollama** — https://ollama.com — for embeddings (`qwen3-embedding:0.6b`, ~500MB)
- **Rust** (optional) — https://rustup.rs — for native acceleration

### Alternative (cloud embeddings)

```bash
export MEMGENTIC_EMBEDDING_PROVIDER=openai
export MEMGENTIC_OPENAI_API_KEY=sk-...
export MEMGENTIC_EMBEDDING_MODEL=text-embedding-3-small
```

### Docker

```bash
make dev    # auto-detects NVIDIA GPU
```

---

## Architecture

- **Backend** — Python 3.12+ / FastAPI / aiosqlite / Qdrant / structlog
- **Native** — Rust + PyO3 (optional, auto-detected)
- **Frontend** — Next.js 16, React 19, Tailwind 4, shadcn/ui, TanStack Query, Zustand
- **Embeddings** — Qwen3-Embedding-0.6B via Ollama (default) or OpenAI
- **LLM intelligence** — Gemini Flash Lite via LangChain (optional, opt-in)
- **MCP** — FastMCP / `mcp[cli]>=1.26`

See [CLAUDE.md](CLAUDE.md) for full architecture details.

---

## Development

```bash
git clone https://github.com/Chariton-kyp/memgentic.git
cd memgentic
make install    # Python deps + Rust native (if available)
make test       # Run all tests
make dashboard  # Start the dashboard locally
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/](docs/) for details.

---

## License

[Apache 2.0](LICENSE) — free for any use, commercial or personal.

---

## Acknowledgements

- Built on the [Agent Skills](https://agentskills.io) open standard
- MCP via [FastMCP](https://github.com/jlowin/fastmcp)
- Inspired by [Multica](https://github.com/multica-ai/multica) for the universal skill distribution pattern
