# Changelog

All notable changes to Memgentic are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] — 2026-04-18 — Zero-config Local

### Added
- **sqlite-vec backend** — opt-in zero-config vector store co-located with the
  existing SQLite metadata DB. Multi-process safe via WAL, no extra binary,
  no Docker. Install with `pip install 'memgentic[sqlite-vec]'` and set
  `MEMGENTIC_STORAGE_BACKEND=sqlite_vec`. Qdrant remains the default.
- **`memgentic serve --watch`** — fuses the MCP server and capture daemon
  into a single asyncio process. One SQLite writer, one Qdrant handle, no
  lock contention. Falls back to MCP-only with a clear warning when a
  standalone daemon already holds the lock.
- **Embedding safety pin** — changing the embedding model or dimensions
  after a collection has been built now raises `EmbeddingMismatchError`
  with a step-by-step recovery plan instead of silently corrupting recall.
  Symmetric across Qdrant and sqlite-vec backends.
- **`memgentic doctor` hardware tiers** — the doctor now detects RAM, GPU,
  and CPU cores and recommends an embedding model + local LLM tier with
  actionable "apply the recommended tier" commands.

### Fixed
- MCP stdio: structlog now writes to stderr (previously polluted stdout and
  broke strict MCP clients). The `memgentic serve` banner also moved to
  stderr — stdout stays pure JSON-RPC in both plain and `--watch` modes.
- File adapters: memory-observer and meta-tooling conversation directories
  are now excluded by default from ingestion — they polluted semantic
  search ranking without adding user-relevant context.
- `.daemon.pid` is reclaimed when its PID is dead. A crashed or killed
  serve/daemon no longer permanently blocks future starts.
- sqlite-vec filter handling: over-fetches a 10× KNN candidate pool when
  payload filters are present so selective platform/content-type queries
  don't silently starve recall compared to Qdrant.
- Doctor `sqlite-vec` install hint escapes Rich markup so `[sqlite-vec]`
  prints verbatim in `pip install 'memgentic[sqlite-vec]'`.

### Dependencies
- PyO3 upgraded 0.22 → 0.24 for the Rust extension (security).

## [0.4.0] — 2026-04-11 — Knowledge Platform

### Added
- **Rust Native Acceleration** (`memgentic-native`) — PyO3 extension module with 27 unit tests
  - Credential scrubbing 20-50x faster (Aho-Corasick compatible)
  - Text overlap / Jaccard dedup 10-20x faster
  - Noise detection & classification 5-10x faster
  - Streaming JSONL parser, ChatGPT JSON flattener, Protobuf wire-format parser, Markdown splitter
  - petgraph-based knowledge graph engine (10-50x faster than NetworkX)
  - Auto-detected at import; pure Python fallback always works

- **Enhanced Dashboard** (Phase A)
  - New home page with collections sidebar, pinned memory row, responsive memory grid
  - Memory cards with source badges, topic badges, confidence dots, quick actions
  - Inline editing of topics and entities on memory detail page
  - Related memories via vector similarity on detail page
  - Command palette (Cmd+K) global semantic search
  - Batch selection with shift+click and bulk archive/tag actions

- **Collections System**
  - User-defined groups for organizing memories (CRUD + membership)
  - Collections sidebar navigation with colored icons
  - 7 new API endpoints

- **Manual Knowledge Upload**
  - Upload modal with three tabs: Write, File, URL
  - Supports `.md`, `.txt`, `.pdf` file ingestion
  - URL fetching with text + title extraction
  - Topic autocomplete from existing memories

- **Pin / Unpin Memories**
  - Star to pin important memories for quick access
  - Pinned row always visible at top of dashboard
  - 3 new API endpoints + MCP `memgentic_pin` tool

- **Universal Skills System** (Phase B) — Memgentic as a universal skill manager
  - Create, edit, delete skills with multi-file support (Agent Skills standard)
  - **Skill Distributor** writes `SKILL.md` files to each tool's native discovery path:
    - `~/.claude/skills/{name}/SKILL.md` — Claude Code
    - `~/.codex/skills/{name}/SKILL.md` — Codex
    - `~/.config/opencode/skills/{name}/SKILL.md` — OpenCode
    - `~/.cursor/rules/{name}/SKILL.md` — Cursor
  - **Skill GitHub Import** — pull a SKILL.md folder from any GitHub repo
  - **LLM Auto-Extraction** — synthesize skills from existing memories (with naive fallback)
  - **Daemon Sync Loop** — auto-redistributes skills every 60s, idempotent
  - **Skills Page** in dashboard with master-detail editor + file management
  - 11 new API endpoints + 2 MCP tools (`memgentic_skills`, `memgentic_skill`)

- **Real-time Activity Feed**
  - WebSocket event stream now includes skill events and memory pin events
  - Sliding activity panel in dashboard with event log
  - Live "captured today" counter in header

- **Ingestion Job Tracking**
  - New `ingestion_jobs` table + 3 API endpoints
  - Floating progress widget in dashboard with cancel button
  - Auto-polls every 3 seconds for live updates

- **Batch Operations**
  - `POST /api/v1/memories/batch-update` — bulk topic/status updates
  - `POST /api/v1/memories/batch-delete` — bulk archive

- **Documentation**
  - `docs/PRODUCT-ROADMAP.md` — feature phases, personas, MVP checklist
  - `docs/TECHNICAL-PLAN.md` — schemas, APIs, skills architecture, dual-mode storage
  - `docs/FRONTEND-DESIGN.md` — component tree, state, UI specs
  - `docs/RUST-RESEARCH.md` — Rust acceleration analysis
  - `docs/LANDING.md` — marketing landing page content
  - CLAUDE.md updated with Phase C/D implementation guides

### Changed
- WebSocket events now use typed format with topic prefixes (memory:created, skill:updated, etc.)
- CORS allow_methods now includes PUT (for skill update endpoints)
- Batch API uses standardized `{memory_ids, updates}` request body
- All REST API routes now emit events to the WebSocket bus

### Fixed
- `save_memory` and `save_memories_batch` now preserve `is_pinned` and `pinned_at` columns on update (previously reset by INSERT OR REPLACE)
- `GET /api/v1/memories/pinned` route ordering — moved before `GET /memories/{memory_id}` to avoid path shadowing
- Codex markdown regex no longer panics (replaced unsupported lookahead with capture group)
- `RustKnowledgeGraph` async methods now use `asyncio.to_thread` to avoid blocking the event loop
- `UploadResponse` field naming aligned between frontend and backend (`error_message`)

## [0.3.0] — 2026-04-09 — Production Hardening

### Added
- **Phase 0: Safety & Reliability**
  - Credential scrubbing pipeline with 15+ patterns (OpenAI, Anthropic, GitHub, AWS, Google, Slack, Bearer, JWT, PEM) — enabled by default
  - SQLite WAL mode + busy_timeout=5000 for concurrent access
  - Full hybrid search in CLI (`memgentic search` now uses semantic + keyword + graph)
  - MCP session isolation via proper context derivation

- **Phase 1: Intelligence & Search**
  - Fact distillation node in intelligence pipeline (enabled by default)
  - Write-time memory deduplication (enabled by default)
  - Query intent detection (decision/learning/preference/bug_fix + time filters)
  - Content-value noise filter (pleasantries, tool output, stack traces)
  - 3-layer retrieval (`detail=index|preview|full`) via MCP
  - `memgentic_expand` MCP tool for drill-down
  - Batch memory lookup (fixed N+1 in hybrid search)

- **Phase 2: Polish**
  - `memgentic status` CLI command
  - Cursor adapter (SQLite-based, read-only)
  - OpenAI embedding provider fallback (removes hard Ollama requirement)
  - Fallback briefing from top-importance memories when recent window is empty
  - Configurable SessionStart hook parameters

### Fixed
- Silent data loss in keyword-only search results (empty payloads)
- `mneme_mcp` server name → `memgentic_mcp`
- Session config global leakage across concurrent MCP sessions

### Performance
- N+1 query eliminated in hybrid search scoring loop
- SQLite WAL enables concurrent daemon+MCP reads

## [0.2.0] — 2026-03-30 — Auto-Injection Layer
- SKILL.md for Claude Code progressive disclosure
- SessionStart + UserPromptSubmit hooks (UserPromptSubmit is a no-op for performance)
- Compact CLI output format (`--format compact|json`)
- Hook installer for Claude Code settings

## [0.1.0] — 2026-03-15 — Initial Release
- Core memory layer with SQLite + Qdrant
- 9 adapters (Claude Code, Gemini CLI, Codex CLI, Copilot CLI, Antigravity, Aider, ChatGPT, Claude Web)
- MCP server with 10 tools
- Daemon-based auto-capture
- Knowledge graph (NetworkX)
- Hybrid search (semantic + FTS5 + graph RRF)
