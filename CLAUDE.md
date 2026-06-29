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
│       └── server.py    MCP server (FastMCP) — 30 tools (see docs/MCP-TOOLS.md)

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
memgentic  ←──  frontend       (the dashboard calls core API; never the reverse)
```
The OSS core is the only dependency root. Anything that builds on top of it
imports from `memgentic`, never the other way around.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| MCP Server | FastMCP (mcp[cli] >=1.26) |
| Embedding | **Qwen3-Embedding-0.6B** via Ollama 0.18+ (768d MRL-truncated, Apache 2.0) |
| Vector DB | **sqlite-vec** >=0.1.9 (default, zero-config, multi-process safe) + **Qdrant** >=1.17 (server or legacy file mode) |
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
- Gemini CLI: `~/.gemini/tmp/*/chats/`
- Antigravity: `~/.gemini/antigravity/conversations/`
- Codex CLI: `~/.codex/sessions/`

## MCP Tools

The MCP server exposes 30 tools. The full reference is auto-generated at
[`docs/MCP-TOOLS.md`](docs/MCP-TOOLS.md) (a CI guard fails the build if the
file drifts from the live tool registry). Highlights:

```
memgentic_recall             Semantic search with source filtering
memgentic_search             Full-text keyword search
memgentic_remember           Store a new memory
memgentic_recent             Latest memories
memgentic_expand             Full content of a memory
memgentic_pin                Pin or unpin a memory
memgentic_sources            List sources and counts
memgentic_stats              Memory statistics
memgentic_export             Export memories as JSON
memgentic_forget             Archive (soft-delete) a memory
memgentic_configure_session  Set session-level filters

memgentic_handoff            Cross-tool resume — source-backed continuation brief
memgentic_context            What memory has been loaded into the current MCP session
memgentic_inventory          Auditable manifest of stored memories

memgentic_briefing           Recall Tiers briefing (T0 + T1 default, ~900 tokens)
memgentic_tier_recall        Render a single Recall Tier (T0–T4) explicitly
memgentic_persona_get        Read the current persona card (T0)
memgentic_persona_update     Update a persona field via dotted path

memgentic_skills             List available skills
memgentic_skill              Get a specific skill's content by name

memgentic_graph_*            Chronograph (bitemporal entity graph) — add / query / timeline / stats / invalidate

memgentic_dedupe_check       Pre-write dedup probe
memgentic_overview           Single-call combined stats / sources / topics
memgentic_refresh            Re-hydrate runtime-mutable settings
memgentic_watchers_status    Per-tool capture-watcher status

memgentic_capture_profile    Read or set the per-session capture profile
memgentic_export             Export memories as JSON
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
memgentic init            # Full onboarding: detect tools, configure models, install hooks
memgentic setup           # Reconfigure models/backend only (no tool detection)
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
- **Same embedding model everywhere** — Qwen3-Embedding-0.6B in every deployment target
- **Core package independence** — `memgentic` must NEVER import from `memgentic-api`, `memgentic-native`, or `dashboard`
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

- `docs/FRONTEND-DESIGN.md` — Component tree, state management, UI specs
- `docs/RUST-RESEARCH.md` — Rust acceleration analysis
- `docs/adr/` — Architecture Decision Records
- `docs/API_GUIDE.md` — REST API documentation
- `docs/DEPLOYMENT.md` — Docker deployment guide

## Release Automation (critical — read `docs/RELEASE.md` for the full flow)

This repo ships **three linked-version packages** via PyPI Trusted Publishing. Everything after "merge the Release PR" is unattended.

### Tags ↔ workflows ↔ PyPI envs

| Tag pattern | Publish workflow | GitHub env | PyPI project |
| --- | --- | --- | --- |
| `vX.Y.Z` | `release.yml` | `pypi` | `memgentic` |
| `api-vX.Y.Z` | `release-api.yml` | `pypi-api` | `memgentic-api` |
| `native-vX.Y.Z` | `release-native.yml` | `pypi-native` | `memgentic-native` |

Env names, workflow filenames, and owner/repo are load-bearing — renaming breaks the OIDC claim check. Never rename without updating the matching PyPI Trusted Publisher entry first.

### Secret + bot identity rules

- **`RELEASE_PLEASE_TOKEN`** — PAT owned by `@Chariton-kyp` with `contents: write` + `pull_requests: write`. Used by `release-please.yml`, `linked-version-align.yml`, and `dependabot-auto-merge.yml`. Three things break without it: (1) release tags don't fire publish workflows — `GITHUB_TOKEN` pushes are blocked by GitHub's recursive-workflow guard; (2) align-workflow commits don't re-trigger CI on the Release PR; (3) Dependabot approvals post as `github-actions[bot]` which doesn't satisfy the CODEOWNERS gate. All three workflows fall back to `GITHUB_TOKEN` if the PAT is missing so they stay green, but automation is degraded.
- **Never pin to `secrets.GITHUB_TOKEN` alone** in any release-adjacent workflow. Use `${{ secrets.RELEASE_PLEASE_TOKEN || secrets.GITHUB_TOKEN }}`.
- No PyPI API tokens. Trusted Publishing (OIDC) does the upload.

### Conventional Commits = version bumps

Only `feat` / `fix` / `perf` / `security` / `revert` move the version and surface in the CHANGELOG. `docs` / `chore` / `test` / `refactor` / `build` / `ci` / `style` are hidden. Breaking changes: `!` in type or `BREAKING CHANGE:` footer. Commitlint CI rejects bad PR titles.

### Linked-version alignment

`.github/workflows/linked-version-align.yml` + `scripts/align_linked_versions.py` auto-backfill any component left behind when `release-please`'s linked-versions plugin only lifts components with releasable commits. **Do NOT manually edit `.release-please-manifest.json`** — the align workflow owns it and will overwrite.

When `release-please` opens a Release PR: the align workflow detects version drift across the three manifest entries, picks the max as target, bumps the lagging component's `__version__.py` / `__init__.py` / `pyproject.toml` / `Cargo.toml` / `Cargo.lock`, updates the manifest, commits as `github-actions[bot]`, and pushes via PAT (re-triggers CI).

### Release-tag reconciliation (makes linked releases bulletproof)

`main` can end up version-bumped but UNTAGGED two ways, both observed here: (1) the align workflow bumps a quiet component's version *files* without release-please releasing it (no tag/Release/publish); (2) **release-please aborts release creation entirely on merge** — `There are untagged, merged release PRs outstanding - aborting` / `Expected N releases, only found 0` → `releases_created=false`, **zero** tags. Either way the manifest says X.Y.Z but no `<comp>-vX.Y.Z` tag exists, and the next release-please run re-scans the laggard from `bootstrap-sha` and proposes a **bogus major bump**. This bit `memgentic-native` at 1.0.0, `memgentic-api` at 1.1.0 (phantom `api 2.0.0`), and the whole 1.2.0 release (release-please tagged nothing).

**`.github/workflows/reconcile-release-tags.yml`** closes this for good. It is a STANDALONE workflow on `push: main` — deliberately **independent of release-please's outcome** (an in-`release-please.yml` step gated on `releases_created` misses case 2). It runs `scripts/reconcile_release_tags.py` (detection-only: derives each component's expected tag `v*`/`api-v*`/`native-v*` from the manifest, lists any missing on `origin`), then creates each missing tag at **the commit that last changed `.release-please-manifest.json`** (the release commit — not blindly `HEAD`, so it tags correctly even on a later push) and pushes via PAT, firing the matching `release*.yml`. Idempotent — a no-op once every manifest version is tagged. Net effect: manifest version X ⟹ a `…-vX` tag + GitHub Release + PyPI publish always exist, so release-please never re-scans a phantom backlog.

**Still open:** *why* release-please aborts release creation on merge in this repo (candidates: squash-merging the Release PR, `RELEASE_PLEASE_TOKEN` scope, or a release-please v17 behavior). The reconcile workflow makes it harmless, but a proper release would let release-please tag+publish itself. When release-please aborts, its Release PR keeps the `autorelease: pending` label and will block the next run — flip it to `autorelease: tagged` after the reconcile publishes (`gh pr edit <#> --remove-label "autorelease: pending" --add-label "autorelease: tagged"`).

### Branch protection

`main` requires 1 **code-owner** review per `.github/CODEOWNERS` (every path → `@Chariton-kyp`). 7 required status checks. Linear history. `enforce_admins: false` so the solo maintainer can admin-bypass when urgent; other contributors cannot.

### Dependabot policy (OSS-mainstream)

Auto-merge **patch-level only** via `dependabot-auto-merge.yml`. Minor and major bumps require manual review. Majors known to break:
- `pyo3` (API renames every 0.x → 0.y) — major + minor ignored
- `next`, `react`, `react-dom`, `tailwindcss` — majors ignored
- Typescript, eslint — majors need migration plans (don't auto-merge)

### Manual publish escape hatch

Every publish workflow accepts `workflow_dispatch` with a `tag` input. If a tag exists on GitHub but its push event was suppressed (happens when `RELEASE_PLEASE_TOKEN` was missing at tag-creation time), re-fire with:

```bash
gh workflow run release.yml         -f tag=vX.Y.Z
gh workflow run release-api.yml     -f tag=api-vX.Y.Z
gh workflow run release-native.yml  -f tag=native-vX.Y.Z
```

### SBOM (temporarily removed)

`cyclonedx-py` doesn't handle Rust-backed wheels or PEP 668 Ubuntu 24.04 cleanly. All SBOM jobs were stripped during the 0.7.0 unblock to get packages on PyPI. Re-add plan: `cargo-cyclonedx` for native; env-native cyclonedx for pure-Python packages. SLSA build-provenance attestations (`actions/attest-build-provenance`) are still emitted — that's the baseline supply-chain signal.

### CHANGELOG locations

- `/CHANGELOG.md` — human-curated aggregate (tracks the narrative across all three packages).
- `/memgentic/CHANGELOG.md` — auto-maintained by release-please (core package only).
- `/memgentic-api/CHANGELOG.md` — auto-maintained (API only).
- `/memgentic-native/CHANGELOG.md` — auto-maintained (native only).

End users see:
- **GitHub Releases** page — per-tag notes extracted from the matching package CHANGELOG.
- **PyPI sidebar → Changelog link** — points to the root `CHANGELOG.md`.
- **PyPI long description** — renders each package's own `README.md` at release time.
