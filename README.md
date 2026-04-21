# Memgentic

> **Universal AI memory layer — your second brain across every AI tool.**

[![PyPI version](https://img.shields.io/pypi/v/memgentic.svg)](https://pypi.org/project/memgentic/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)
[![CI](https://github.com/Chariton-kyp/memgentic/actions/workflows/ci.yml/badge.svg)](https://github.com/Chariton-kyp/memgentic/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-500+-brightgreen)](memgentic/tests)

Memgentic captures knowledge from every AI tool you use, then makes it searchable, shareable, and distributable across all of them. **One memory layer. Every AI tool. Local-first.**

Named after Mneme, the Greek Titaness of memory and mother of the Muses.

---

## What is Memgentic?

Every conversation with an AI assistant is **ephemeral**. What Claude figured out yesterday is gone today. What ChatGPT learned, Cursor doesn't know. Your architecture decisions, debug sessions, and hard-won insights are scattered across a dozen tools that can't talk to each other.

**Memgentic is the missing layer.** It silently watches every AI tool you use, extracts the signal from the noise, and builds a unified, searchable memory graph that follows you across Claude Code, Cursor, Gemini CLI, Codex, ChatGPT, Aider, and more. Then it turns that memory into **Skills** — reusable knowledge templates that get automatically distributed to every AI tool via the open Agent Skills standard.

**Capture once. Remember everywhere.**

### Key features

- **Captures from 11+ AI tools automatically** — Claude Code, Cursor, Gemini CLI, Codex CLI, Copilot CLI, Aider, ChatGPT, Antigravity, Claude Web, OpenCode
- **Universal skill distribution** — create a skill once, push it to 26+ AI tools via the Agent Skills open standard
- **Local-first** — your memories live on your machine, no cloud required, no telemetry, no tracking
- **Rust native acceleration** — optional PyO3 module makes hot paths 5-50x faster (auto-detected, pure Python fallback)
- **Hybrid search** — semantic vectors + FTS5 keyword + knowledge graph, fused with RRF
- **Credential scrubbing** — 15+ patterns (API keys, tokens, PEM, JWT) redacted before storage
- **Write-time dedup + noise filtering** — only the stuff worth remembering gets stored
- **Knowledge graph** — entity co-occurrence graph for associative recall
- **MCP server + REST API + Dashboard** — use it however you like

---

## Positioning

If the AI memory space were a note-taking analogy:

- **claude-mem** and **MemPalace** are the **Obsidian** of AI memory — solo user, CLI-first, deep in a single niche (session compression or verbatim capture), best-in-class at what they do.
- **Memgentic** is the **Notion** of AI memory — **universal** across AI tools, **dashboard-first**, **team-ready**, multi-surface (CLI + MCP + REST + web UI).

We respect those projects. They're mature, well-engineered, and each one is the right choice for users who match their shape. Memgentic is for people with a different shape: 3+ AI tools in parallel, appetite for a real dashboard, plans to share knowledge with a team, and a preference for Apache 2.0.

---

## How Memgentic compares

Feature comparison verified against each project's current public README (April 2026). Both neighbors are established — each has tens of thousands of GitHub stars and active development. Memgentic is earlier and makes different architectural bets.

| Capability | Memgentic | claude-mem | MemPalace |
|---|---|---|---|
| License | Apache 2.0 | AGPL-3.0 (+ PolyForm NC for `ragtime/`) | MIT |
| Primary shape | Universal, dashboard-first, team-ready (workspaces on roadmap) | Persistent memory compression for Claude Code | Local-first verbatim memory with published benchmarks |
| Capture model | LLM-distilled summaries + noise filter (default). `raw` and `dual` profiles ship this month. | Semantic compression summaries | Verbatim (by design; no summarization, no paraphrase) |
| AI tools captured | 10 adapters (Claude Code, Cursor, Gemini CLI, Codex CLI, Copilot CLI, Aider, Antigravity, OpenCode) + JSON import (ChatGPT, Claude Web) | Claude Code (primary), Gemini CLI, OpenCode | Claude Code, Gemini CLI, any MCP-compatible tool |
| ChatGPT history import (JSON) | Yes | Not documented | Not documented |
| Knowledge graph | Entity co-occurrence graph (NetworkX / Rust petgraph). LLM-extracted temporal triples with user validation ship this month. | Not documented | Temporal entity-relationship graph with validity windows (local SQLite) — more mature today |
| Skills distribution (open Agent Skills standard) | Yes — filesystem write of `SKILL.md` to 26+ AI tools, daemon keeps them synced | Different model (`mem-search` + Claude Desktop Skill) | Not documented |
| Primary surfaces | CLI, MCP, REST API (11 routes), Next.js 16 web dashboard | CLI, MCP, local Web Viewer UI | CLI, MCP (29 tools) |
| Native acceleration | Optional Rust/PyO3 (5–50× on hot paths) | Not documented | Not documented |
| Published retrieval benchmarks | Benchmark harness landing this month (LongMemEval, LoCoMo, ConvoMem, cross-tool transfer) | Not in README | Yes — 96.6% R@5 raw on LongMemEval (no LLM), reproducible |
| Team / workspace support | Phase C milestone (authentication + workspaces + RBAC) | Not documented | Not documented |

### When to pick which

- **Pick claude-mem** if your workflow is mostly Claude Code (optionally Gemini CLI or OpenCode), you want a heavily-starred compression-based memory with a one-line `npx claude-mem install`, and AGPL-3.0 fits your distribution model.
- **Pick MemPalace** if you want **verbatim** storage (every turn kept exactly as written, retrieved semantically), reproducible published benchmarks, a temporal knowledge graph today, and MIT suits you. Single-user, CLI-native.
- **Pick Memgentic** if you use multiple AI tools in parallel (including ChatGPT / Aider / Antigravity — which neither neighbor currently documents), you want a real web dashboard + REST API, you care about Agent-Skills-standard distribution to 26+ tools, you want optional Rust acceleration, Apache 2.0 fits enterprise/team adoption, and your ambitions include workspaces and teams.

None of these tools is universally better — they make different bets. Memgentic's bet is **breadth of tool coverage + multi-surface (dashboard, REST, MCP) + team-readiness**, at the cost of being the newest of the three.

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
              │  13 tools  │             │  FastAPI   │            │  Next.js 16 │
              └─────┬──────┘             └────────────┘            └─────────────┘
                    │
              ┌─────▼──────────────────────────────────┐
              │ Back to AI Tools (recall + skills)     │
              └────────────────────────────────────────┘
```

---

## Tool Integrations

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

## MCP Tools

When Memgentic's MCP server is connected to an AI tool, the tool can call:

| Tool | Purpose |
|------|---------|
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

## Performance

- Search over 1000 memories: p50 < 200ms, p95 < 500ms
- Ingestion of 100 chunks: < 10s
- Batch memory lookup: < 100ms for 100 IDs

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for full numbers.

---

## Roadmap

**Current: v0.6.0 — Zero-config Local + Release Automation**

- [x] M1: Core memory engine
- [x] M2: 11+ adapter ecosystem
- [x] M3: Auto-injection layer (hooks, SKILL.md, context files)
- [x] M4: Production hardening (credential scrubbing, WAL, write-time dedup)
- [x] M5: Rust native acceleration
- [x] M6: Enhanced dashboard + collections + uploads + pins
- [x] M7: Universal skills system + GitHub import + LLM extraction
- [x] M8: Real-time activity feed + ingestion tracking
- [x] M9: Zero-config local (sqlite-vec backend, `serve --watch`, embedding safety pin)
- [x] **M10: Release automation (release-please + linked versions + Conventional Commits + SBOM + SLSA L3)**
- [ ] M11: Authentication + workspaces + teams (Phase C)
- [ ] M12: PostgreSQL + pgvector backend (Phase C)
- [ ] M13: Desktop app (Electron) (Phase D)
- [ ] M14: Browser extension

See [docs/PRODUCT-ROADMAP.md](docs/PRODUCT-ROADMAP.md) for the full plan.

---

## License

[Apache 2.0](LICENSE) — free for any use, commercial or personal.

---

## Acknowledgements

- Built on the [Agent Skills](https://agentskills.io) open standard
- MCP via [FastMCP](https://github.com/jlowin/fastmcp)
- Inspired by [Multica](https://github.com/multica-ai/multica) for the universal skill distribution pattern
