# Changelog

All notable changes to Memgentic are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] — 2026-04-22 — Intelligence Upgrades + Distribution

Linked release across all three packages (`memgentic` / `memgentic-api` / `memgentic-native`).

### Added
- **Recall Tiers (T0–T4)** — progressive context loader: T0 Persona, T1 Horizon (hybrid score + MMR), T2 Orbit, T3 Deep Recall, T4 Atlas. Adaptive token budget that auto-scales to model context. New MCP `memgentic_tier_recall` tool; upgraded `memgentic_briefing`. Dashboard `/briefing` page with tier picker, weight sliders, and live preview.
- **Persona** — structured identity/people/projects/preferences with LLM bootstrap and atomic file locking. `memgentic persona {init,show,edit,validate,…}` CLI; REST `/api/v1/persona/*`; MCP `memgentic_persona_get` + `memgentic_persona_update`; dashboard `/persona` page.
- **Watchers** — cross-tool automatic capture umbrella. Hook scripts for Claude Code and Codex. File watchers for Aider, Antigravity, Copilot CLI, Gemini CLI behind a `FILE_WATCHERS` registry. `memgentic watchers {install,uninstall,enable,disable,status,logs}` CLI; REST `/api/v1/watchers/*`; MCP `memgentic_watchers_status`; dashboard `/watchers` page.
- **Chronograph** — bitemporal entity-relationship graph (separate `chronograph.sqlite`). LLM triple extractor, validation queue, `memgentic graph` CLI subgroup (11 commands), 13 REST endpoints, 5 MCP tools, dashboard `/chronograph` page.
- **Capture Profiles** (raw / enriched / dual) — pipeline dispatches on profile; CLI `--profile`; REST + MCP surface; dashboard selector.
- **MCP surface** expanded 14 → **27 tools**. New: `dedupe_check`, `overview`, `refresh`, `watchers_status`. `docs/MCP-TOOLS.md` auto-generated from the live tool registry with a CI drift guard.
- **Benchmarks (phase 2)** — runners for LoCoMo, ConvoMem, MemBench, Cross-Tool Transfer in `benchmarks/runners/`. Profile flag now wires through `BenchmarkHarness` → `IngestionPipeline.ingest_conversation`. `docs/BENCHMARKS.md` has the full reproducibility walkthrough. Actual numbers are run-then-publish.
- **Dashboard landing page** (`/welcome`) with Recall Tiers diagram + Watchers matrix + "Why Memgentic".

### Fixed
- **`lxml`** bumped 6.0.4 → 6.1.0 to close the GHSA XXE CVE (Dependabot alert #22).
- **Antigravity protobuf** — pinned wire-format version (`wireformat.v1-2026-04`) + fail-safe decode that logs a structured warning and skips corrupt payloads instead of raising.
- **WebSocket reconnect** — broke a `scheduleReconnect` / `connect` circular reference via ref-indirection. Fixes the "variable accessed before declared" lint that shaded a live stale-closure risk.
- **Release automation** — `release-please` + `scorecard-action` pin + Dependabot workspace scope unblocked after weeks of red workflows.

### Changed
- **Default capture profile** now persists in the `runtime_settings` kv table; MCP `memgentic_refresh` re-hydrates it live without reopening stores.
- **Dashboard eslint** now runs in CI; 0 errors, 0 warnings on main.
- **Dependabot `pip` scope** fixed to the workspace root (was scanning member pyprojects without the lock).
- **Branch protection** on `main` now requires a code-owner review on every PR (solo admin-bypass retained).

## [0.6.0] — 2026-04-19 — Zero-config by default

### Breaking Changes
- **Default storage backend is now `sqlite_vec`** (was `local` / Qdrant file mode).
  Users upgrading from 0.4.x or 0.5.0 who have existing Qdrant data under
  `~/.memgentic/data/qdrant/` must run:
  ```
  memgentic migrate-storage --from local --to sqlite_vec
  ```
  to copy memories to the new default store. Memgentic will print a clear
  warning on first start if legacy Qdrant data is detected. To continue using
  Qdrant file mode instead, set `MEMGENTIC_STORAGE_BACKEND=local`.

### Added
- `sqlite-vec>=0.1.9` promoted from optional extra to core dependency — a
  working install no longer requires `pip install 'memgentic[sqlite-vec]'`.
  The `[sqlite-vec]` extra is retained as a no-op alias for back-compat.
- Migration detection warning: on first sqlite-vec start, if a legacy Qdrant
  data directory is found and the new SQLite DB is empty, a loud one-time
  warning is printed to stderr with the exact command to run.
- **`memgentic migrate-storage`** — new CLI command that copies every memory
  + embedding between vector backends (`local` / `qdrant` / `sqlite_vec`).
  Supports `--dry-run`, `--force`, and streams a rich progress bar. Metadata
  (SQLite) is shared and untouched; migration is purely additive.
- **Consolidated onboarding**: `memgentic init` is now the one full-onboarding
  command (detect AI tools → backend/embedding/LLM picker → inject memory
  instructions → optional import). New `--yes/-y` flag skips interactive
  prompts for scripted use. `memgentic setup` stays as a reconfigure-only
  escape hatch (steps 1-4 without tool detection or hook installation).
- **Tag-triggered release workflow**: pushing `v*` tags builds both packages
  with `uv build`, publishes via PyPI Trusted Publishing (OIDC — no PAT),
  and creates a GitHub Release with the matching CHANGELOG section as body.
  New `build-sanity` workflow satisfies the required `build` status check.

### Changed
- `memgentic doctor` check output is now tri-state (`OK`/`WARN`/`FAIL`).
  Qdrant unreachable under the default `local` backend renders as `WARN`
  (the tool transparently falls back to file mode — nothing is broken);
  only genuine misconfigurations still render red. GPU detection also
  downgraded to `WARN` since GPU is optional.

### Fixed
- Pre-existing test suite drift: `test_mcp_server.py` fixture drifted after
  the v0.5.0 lifespan rename (wrong dict key) and `test_daemon.py` fixture
  left `MagicMock` instances on numeric settings fields, causing an async
  spin-loop that hung the suite. Suite now goes from ~531 passing / ~23
  failing to 589 passing / 0 failing.
- `ossf/scorecard-action` pin repointed at a real SHA (`v2.4.3` — the prior
  pin was a hallucinated commit that broke every weekly Scorecard run).

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
