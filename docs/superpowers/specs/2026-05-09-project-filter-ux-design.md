# Project Filter UX Overhaul — Architecture Specification

**Date**: 2026-05-09
**Status**: Design — pending user review
**Owners**: Chariton (decisions), code-architect agent (architecture review)

---

## What Changed From the Brainstorm (Read First)

Four landmines discovered during codebase review. Review these before anything else.

**Landmine 1 — Migration number collision.** The brainstorm called this "Migration 10". Migration 10 is already occupied by the dreams tables (`migrations.py` lines 203–256). The JSONL backfill migration must be **Migration 11**. Applying a duplicate version silently overwrites the schema_version row and leaves the dreams schema in an unknown state on already-upgraded databases.

**Landmine 2 — JSONL reads inside `migrate()` must not happen.** `MetadataStore.initialize()` calls `migrate()` synchronously on every startup — MCP server, daemon, every CLI subcommand. Migration 9's backfill was safe because it reads only the existing `file_path` column from SQLite (no I/O). Reading hundreds of MB of JSONL inside `migrate()` blocks startup for minutes on first run after upgrade, cannot be interrupted mid-run without leaving the schema_version row unwritten (non-atomic), and can fail on locked/deleted session files. Migration 11 must be schema-only (a partial index). The JSONL re-read lives in an explicit CLI command: `memgentic projects backfill-jsonl`.

**Landmine 3 — git subprocess is async-unsafe in the ingestion pipeline.** A sync `subprocess.run(["git", ...])` called directly from an adapter coroutine blocks the event loop during batch ingestion. The LRU-cached function must be sync, wrapped in `asyncio.to_thread()` at the call site.

**Landmine 4 — WSL UNC paths break `git rev-parse`.** Paths of the form `\\wsl.localhost\Ubuntu\home\...` or `\\wsl$\...` cause git to fail with "fatal: not a git repository" (git can't `chdir` to a UNC path on Windows). Detect the UNC prefix before calling git and return `None` immediately, falling through to bare `cwd.name`.

---

## Locked Decisions

The following were settled during a 4-question brainstorm. They are **constraints** for this spec, not open for re-debate without explicit reopening.

| Question | Decision | Rationale |
|---|---|---|
| **Q1 — Default ranking behavior** | **B+C combo: boost + cross-project section** | Auto-boost current project ×1.5 importance. Cross-project hits appear in labeled "Related from other projects" section when score ≥ 0.6 × top primary score, max 5 hits. Configurable via env vars. |
| **Q2 — Aliasing strategy** | **C combo: git toplevel + TOML aliases + merge CLI** | Resolution chain: git remote URL stem (opt-in only) → git toplevel → bare cwd → empty. TOML at `~/.memgentic/projects.toml`. Transitive resolution with cycle guard, first-match-wins. Empty `to: ""` collapses to "(unknown)". |
| **Q3 — Legacy backfill** | **D combo: schema-only migration + repair CLI + JSONL backfill CLI** | Migration 11 is a partial index only. Two CLI commands: `repair` (fast, alias-only, idempotent) and `backfill-jsonl` (slow, JSONL re-read, run once). |
| **Q4 — Dashboard semantics** | **E combo: multi-select + AND-stack** (with B1 for current indicator) | Multi-select project checkboxes, AND-stack with source + content_type. Multi-value REST query param. **No "Current project" banner in dashboard** (user explicitly rejected — wants minimal hooks/dependencies). |
| **Q-A — Git remote URL collapse** | **A1: opt-in only** | Default OFF, enable via `[settings] use_remote_url_collapse = true` in TOML. |
| **Q-B — Dashboard "current" signal** | **B1: drop entirely** | No indicator, no hook, no `~/.memgentic/current.json`. Zero implementation. |

**Unilateral decisions** (Claude proposed, user accepted):
- Single module `project.py` (no separate `project_aliases.py` — YAGNI)
- `functools.lru_cache(maxsize=512)` for git toplevel and remote URL resolution
- "current project" definition per surface:
  - **Daemon**: never has one (just captures with proper aliases)
  - **MCP / CLI**: `os.getcwd()` + `MEMGENTIC_CURRENT_PROJECT` env override + git toplevel resolution
  - **Dashboard**: none (B1)

---

## Independent Evaluation of Each Decision

### Q1 — Boost + cross-project section

**Verdict: Agree with two architectural caveats.**

The ×1.5 current-project boost must be computed **after** `importance * decay` and tracked as a separate named multiplier. If folded into `importance_score` itself, you get triple-compounding with the existing temporal and importance weights. The current code at `graph/search.py:262` computes `scores[mid] = scores[mid] * importance * decay_factor`. The boost must be an additional pass after that line.

The cross-project threshold must be computed against the **unboosted score**, not the boosted score. If you threshold against the boosted top, a true 0.6× cross-project candidate fails the gate by construction. Each result dict carries both `score_raw` (pre-boost) and `score` (post-boost, used for ranking). The gate checks `result["score_raw"] >= 0.6 * top_raw`.

The partition itself (primary vs. "Related from other projects") happens **at the surface**, not inside `hybrid_search`. The function's return type stays `list[dict]`. Every existing caller (REST, basic CLI, tests) is unaffected. Only `memgentic_recall` (MCP text rendering) and the dashboard result panel consume the partition.

### Q2 — Aliasing chain

**Verdict: Agree on design; disagree on one detail about `auto` sentinel interaction.**

The brainstorm says `auto` resolves to `Path.cwd().name.lower()`. That conflicts with how ingestion derives the key — ingestion adapters use `derive_project(cwd=...)` which applies git-toplevel resolution when enabled. If a user opens `memgentic recall` from a subdirectory of `memgentic-public-export`, `Path.cwd().name.lower()` returns the subdirectory name, not `memgentic-public-export`. The `auto` sentinel must use the same resolution chain as ingestion.

The `MEMGENTIC_CURRENT_PROJECT` env override solves both: daemon sessions, subshell invocations, and explicit overrides in .env. Give this higher priority than the git/cwd derivation.

The `auto` sentinel keeps its **strict-filter semantics** (existing behavior, unchanged). The new boost behavior is distinct: it fires when `current_project` is resolved implicitly for the boost pass, not when `auto` is in `project=`. Do not conflate them.

### Q3 — Migration 11 schema-only + repair CLI

**Verdict: Disagree with the brainstorm's "Migration 10 auto JSONL re-read." Agree with the CLI repair part.**

As stated in Landmine 2: migration must be schema-only. The JSONL re-read lives in `memgentic projects backfill-jsonl`. This command is idempotent (only processes rows where `project = ''`), resumable, and produces a progress report. It can be run once manually after upgrade.

The alias repair (`memgentic projects repair`) is correctly specified: pure SQL updates to existing rows, zero file I/O, idempotent. This is safe to run frequently.

### Q4 — Dashboard multi-select + AND-stack

**Verdict: Agree. One concrete implementation detail is missing from the brainstorm.**

The existing `CollectionsSidebar` at `collections-sidebar.tsx:264-268` calls `onProjectChange` which calls `onSourceChange(undefined)` (clears source filter). This mutex must be removed as part of AND-stack. The sidebar state model changes from three mutually-exclusive toggles to independent filter checkboxes. The `page.tsx` `listMemories` call (line 121-127) passes `project: projectFilter` as a scalar — this must change to `projects: projectFilters[]` and the `api.ts` `listMemories` function must use `qs.append("project", p)` instead of `qs.set`.

On the REST side, FastAPI handles repeated query params natively with `project: list[str] | None = Query(default=None)`. The slowapi rate limiter does not inspect query parameters, so no changes to `limiter` are needed.

### Q-A — Git remote URL collapse

**Verdict: Agree. Additional constraint: only runs on the non-WSL-path code path (Landmine 4).**

### Q-B — No dashboard "current project" indicator

**Verdict: Agree. Zero implementation required.**

---

## Architecture

### Existing Modules Affected

| Module | Path | Role in this feature |
|--------|------|---------------------|
| `project.py` | `memgentic/memgentic/processing/project.py` | All alias/resolution logic added here |
| `migrations.py` | `memgentic/memgentic/storage/migrations.py` | Migration 11 schema entry (no Python backfill) |
| `metadata.py` | `memgentic/memgentic/storage/metadata.py` | No changes needed; `get_project_stats()` already exists |
| `search.py` | `memgentic/memgentic/graph/search.py` | Add `current_project`, `score_raw`, boost pass |
| `server.py` | `memgentic/memgentic/mcp/server.py` | Resolve current project, pass to search, render partition |
| `cli.py` | `memgentic/memgentic/cli.py` | New `projects` command group |
| `config.py` | `memgentic/memgentic/config.py` | Three new env vars for boost tuning |
| `memories.py` (API) | `memgentic-api/memgentic_api/routes/memories.py` | Multi-value `project` param |
| `api.ts` | `dashboard/src/lib/api.ts` | Multi-value project param |
| `collections-sidebar.tsx` | `dashboard/src/components/collections/collections-sidebar.tsx` | Multi-select, remove mutex |
| `page.tsx` | `dashboard/src/app/page.tsx` | `projectFilter` → `projectFilters: string[]` |

### New Files

| File | Purpose |
|------|---------|
| `~/.memgentic/projects.toml` | User alias config (created by `memgentic projects alias`; never checked in) |
| `projects.toml.example` | Checked into repo root; documents format and starter denylist |

### No New Python Modules

All alias + resolution logic lives in the existing `processing/project.py`. The brainstorm considered a separate `project_aliases.py` and discarded it (YAGNI). That decision stands — the module is already narrow and well-contained.

---

## Component Design

### `memgentic/memgentic/processing/project.py` (extended)

**Public API additions:**

```python
# TOML config reader — cached at module level after first read
def load_project_aliases(toml_path: Path | None = None) -> dict[str, str]:
    """Parse ~/.memgentic/projects.toml and return resolved alias map.

    Performs transitive resolution: if a -> b and b -> c, a resolves to c.
    Cycle guard: if a cycle is detected, raises ValueError with the cycle path.
    First-match-wins among [[alias]] entries.
    Returns: normalized {from_key: to_key} where to_key may be "" (collapse to unknown).
    """

def resolve_project(key: str, alias_map: dict[str, str]) -> str:
    """Apply alias_map to a project key. Handles transitive chains.
    Returns key unchanged if not in map.
    """

def invalidate_alias_cache() -> None:
    """Clear the module-level alias cache. Call after TOML write."""

# Git discovery — sync, lru_cache(maxsize=512)
@functools.lru_cache(maxsize=512)
def _git_toplevel_sync(cwd: str) -> str | None:
    """Run git rev-parse --show-toplevel synchronously. Returns None on failure.
    Skips UNC paths (\\wsl.localhost\... and \\wsl$\...) immediately.
    """

@functools.lru_cache(maxsize=512)
def _git_remote_url_sync(git_root: str) -> str | None:
    """Run git remote get-url origin synchronously. Returns None on failure.
    Only called when use_remote_url_collapse=True in projects.toml.
    """

# Async wrappers for use in ingestion pipeline and MCP
async def git_toplevel(cwd: str) -> str | None:
    """Async wrapper: asyncio.to_thread(_git_toplevel_sync, cwd)."""

async def git_remote_url(git_root: str) -> str | None:
    """Async wrapper: asyncio.to_thread(_git_remote_url_sync, git_root)."""

# Extended derive_project — existing function gains two new optional params
async def derive_project_full(
    *,
    cwd: str | None = None,
    file_path: str | None = None,
    slug: str | None = None,
    use_git: bool = False,
    use_remote_url: bool = False,
    alias_map: dict[str, str] | None = None,
) -> str:
    """Full resolution chain:
    1. If use_remote_url and use_git: git remote URL stem (opt-in only)
    2. If use_git: git toplevel name
    3. Bare cwd basename (existing derive_project logic)
    4. Slug decoding (existing logic)
    5. Empty string
    Then apply alias_map if provided.
    """

# Current-project resolver for MCP/CLI surfaces
async def resolve_current_project(
    env_override: str | None = None,
    use_git: bool = False,
) -> str | None:
    """Resolve the current project for the calling process.
    Resolution order:
    1. MEMGENTIC_CURRENT_PROJECT env var (or env_override param)
    2. git toplevel name of os.getcwd() (if use_git=True)
    3. os.getcwd() basename
    Returns None if empty.
    Applies alias_map automatically.
    """
```

**TOML format:**

```toml
# ~/.memgentic/projects.toml

[settings]
# Set to true to collapse memories from multiple clones of the same git repo
# (identified by matching git remote origin URL stem) into one project key.
# Default: false. Only applies to new ingestion; run `memgentic projects repair`
# after changing to recompute existing rows.
use_remote_url_collapse = false

# Aliases: each [[alias]] maps one or more project keys to a canonical name.
# `from` is a list of source keys (normalized lowercase).
# `to` is the target key. Use "" to collapse to unknown (sink garbage projects).
# First matching alias wins. Transitive chains are resolved (a→b, b→c → a resolves to c).
# Cycles are rejected at load time with an error.

[[alias]]
from = ["allweb-projects-allvolution2", "allweb-projects"]
to = "allweb-projects"

[[alias]]
from = ["mnt-c-users-harit-desktop-inproma"]
to = "inproma"

[[alias]]
from = ["memgentic"]
to = "memgentic-public-export"

# Garbage sink: collapse throwaway directories
[[alias]]
from = ["new-folder", "temp", "untitled", "desktop", "new-project"]
to = ""
```

**Transitive resolution algorithm:**

```python
# Loaded once, cached module-level, invalidated by invalidate_alias_cache()
_alias_cache: dict[str, str] | None = None

def _resolve_transitive(key: str, raw_map: dict[str, str]) -> str:
    """Follow chain until stable or cycle detected. Max depth 16."""
    seen: set[str] = {key}
    current = key
    for _ in range(16):
        target = raw_map.get(current)
        if target is None or target == current:
            return current
        if target in seen:
            raise ValueError(f"Alias cycle detected: {seen} -> {target}")
        seen.add(target)
        current = target
    raise ValueError(f"Alias chain too deep from {key!r}")
```

---

### `memgentic/memgentic/graph/search.py` (modified)

**Signature change to `hybrid_search`:**

```python
async def hybrid_search(
    query: str,
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    graph: KnowledgeGraph | RustKnowledgeGraph | None = None,
    session_config: SessionConfig | None = None,
    limit: int = 10,
    rrf_k: int = 60,
    settings: MemgenticSettings | None = None,
    user_id: str = "",
    *,
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    graph_weight: float = DEFAULT_GRAPH_WEIGHT,
    min_score: float = 0.0,
    current_project: str | None = None,          # NEW — caller resolves, function is pure
    project_boost: float = 1.5,                  # NEW — MEMGENTIC_CURRENT_PROJECT_BOOST
    cross_project_threshold: float = 0.6,        # NEW — MEMGENTIC_CROSS_PROJECT_THRESHOLD
    cross_project_max: int = 5,                  # NEW — MEMGENTIC_CROSS_PROJECT_MAX
) -> list[dict]:
```

**Return dict schema — additions:**

```python
{
    "id": str,
    "score": float,          # post-boost, used for ranking
    "score_raw": float,      # pre-boost, used for cross-project threshold
    "is_current_project": bool | None,   # None when current_project=None
    "payload": dict,
    "semantic_rank": int | None,
    "keyword_rank": int | None,
    "graph_boosted": bool,
    "search_method": str,
}
```

**Boost implementation (after the existing `importance * decay` pass at line 262):**

```python
top_raw: float = 0.0
for mid in scores:
    if scores[mid] > top_raw:
        top_raw = scores[mid]

score_raw: dict[str, float] = dict(scores)  # snapshot before boost

if current_project:
    for mid, mem in memories_map.items():
        if mid in scores and (mem.project or "") == current_project:
            scores[mid] *= project_boost

# Each result dict carries score_raw, is_current_project, etc.
# The function does NOT partition into primary/related — that is the surface's job.
```

**What does NOT change inside `hybrid_search`:** The function does not partition results. It does not read env vars. It does not call `os.getcwd()`. All of that is surface-layer responsibility.

---

### `memgentic/memgentic/mcp/server.py` (modified)

**`RecallInput` changes:** None. The MCP tool already has `project`, `projects`, `exclude_projects`. No schema change.

**Inside the recall handler:**

```python
# Resolve current project for boost pass — purely additive, does not filter
current_project: str | None = None
if HAS_INTELLIGENCE:
    from memgentic.processing.project import resolve_current_project
    current_project = await resolve_current_project(
        env_override=os.environ.get("MEMGENTIC_CURRENT_PROJECT"),
        use_git=settings.enable_git_project_resolution,
    )

results = await hybrid_search(
    ...,
    current_project=current_project,
    project_boost=settings.current_project_boost,
    cross_project_threshold=settings.cross_project_threshold,
    cross_project_max=settings.cross_project_max,
)
```

**Text rendering partition:**

```python
# Partition results for display only — does not affect what was stored or ranked
if current_project and any(r.get("is_current_project") is not None for r in results):
    primary = [r for r in results if r.get("is_current_project", True)]
    raw_scores = [r["score_raw"] for r in primary]
    top_raw = max(raw_scores) if raw_scores else 0.0
    threshold = top_raw * settings.cross_project_threshold
    related = [
        r for r in results
        if not r.get("is_current_project", True)
        and r["score_raw"] >= threshold
    ][: settings.cross_project_max]
    # Render primary block, then "--- Related from other projects ---", then related
else:
    primary = results
    related = []
```

The `is_current_project` field is populated inside `hybrid_search` when `current_project` is non-None: `is_current_project = (mem.project or "") == current_project`.

---

### `memgentic/memgentic/storage/migrations.py` (modified)

**Migration 11:**

```python
(
    11,
    "project_aliases_index — partial index for empty-project repair discovery",
    [
        # Partial index makes `memgentic projects backfill-jsonl` and `repair`
        # efficient on large databases: both commands scan WHERE project = ''.
        "CREATE INDEX IF NOT EXISTS idx_memories_project_empty "
        "ON memories(id, file_path) WHERE project = ''",
    ],
),
```

**No Python backfill in `migrate()`.** The JSONL re-read happens in the CLI command described below. Migration 11 is schema-only and runs in milliseconds.

---

### `memgentic/memgentic/cli.py` (modified — new `projects` group)

```python
@main.group()
def projects():
    """Manage project keys — aliases, merges, and backfills."""

@projects.command("list")
async def projects_list():
    """Show all projects with memory counts and alias mappings."""

@projects.command("alias")
@click.argument("from_key")
@click.option("--to", required=True, help="Target project key ('' to sink to unknown)")
async def projects_alias(from_key: str, to: str):
    """Add a single alias mapping to ~/.memgentic/projects.toml.
    Appends [[alias]] entry; does NOT auto-run repair. Run `projects repair` after."""

@projects.command("merge")
@click.argument("key_a")
@click.argument("key_b")
@click.option("--into", required=True, help="Canonical name to merge both into")
async def projects_merge(key_a: str, key_b: str, into: str):
    """Add alias entries for both keys pointing to --into, then run repair."""

@projects.command("repair")
@click.option("--dry-run", is_flag=True)
async def projects_repair(dry_run: bool):
    """Recompute project keys for all rows using current alias table.

    Zero JSONL I/O. Reads alias map from ~/.memgentic/projects.toml,
    loads all (id, project) pairs from SQLite, applies resolve_project(),
    writes rows where the key changed. Idempotent. Safe to run anytime.
    """

@projects.command("backfill-jsonl")
@click.option("--source", "-s", multiple=True,
              help="Limit to specific adapters: codex_cli, gemini_cli (default: all)")
@click.option("--dry-run", is_flag=True)
async def projects_backfill_jsonl(source: tuple[str, ...], dry_run: bool):
    """Re-read session_meta from JSONL files to fill empty-project rows.

    Only processes memories WHERE project = ''. Safe to run multiple times.
    Covers the 696 unknown memories that Migration 9 couldn't reach because
    the project key lives inside session_meta events, not file_path patterns.

    Adapters covered:
    - codex_cli: reads session_meta.cwd from rollout-*.jsonl
    - gemini_cli: reads top-level 'cwd' from old JSON format files

    After running, call `projects repair` to apply aliases to newly filled rows.
    """
```

---

### `memgentic-api/memgentic_api/routes/memories.py` (modified)

**`list_memories` endpoint signature change:**

```python
@router.get("/memories")
async def list_memories(
    request: Request,
    metadata_store: MetadataStoreDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source: str | None = None,
    content_type: str | None = None,
    project: list[str] | None = Query(          # was: str | None
        default=None,
        description=(
            "Filter by project key (repeatable). Pass multiple times for OR semantics: "
            "?project=foo&project=bar returns memories from foo OR bar. "
            "Pass the empty string to fetch only unassigned memories."
        ),
    ),
) -> MemoryListResponse:
```

`config.include_projects = [p.strip().lower() for p in project]` when project is non-None.

The existing `get_memories_by_filter` in `MetadataStore` already handles `session_config.include_projects` as a list, so no metadata layer changes are needed.

---

### `dashboard/src/lib/api.ts` (modified)

```typescript
export async function listMemories(params: {
  page?: number;
  page_size?: number;
  source?: string;
  content_type?: string;
  projects?: string[];          // was: project?: string
}): Promise<MemoryListResponse> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.source) qs.set("source", params.source);
  if (params.content_type) qs.set("content_type", params.content_type);
  (params.projects ?? []).forEach((p) => qs.append("project", p));
  return fetchJson(`${API_BASE}/memories?${qs}`);
}
```

---

### `dashboard/src/components/collections/collections-sidebar.tsx` (modified)

**Interface change:**

```typescript
interface CollectionsSidebarProps {
  activeView: string | null;
  onViewChange: (view: string | null) => void;
  activeSource: string | undefined;
  onSourceChange: (source: string | undefined) => void;
  activeProjects: string[];                    // was: activeProject?: string
  onProjectsChange: (projects: string[]) => void;  // was: onProjectChange?
}
```

**Behavior changes:**
- Projects section renders checkboxes instead of radio-style single-toggle buttons.
- Clicking a project key toggles it in/out of `activeProjects` array. Does not call `onViewChange(null)` or `onSourceChange(undefined)` — the mutex is gone.
- Clicking a source filter no longer clears `activeProjects`. Clicking "All Memories" clears everything.
- Visual treatment: checked state renders the existing `bg-muted font-medium` class; unchecked renders `text-muted-foreground`.

**`page.tsx` state change:**

```typescript
const [projectFilters, setProjectFilters] = useState<string[]>([]);  // was: string | undefined
```

`useMemories` hook call:

```typescript
useMemories({
  page,
  page_size: pageSize,
  source: sourceFilter,
  content_type: contentTypeFilter,
  projects: projectFilters,      // was: project: projectFilter
})
```

`page.tsx` effect reset:

```typescript
useEffect(() => {
  setPage(1);
}, [debouncedQuery, sourceFilter, contentTypeFilter, projectFilters, activeView]);
```

---

### `memgentic/memgentic/config.py` (modified)

Three new fields:

```python
current_project_boost: float = Field(
    default=1.5,
    ge=1.0,
    le=5.0,
    description=(
        "Score multiplier applied to memories from the current project during "
        "hybrid search. 1.0 disables the boost. Set via MEMGENTIC_CURRENT_PROJECT_BOOST."
    ),
)
cross_project_threshold: float = Field(
    default=0.6,
    ge=0.0,
    le=1.0,
    description=(
        "Minimum score ratio (vs. top unboosted primary result) for a cross-project "
        "memory to appear in the 'Related from other projects' section. "
        "Set via MEMGENTIC_CROSS_PROJECT_THRESHOLD."
    ),
)
cross_project_max: int = Field(
    default=5,
    ge=0,
    le=20,
    description=(
        "Maximum number of cross-project hits returned in the 'Related' section. "
        "0 disables the section. Set via MEMGENTIC_CROSS_PROJECT_MAX."
    ),
)
enable_git_project_resolution: bool = Field(
    default=False,
    description=(
        "Enable git toplevel + remote URL resolution in derive_project_full(). "
        "When False, falls back to bare cwd.name (current behavior). "
        "Set via MEMGENTIC_ENABLE_GIT_PROJECT_RESOLUTION."
    ),
)
```

These flow from env vars automatically via the `MEMGENTIC_` prefix. Pass them to `hybrid_search` from the MCP and CLI call sites via `settings.current_project_boost` etc.

---

### `projects.toml.example` (new — repo root)

```toml
# ~/.memgentic/projects.toml — Project key aliases for Memgentic.
#
# Copy this file to ~/.memgentic/projects.toml and edit it.
# Run `memgentic projects repair` after any edit to recompute existing rows.

[settings]
# Collapse multiple clones of the same git repo into one project key.
# Requires git remote origin to be identical across clones.
# Default: false
use_remote_url_collapse = false

# --- Alias examples ---

# Merge WSL path variant with Windows-side clone:
# [[alias]]
# from = ["mnt-c-users-harit-desktop-inproma"]
# to = "inproma"

# Merge fragmented project keys for the same repo:
# [[alias]]
# from = ["allweb-projects-allvolution2", "allweb-projects"]
# to = "allweb-projects"

# Garbage sink: collapse transient directories to unknown:
[[alias]]
from = ["new-folder", "temp", "untitled", "desktop", "new-project", "downloads"]
to = ""
```

---

## Data Flow

### Ingestion (daemon / import-existing)

```
file_path / event payload
    → adapter.get_project(file_path)
        → derive_project_full(cwd=..., use_git=settings.enable_git_project_resolution,
                              alias_map=load_project_aliases())
            1. MEMGENTIC_CURRENT_PROJECT env (only if adapter exposes cwd)
            2. git toplevel name (via asyncio.to_thread, lru_cache, UNC guard)
            3. bare cwd.name
            4. slug decode (Claude Code fallback)
            5. apply alias_map
    → Memory.project = result
    → MetadataStore.save_memory()
```

### MCP `memgentic_recall`

```
user query
    → RecallInput validated
    → session_config built from include_projects / exclude_projects / sources
    → current_project resolved:
          MEMGENTIC_CURRENT_PROJECT → git_toplevel(os.getcwd()) → cwd.name → alias
    → hybrid_search(query, ..., current_project=current_project,
                    project_boost=settings.current_project_boost, ...)
        → RRF fusion (semantic + keyword + graph)
        → importance * decay per result
        → score_raw snapshot
        → boost current-project rows by project_boost
        → rank by score (boosted)
        → each result: {id, score, score_raw, is_current_project, ...}
    → surface partition:
          primary = is_current_project or current_project is None
          related = not is_current_project AND score_raw >= 0.6 * top_raw
    → render primary results
    → if related: render "--- Related from other projects ---"
    → _record_loaded_payloads()
```

### REST `GET /api/v1/memories?project=foo&project=bar`

```
FastAPI: project: list[str] | None = Query(default=None)
→ config.include_projects = [p.strip().lower() for p in project]
→ MetadataStore.get_memories_by_filter(session_config=config, ...)
  (existing WHERE clause: platform IN (...) AND project IN (...))
→ MemoryListResponse
```

No boost, no partition — REST list endpoint is for browsing, not recall.

### `memgentic projects repair`

```
load_project_aliases() → alias_map
MetadataStore: SELECT id, project FROM memories WHERE status = 'active'
for each row:
    resolved = resolve_project(row.project, alias_map)
    if resolved != row.project:
        stage UPDATE memories SET project = resolved WHERE id = row.id
executemany(staged_updates)
invalidate_alias_cache()
```

### `memgentic projects backfill-jsonl`

```
MetadataStore: SELECT id, file_path FROM memories WHERE project = ''
For each row's file_path:
    detect adapter (platform from memories row, or infer from file_path pattern)
    if codex_cli:
        open file_path, scan for first {"type": "session_meta"} event
        extract payload.cwd → derive_project_full(cwd=cwd, ...)
    if gemini_cli:
        open file_path as JSON → top-level "cwd" field
        derive_project_full(cwd=cwd, ...)
    if derived non-empty: stage UPDATE
executemany(staged_updates)
log: scanned N, updated M, still_empty K
```

---

## Implementation Sequence

The five slices are ordered by risk (lowest-risk first) and dependency (upstream before downstream).

### Slice 1 — Alias system + repair CLI (no ranking changes)

Touches: `processing/project.py`, `cli.py`, `projects.toml.example`

Tasks:
- Add `load_project_aliases()`, `resolve_project()`, `invalidate_alias_cache()`, `_resolve_transitive()` to `project.py`
- Wire `load_project_aliases()` into existing `derive_project()` as optional `alias_map` param
- Add `projects` CLI group with `list`, `alias`, `merge`, `repair` subcommands
- Add `projects.toml.example` to repo root
- Unit tests: transitive resolution, cycle detection, empty-string sink, first-match-wins precedence

Shippable independently. Zero ranking change. Zero migration needed.

### Slice 2 — Git toplevel resolution (opt-in, ingestion-only)

Touches: `processing/project.py`, `config.py`, all adapters that override `get_project()`

Tasks:
- Add `_git_toplevel_sync()`, `_git_remote_url_sync()` (lru_cache, UNC guard) to `project.py`
- Add `git_toplevel()`, `git_remote_url()` async wrappers
- Add `derive_project_full()` incorporating the full chain
- Add `enable_git_project_resolution: bool = False` to `MemgenticSettings`
- Update adapter `get_project()` overrides (Claude Code, Codex, Gemini, Aider) to call `derive_project_full()` when the new setting is enabled
- Unit tests: UNC path returns None, clean cwd with git returns toplevel name, git failure falls back to cwd.name

Can be developed in parallel with Slice 1 since both touch `project.py` — coordinate via branch or sequential ordering.

### Slice 3 — Migration 11 + JSONL backfill CLI

Touches: `migrations.py`, `cli.py` (extends `projects` group)

Tasks:
- Add Migration 11 (partial index `idx_memories_project_empty`) to `MIGRATIONS` list
- Add `projects backfill-jsonl` command to CLI
- Integration test: create mock Codex JSONL with `session_meta.cwd`, run backfill, verify `project` column updated
- Run on production DB, report: scanned / updated / still_empty counts

Blocked on: Slice 1 (needs `derive_project_full` from Slice 2, or `derive_project` from Slice 1 if git is not enabled for backfill). Can ship Slice 1 first, then 3 references it.

### Slice 4 — Multi-value REST + dashboard multi-select

Touches: `memories.py` (API route), `api.ts`, `hooks/use-memories.ts`, `collections-sidebar.tsx`, `page.tsx`

Tasks:
- Change `project: str | None` to `project: list[str] | None` in `list_memories` endpoint
- Update `api.ts` `listMemories` signature and `qs.append` loop
- Update `useMemories` hook in `hooks/use-memories.ts` to accept `projects?: string[]`
- Update `CollectionsSidebar` interface: `activeProjects: string[]`, `onProjectsChange`
- Remove mutex: project click no longer clears source, source click no longer clears projects
- Update `page.tsx`: `projectFilters` state, pass to sidebar and API call
- Test: multi-project filter returns union of memories from all selected projects

Blocked on nothing (REST change is additive — a single string is still a one-element list in FastAPI).

### Slice 5 — Current-project boost + cross-project section

Touches: `search.py`, `config.py`, `server.py`, `cli.py` (`search` command), REST search endpoint

Tasks:
- Add `current_project`, `project_boost`, `cross_project_threshold`, `cross_project_max` params to `hybrid_search`
- Add score_raw tracking, boost pass, `is_current_project` field to result dicts
- Add three `MemgenticSettings` fields
- MCP `memgentic_recall` handler: resolve current project, pass to search, render partition
- CLI `memgentic search` command: resolve current project (same chain), pass to search
- REST `/memories/search` endpoint: optional `current_project` query param (not sent by dashboard)
- Verify: boost does not affect `min_score` filter (filter runs after boost, against boosted score)
- A/B test: run existing LongMemEval harness with boost=1.0 (control) vs boost=1.5 (treatment)

Blocked on: Slice 2 (needs `resolve_current_project` from `project.py`).

---

## Risk Register

### `lru_cache` thread safety in concurrent ingestion

`functools.lru_cache` in CPython is protected by a C-level lock per-cache. Concurrent asyncio tasks calling `asyncio.to_thread(_git_toplevel_sync, cwd)` are safe — multiple threads may call the underlying `subprocess.run` for distinct `cwd` values simultaneously, and the cache will deduplicate correctly. The only subtle case: two threads racing to populate the same `cwd` key both call `subprocess.run` (the cache miss is not serialized before population). This is correct behavior (idempotent), just means one extra git call per novel `cwd` under concurrency. Acceptable.

### Vec payload `project` staleness after alias repair

`hybrid_search` already overlays `memory.project` from the metadata store onto the payload at line 278 (`payloads[mid]["project"] = memory.project or ""`). After `memgentic projects repair` updates `memories.project`, the sqlite-vec/Qdrant payload column still holds the old key. This is correct by design: the metadata store is authoritative; the vec payload is informational for display only; the overlay-at-read pattern means users see correct project labels without a re-embed. Document this as a non-goal for repair. The only scenario where stale vec payload matters is direct Qdrant API access bypassing the hybrid_search overlay — that path is out of scope.

### Migration 11 on fresh installs

Migration 11 (partial index) runs on fresh installs where `idx_memories_project_empty` doesn't yet exist. `CREATE INDEX IF NOT EXISTS` is idempotent. No issue.

### `auto` sentinel with new boost semantics

With boost enabled, `project="auto"` (strict filter) is now more restrictive than passing no project (boost without filter). Users who previously used `auto` to scope a query to their current project will now get current-project memories at top of the unboosted list anyway — `auto` is still correct when they want only current-project results. Do not change `auto`'s behavior. Update the `RecallInput.project` field description to note the distinction: "`auto` = strict filter to current project only. Omit to get cross-project suggestions ranked by current-project boost."

### Boost interaction with `min_score`

The `min_score` filter in `hybrid_search` (line 289) currently runs after importance×decay. With boost, a cross-project memory with `score_raw` just below `min_score` passes the threshold after boost. This is unlikely to be a problem in practice (boost only raises current-project scores, never cross-project ones), but verify the filter runs against `scores[mid]` (boosted) not `score_raw`. The current behavior is correct if boost is applied before the `min_score` check.

### Dashboard multi-select scroll performance

The Projects sidebar currently renders all projects including "(unknown)". On the production DB that is 35 distinct projects + 1 unknown = 36 items. That's fine. No virtualization needed unless the list grows past ~200 items.

### TOML parse errors on startup

If `~/.memgentic/projects.toml` is malformed, `load_project_aliases()` must log a warning and return an empty map (no aliases applied), not crash ingestion or the MCP server. Use `tomllib` (stdlib since Python 3.11) with a try/except.

---

## Non-Goals (Explicit)

- No "current project" banner in the dashboard (Q-B decision, locked).
- No `~/.memgentic/current.json` or equivalent current-project signal file.
- No automatic re-embed of vec payloads after alias repair.
- No remote URL collapse enabled by default.
- No changes to `memgentic_projects` MCP tool signature (already correct).
- No `(unknown)` cleanup in the dashboard — the sink alias in `projects.toml` handles garbage project names; the UI can keep rendering whatever's in the DB.
- No JSONL read inside any migration function.

---

## Source Files (Authoritative References)

- `memgentic/memgentic/processing/project.py`
- `memgentic/memgentic/storage/migrations.py`
- `memgentic/memgentic/graph/search.py`
- `memgentic/memgentic/mcp/server.py`
- `memgentic/memgentic/config.py`
- `memgentic/memgentic/cli.py`
- `memgentic/memgentic/adapters/codex_cli.py`
- `memgentic/memgentic/adapters/base.py`
- `memgentic-api/memgentic_api/routes/memories.py`
- `dashboard/src/lib/api.ts`
- `dashboard/src/components/collections/collections-sidebar.tsx`
- `dashboard/src/app/page.tsx`
- `memgentic/memgentic/models.py`
