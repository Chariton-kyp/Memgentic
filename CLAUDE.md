# CLAUDE.md

## Project Overview

**Memgentic (Μνήμη)** — Universal AI Memory Layer. Zero-effort knowledge capture across all AI tools. Source-aware memory with semantic search, filtering, and knowledge graphs.

Named after the Greek Titaness of memory, mother of the Muses.

## The Problem We Solve

Every AI conversation is ephemeral — knowledge is lost when the session ends. Worse, knowledge is siloed: what Claude knows, ChatGPT doesn't, and vice versa. No universal memory layer exists that captures knowledge automatically from all AI tools and makes it available everywhere.

**Memgentic is that missing layer.**

## Architecture: Monorepo with Extractable Core

```
memgentic/              ← Independent package (core engine, extractable)
├── memgentic/
│   ├── config.py        Settings (Pydantic)
│   ├── models.py        Data models (Memory, SourceMetadata, SessionConfig)
│   ├── cli.py           CLI tool (Click + Rich)
│   ├── storage/
│   │   ├── metadata.py  SQLite + FTS5 (metadata, full-text search)
│   │   └── vectors.py   Qdrant (semantic vector search)
│   ├── processing/
│   │   ├── embedder.py  Embedding generation (Ollama / OpenAI)
│   │   ├── pipeline.py  Ingestion pipeline (chunk → embed → store)
│   │   ├── intelligence.py  LLM classification, extraction, summarization
│   │   └── llm.py       LLM client (Gemini Flash Lite)
│   ├── adapters/
│   │   ├── base.py           Base adapter interface
│   │   ├── registry.py       Adapter registry (auto-discovery)
│   │   ├── claude_code.py    Claude Code adapter (~/.claude/projects/)
│   │   ├── gemini_cli.py     Gemini CLI adapter
│   │   ├── chatgpt_import.py ChatGPT JSON import adapter
│   │   ├── aider.py          Aider adapter (.aider.chat.history.md)
│   │   ├── codex_cli.py      Codex CLI adapter
│   │   ├── copilot_cli.py    Copilot CLI adapter
│   │   ├── claude_web_import.py  Claude Web/Desktop import adapter
│   │   └── antigravity.py    Antigravity adapter (Protocol Buffers)
│   ├── graph/
│   │   ├── knowledge.py  NetworkX knowledge graph (entity co-occurrence)
│   │   └── search.py     Graph-enhanced retrieval
│   ├── daemon/
│   │   └── watcher.py   File system watcher (watchdog)
│   └── mcp/
│       └── server.py    MCP server (FastMCP) — 10 tools

memgentic-api/               ← REST API package (FastAPI)
├── memgentic_api/
│   ├── main.py          FastAPI app with lifespan
│   ├── deps.py          Dependency injection
│   ├── schemas.py       Request/response Pydantic models
│   └── routes/
│       ├── memories.py  CRUD + search endpoints
│       ├── sources.py   Source stats endpoints
│       ├── stats.py     Analytics endpoints
│       ├── graph.py     Knowledge graph endpoints
│       └── import_export.py  Import/export endpoints

memgentic-native/            ← Rust native acceleration (PyO3, optional)
├── Cargo.toml
├── pyproject.toml       Maturin build config
└── src/
    ├── lib.rs           PyO3 module registration
    ├── textproc/        Credential scrubbing, noise detection, classification
    ├── parsers/         JSONL, ChatGPT JSON, Protobuf, Markdown parsers
    └── graph/           petgraph-based knowledge graph engine

dashboard/               ← Web Dashboard (Next.js 16, React 19, Tailwind v4, shadcn/ui)
docs/                    ← Research & architecture docs
```

### Golden Rule: Dependency Direction
```
memgentic  ←──  mneme-cloud    (cloud imports from core)
memgentic  ←──  frontend       (frontend calls core API)
NEVER: memgentic  ──→  cloud   (core NEVER imports from cloud)
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| MCP Server | FastMCP (mcp[cli] >=1.26) |
| Embedding | **Qwen3-Embedding-0.6B** via Ollama 0.18+ (768d MRL-truncated, Apache 2.0) |
| Vector DB | **Qdrant** >=1.17 — file-based local (zero-config) or server |
| Metadata DB | **SQLite + FTS5** via aiosqlite >=0.22 |
| LLM Processing | **langchain-core** + **LangGraph** (pipeline orchestration) |
| LLM Providers | **Gemini Flash Lite** (langchain-google-genai >=4.0) + **Claude** (langchain-anthropic >=1.0) |
| Native Accel | **memgentic-native** — Rust/PyO3 (optional, auto-detected) |
| Backend | Python 3.12+ / FastAPI >=0.130 |
| CLI | Click >=8.1 + Rich >=14.0 |
| Frontend | Next.js 16.2+, React 19.2+, Tailwind CSS 4.2+, shadcn/ui |
| File Watching | watchdog >=6.0 |
| Config | Pydantic Settings >=2.10 + .env |
| Logging | structlog >=25.0 |
| Linting | Ruff >=0.14 |
| Package Manager | UV |
| Database (cloud) | PostgreSQL 18 |
| License | Apache 2.0 |

## Key Concepts

### Source-Aware Memory
Every memory carries full provenance metadata:
- **platform**: Which AI tool (claude_code, chatgpt, gemini_cli, etc.)
- **capture_method**: How it was captured (auto_daemon, mcp_tool, json_import)
- **session_id**: Original conversation ID
- **original_timestamp**: When the conversation happened

### Session-Level Source Filtering
Users can configure per-session source filters:
```
memgentic_configure_session(exclude_sources=["codex_cli"])
```
All subsequent `memgentic_recall` calls respect these filters.

### Automatic Capture Daemon
File watcher monitors CLI tool directories:
- Claude Code: `~/.claude/projects/**/*.jsonl`
- Gemini CLI: `~/.gemini/tmp/*/chats/` (Phase 2)
- Antigravity: `~/.gemini/antigravity/conversations/` (Phase 2)
- Codex CLI: `~/.codex/sessions/` (Phase 2)

## MCP Tools

```
memgentic_recall             Semantic search with source filtering
memgentic_remember           Store a new memory
memgentic_sources            List sources and counts
memgentic_configure_session  Set session-level filters
memgentic_search             Full-text keyword search
memgentic_recent             Recent memories
memgentic_stats              Memory statistics
memgentic_briefing           Cross-agent briefing of recent memories
memgentic_forget             Archive (soft-delete) a memory
memgentic_export             Export memories as JSON
memgentic_skills             List available skills (name + description)
memgentic_skill              Get a specific skill's content by name
memgentic_pin                Pin or unpin a memory
```

## CLI Commands

```bash
memgentic serve --watch   # Recommended: MCP server + file watcher, one process
memgentic serve           # MCP server only (back-compat; needs a separate daemon)
memgentic daemon          # Standalone file watcher daemon (back-compat)
memgentic import-existing # Import all existing conversations
memgentic search "query"  # Semantic search
memgentic sources         # Show source stats
memgentic remember "..."  # Manual memory
memgentic doctor          # Check prerequisites (Ollama, models, Qdrant)
memgentic setup           # Interactive model selection and configuration
memgentic consolidate     # Recompute importance, detect duplicates
memgentic re-embed        # Re-generate all embeddings with current model
memgentic graph "entity"  # Explore knowledge graph around an entity
memgentic backup          # Create database backup archive
memgentic restore <file>  # Restore from backup archive
memgentic export-gdpr     # Export all data (GDPR Article 20)
```

## Docker Services

```yaml
services:
  memgentic     # MCP server (HTTP transport, :8200)
  qdrant    # Vector database (:6333)
  ollama    # Embedding service — Qwen3-0.6B (:11434)
```

## Commands

```bash
make dev          # Start full Docker stack
make install      # Install all deps (auto-builds Rust native if available)
make native       # Build Rust native acceleration (optional, requires Rust)
make serve        # Start MCP server locally (stdio)
make daemon       # Start file watcher daemon locally
make import       # Import all existing conversations
make test         # Run all tests
make lint         # Lint code
make pull-models  # Pull embedding model into Ollama
```

## Critical Constraints

- **Local-first** — Everything works offline, data stays on your machine
- **Source metadata on every memory** — Full provenance, always
- **Same embedding model everywhere** — Qwen3-Embedding-0.6B on both local and server
- **Core package independence** — memgentic must NEVER import from cloud/api/dashboard
- **Apache 2.0 License** — Free for any use
- **Privacy** — No telemetry, no data collection, no external calls (except Ollama/LLM)
- **Native acceleration is optional** — Rust/PyO3 module auto-detected at import; pure Python fallback always works

## REST API Endpoints

### Memories
```
GET    /api/v1/memories                    List with pagination + filters
GET    /api/v1/memories/pinned             List pinned memories
GET    /api/v1/memories/{id}               Get single memory
POST   /api/v1/memories                    Create memory
PATCH  /api/v1/memories/{id}               Update topics/entities/status
DELETE /api/v1/memories/{id}               Archive memory
POST   /api/v1/memories/{id}/pin           Pin memory
DELETE /api/v1/memories/{id}/pin           Unpin memory
GET    /api/v1/memories/{id}/related       Find similar memories
POST   /api/v1/memories/search             Semantic search
POST   /api/v1/memories/keyword-search     Full-text search
POST   /api/v1/memories/batch-update       Bulk update status/topics
POST   /api/v1/memories/batch-delete       Bulk archive
GET    /api/v1/topics                      Topic autocomplete
```

### Collections
```
GET    /api/v1/collections                 List collections
POST   /api/v1/collections                 Create collection
PATCH  /api/v1/collections/{id}            Update collection
DELETE /api/v1/collections/{id}            Delete collection
GET    /api/v1/collections/{id}/memories   List memories in collection
POST   /api/v1/collections/{id}/memories   Add memory to collection
DELETE /api/v1/collections/{id}/memories/{mid}  Remove from collection
```

### Skills (Agent Skills standard)
```
GET    /api/v1/skills                      List all skills
POST   /api/v1/skills                      Create skill
GET    /api/v1/skills/{id}                 Get skill with files
PUT    /api/v1/skills/{id}                 Update skill
DELETE /api/v1/skills/{id}                 Delete + remove from tool paths
POST   /api/v1/skills/{id}/files           Add file to skill
PUT    /api/v1/skills/{id}/files/{fid}     Update file
DELETE /api/v1/skills/{id}/files/{fid}     Delete file
POST   /api/v1/skills/{id}/distribute      Distribute to AI tools
GET    /api/v1/skills/{id}/distributions   List where installed
POST   /api/v1/skills/extract              Auto-extract from memories
```

### Uploads
```
POST   /api/v1/upload/text                 Upload text content
POST   /api/v1/upload/file                 Upload file (.md/.txt/.pdf)
POST   /api/v1/upload/url                  Import from URL
GET    /api/v1/uploads                     List recent uploads
```

## Skills System

Memgentic acts as a **universal skill manager** — storing and distributing skills to AI tools via the Agent Skills open standard (26+ tools support it).

### Skill Distribution
The daemon writes SKILL.md files to each tool's native discovery path:
- Claude Code: `~/.claude/skills/{name}/SKILL.md`
- Codex: `~/.codex/skills/{name}/SKILL.md`
- Cursor: `~/.cursor/rules/{name}/SKILL.md`
- OpenCode: `~/.config/opencode/skills/{name}/SKILL.md`

### Three Injection Layers
1. **Filesystem** (static) — daemon writes SKILL.md to tool paths
2. **MCP** (dynamic) — `memgentic_skills` / `memgentic_skill` tools
3. **Hooks** (automatic) — SessionStart hook injects briefing

## Dashboard Features

- **Enhanced home page** — sidebar with collections/sources, pinned row, memory grid
- **Memory cards** — source badges, topics, confidence, pin/archive quick actions
- **Collections** — user-defined groups with CRUD
- **Upload modal** — write text, upload files, import URLs
- **Skills page** — master-detail editor with file management + distribution
- **Command palette** — Cmd+K global search across memories
- **Activity feed** — real-time event log via WebSocket
- **Batch actions** — multi-select memories for bulk archive/tag
- **Inline editing** — edit topics/entities on memory detail page
- **Related memories** — vector-similarity suggestions on detail page

## Planning & Implementation

See `docs/` for technical documentation:
- `docs/PRODUCT-ROADMAP.md` — Feature phases, personas, go-live checklist
- `docs/TECHNICAL-PLAN.md` — Database schemas, API specs, skills architecture
- `docs/FRONTEND-DESIGN.md` — Component tree, state management, UI specs
- `docs/RUST-RESEARCH.md` — Rust acceleration analysis
- `docs/adr/` — Architecture Decision Records
- `docs/API_GUIDE.md` — REST API documentation
- `docs/DEPLOYMENT.md` — Docker deployment guide

### Current Status
**Phase A (Enhanced Dashboard + Upload + Collections): COMPLETE**
**Phase B (Skills + Real-time + Batch): COMPLETE**
**Phase C (Auth + Workspaces + Teams): NEXT**
**Phase D (Desktop App): PLANNED**

### Phase C Implementation Guide
Phase C adds multi-user support. See `docs/TECHNICAL-PLAN.md` for full details:
- Database migration 7: users, auth_tokens, workspaces, workspace_members tables
- Add `workspace_id` to memories, collections, skills, uploads
- JWT (HS256) + email magic links (opt-in, local mode unchanged)
- `X-Workspace-ID` header scoping on all queries
- PostgreSQL + pgvector as alternative storage backend
- Role-based access: owner, admin, member

### Phase D Implementation Guide
Phase D adds a desktop app. Key steps:
- Extract dashboard components into shared packages (core/ui/views pattern from Multica)
- Create Electron shell with electron-vite
- System tray with global Cmd+Shift+M search shortcut
- Shares all business logic with web dashboard

### How to Implement a Phase
Each plan doc contains:
- Files to create/modify
- Acceptance criteria (checkboxes)

Agents should read the milestone doc, implement each phase's tasks, run tests, and verify acceptance criteria.
