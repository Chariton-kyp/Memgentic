# Plan: Auto-Dream — LLM-driven memory consolidation

> Canonical plan, committed alongside other docs. Approved 2026-05-07.

---

## Context

Anthropic shipped **Dreams** (Research Preview, 2026-04-21) for Claude Managed Agents — an asynchronous job that reads a memory store + recent sessions and produces a *new, separate* memory store with duplicates merged, contradictions resolved, stale entries removed, and recurring patterns surfaced as new insights. The community open-sourced a 4-phase replica (`grandamenium/dream-skill`) for Claude Code.

Memgentic already has deterministic housekeeping in [memgentic/memgentic/processing/consolidation.py](../../memgentic/memgentic/processing/consolidation.py): exponential importance decay + cosine-based dedup. **What's missing** is the LLM-driven semantic layer that:
- normalizes relative dates ("yesterday we decided X" → "On 2026-04-15 we decided X"),
- *resolves* contradictions (the existing code only flags them),
- removes references to deleted files / renamed entities,
- extracts recurring patterns and user preferences as new high-signal "insight" memories.

The existing infra (LangChain LLM client, LangGraph state machines in [intelligence.py](../../memgentic/memgentic/processing/intelligence.py), `get_recent_session_handoffs` with project filter, structured Pydantic outputs) covers ~80 % of what we need. This plan adds the orchestration layer on top.

**Outcome:** A new `memgentic dream` CLI command + `memgentic_dream_*` MCP tools that:
1. Run an LLM pipeline over recent sessions for a given project,
2. Produce a list of *proposed* patches (merge / supersede / archive / normalize_date / insert_insight) without mutating live memories,
3. Let the user review and explicitly `apply` (or reject) each batch.

This matches Anthropic's "input never modified" semantics and the personal-tool constraint (small, on-demand, no product-feature scope creep).

---

## Goals (Phase 0 — what we ship first)

- Manual `memgentic dream run [--project NAME]` CLI command
- Manual MCP tools: `memgentic_dream_run`, `memgentic_dream_status`, `memgentic_dream_apply`, `memgentic_dream_list`
- Project-scoped by default (defaults to `derive_project(cwd=os.getcwd())`)
- Branch-then-swap semantics: dream output is a list of *proposed patches* in dedicated tables; live memories untouched until `apply`
- Reuses existing `LLMClient.generate_structured()` + LangGraph patterns from `intelligence.py`
- Tests covering: pipeline phases (mocked LLM), patch persistence, apply/reject idempotency, project scoping

## Non-goals (defer until proven useful)

- Daemon scheduler / 24h auto-trigger (Stop hook)
- Dashboard UI for dream review (CLI diff viewer is enough for v0)
- REST `/dreams` endpoints (defer until dashboard need)
- Cross-project dreams (force project scope to keep contexts clean)

## Model routing (per phase) — full matrix

Updated 2026-05-09 after latest evaluator pass. **See [`docs/AUTO-DREAM-MODELS.md`](../AUTO-DREAM-MODELS.md) for the canonical reference.** This section is the design rationale; that document is the user-facing config guide.

Routing is by model-name **prefix match (case-insensitive)** — same logic in CLI, MCP, REST, and dashboard:

| Prefix | Provider | Phase 2 example | Phase 3 example |
|---|---|---|---|
| `claude-*` / `anthropic/...` | Anthropic API | `claude-haiku-4-5` | `claude-sonnet-4-6` |
| `gemini-*` / `models/gemini-*` | Google API | `gemini-3.1-flash-lite` | `gemini-3.1-pro` |
| `gpt-*` / `o1-*` / `openai/...` | OpenAI-compat (LM Studio / vLLM / llama.cpp) | `gpt-4o-mini` | `gpt-4o` |
| anything else | Ollama tag | `gemma4:e4b` | `qwen3.6:35b-a3b` |
| empty string | default `LLMClient` chain | (auto) | (auto) |

**Each phase has its own model.** You can mix providers freely (e.g. cheap Haiku for Phase 2, local Qwen 3.6 for Phase 3). Per-phase override surfaces:

- `.env`: `MEMGENTIC_DREAM_SIGNAL_MODEL` + `MEMGENTIC_DREAM_CONSOLIDATE_MODEL`
- CLI: `memgentic dream run --signal-model X --consolidate-model Y`
- MCP: `memgentic_dream_run` params `signal_model` / `consolidate_model`
- REST: `POST /api/v1/dreams` body `signal_model` / `consolidate_model`
- Dashboard: `/dreams` page → Advanced section → per-phase fields with provider chips
- Wizard: `memgentic init` / `memgentic setup` → Step 3b preset bundles
- Helper: `memgentic dream models` shows current config + available providers + installed Ollama tags

### State of the art (May 2026, evaluator-verified)

| Tier | Phase 2 | Phase 3 | Cost | Wall clock | When |
|---|---|---|---|---|---|
| Cheapest cloud | `claude-haiku-4-5` | `claude-haiku-4-5` | ~$0.10/run | 30-90 s | Daily iteration |
| Best balanced | `claude-haiku-4-5` | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S` | ~$0.005/run | 6-15 min | Weekly batch |
| Fully local | `gemma4:e4b` | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S` | $0 | 8-15 min | No cloud allowed |
| Portable local | `gemma4:e4b` | `gemma4:26b-a4b` | $0 | 20-60 min on 16 GB | Other users (low-spec) |
| Quality cloud | `claude-haiku-4-5` | `claude-sonnet-4-6` | ~$0.90/run | 5-10 min | Production / verified store |

**Why MoE matters for portability**: the user wants this to also work on 16 GB machines. MoE models like `qwen3.6:35b-a3b` and `gemma4:26b-a4b` activate only ~3-4 B params per token, so the access pattern is sparse and cacheable via mmap. Dense 27B on 16 GB would thrash the page cache. **MoE A3B-class is the only realistic large-model path on low-spec.**

### Implementation

Config keys in [`memgentic/memgentic/config.py`](../../memgentic/memgentic/config.py):

- `dream_consolidate_model: str = "claude-sonnet-4-6"`
- `dream_signal_model: str = "claude-haiku-4-5"`
- `anthropic_api_key: str | None = None`
- `dream_default_session_limit: int = 10`

Routing factories in [`memgentic/memgentic/processing/dream.py`](../../memgentic/memgentic/processing/dream.py):

- `_detect_provider(model)` — prefix → provider key dispatcher
- `_build_anthropic_client` / `_build_gemini_client` / `_build_openai_compat_client` / `_build_ollama_client`
- `_build_phase_llm(settings, raw_model, phase_label)` — top-level dispatcher
- `create_signal_llm` / `create_consolidate_llm` — read settings, fall back to default LLMClient on builder failure

Per-run overrides flow `run_dream(signal_model=..., consolidate_model=...)` → `_build_phase_llm` directly, bypassing the settings.

---

## Architecture: 4-phase LangGraph pipeline

Mirrors `dream-skill`'s 4-phase structure, adapted to Memgentic's existing primitives.

```
                   ┌─────────────────────────────────────────────┐
                   │  memgentic dream run --project memgentic    │
                   └──────────────────────┬──────────────────────┘
                                          │
            ┌─────────────────────────────▼─────────────────────────────┐
            │ Phase 1: ORIENT                                           │
            │  - Snapshot active memories for project (filter by        │
            │    SessionConfig.include_projects=[project_key])          │
            │  - Pull persona card (T0) + topic clusters                │
            │  - Build inventory: counts by source, by content_type     │
            │  Reuses: metadata_store.get_memories_by_filter(),         │
            │          get_recent_session_handoffs()                    │
            └──────────────────────┬────────────────────────────────────┘
                                   │
            ┌──────────────────────▼────────────────────────────────────┐
            │ Phase 2: GATHER SIGNAL  (LLM)                             │
            │  - For last N sessions (default 10, max 100), extract:    │
            │    * user corrections                                     │
            │    * preference changes                                   │
            │    * recurring patterns                                   │
            │    * decisions with timestamps                            │
            │  - Output: SignalReport (Pydantic)                        │
            │  Reuses: LLMClient.generate_structured()                  │
            └──────────────────────┬────────────────────────────────────┘
                                   │
            ┌──────────────────────▼────────────────────────────────────┐
            │ Phase 3: CONSOLIDATE  (LLM)                               │
            │  - Cluster active memories by topic                       │
            │  - For each cluster, LLM proposes Patches:                │
            │    * merge   (kill duplicate, keep canonical)             │
            │    * supersede (newer fact replaces older)                │
            │    * archive_stale (no longer relevant)                   │
            │    * normalize_date (relative → absolute)                 │
            │    * insert_insight (new memory derived from patterns)    │
            │  - Output: PatchSet (Pydantic, list of Patch ops)         │
            │  Reuses: existing cosine-similarity dedup signals as      │
            │           input HINTS to the LLM (not as ground truth)    │
            └──────────────────────┬────────────────────────────────────┘
                                   │
            ┌──────────────────────▼────────────────────────────────────┐
            │ Phase 4: PRUNE & INDEX                                    │
            │  - Persist DreamRun (status=completed) + Patches          │
            │    (status=proposed) to SQLite                            │
            │  - DOES NOT mutate live memories                          │
            │  - Print human-readable summary to CLI                    │
            └───────────────────────────────────────────────────────────┘

  → User reviews:  memgentic dream show <dream_id>
  → User applies:  memgentic dream apply <dream_id>     [executes patches deterministically]
  → User rejects:  memgentic dream reject <dream_id>    [marks patches as rejected, no mutation]
```

---

## Data model

Two new tables. **No changes to existing `memories` schema** (keeps the live data path untouched).

### Migration 10 — `dream_runs` + `dream_patches`

```sql
CREATE TABLE IF NOT EXISTS dream_runs (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN
        ('pending','running','completed','failed','canceled')),
    model TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    input_session_ids TEXT NOT NULL DEFAULT '[]',
    input_memory_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    usage_input_tokens INTEGER NOT NULL DEFAULT 0,
    usage_output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    ended_at TEXT,
    applied_at TEXT,
    user_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS dream_patches (
    id TEXT PRIMARY KEY,
    dream_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN
        ('merge','supersede','archive_stale',
         'normalize_date','insert_insight','update_field')),
    target_memory_ids TEXT NOT NULL DEFAULT '[]',
    new_content TEXT,
    new_metadata TEXT,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN
        ('proposed','applied','rejected','superseded_by_apply')),
    created_at TEXT NOT NULL,
    applied_at TEXT,
    FOREIGN KEY (dream_id) REFERENCES dream_runs(id)
);
```

Indexes: `dream_runs(project)`, `dream_runs(status)`, `dream_runs(created_at)`, `dream_patches(dream_id)`, `dream_patches(status)`.

No backfill needed (new tables, empty on creation).

---

## Apply policy

| Action | Class | Effect | Auto-apply? |
|---|---|---|---|
| `merge` | destructive | mark all-but-canonical as `MemoryStatus.SUPERSEDED`, set `keep.supersedes` | explicit only |
| `supersede` | destructive | same as merge but with explicit ordering | explicit only |
| `archive_stale` | destructive | set `MemoryStatus.ARCHIVED` | explicit only |
| `normalize_date` | non-destructive | write `valid_from` triple to Chronograph (never rewrites memory.content) | `--auto-apply` allowed |
| `insert_insight` | non-destructive | create new memory with `source.platform="dream"`, `capture_method="dream_run"`, `derived_from=[ids]` | `--auto-apply` allowed |
| `update_field` | non-destructive | patch topics/entities only (never raw content) | `--auto-apply` allowed |

`apply_dream(dream_id, *, only_non_destructive=False)`. When `only_non_destructive=True` (the `--auto-apply` flag), destructive patches remain `PROPOSED` for later explicit `dream apply <id>`.

---

## Critical files (touch list)

| Surface | Path | Change |
|---|---|---|
| Config | `memgentic/memgentic/config.py` | + `dream_consolidate_model`, `dream_signal_model` |
| DB | `memgentic/memgentic/storage/migrations.py` | append migration 10 |
| Storage | `memgentic/memgentic/storage/metadata.py` | + 8 CRUD methods |
| Models | `memgentic/memgentic/models.py` | + DreamRun, DreamPatch, 3 enums |
| Core | `memgentic/memgentic/processing/dream.py` | NEW — LangGraph pipeline |
| Core | `memgentic/memgentic/processing/dream_prompts.py` | NEW — prompt templates |
| CLI | `memgentic/memgentic/cli.py` | + `dream` group with 5 subcommands |
| MCP | `memgentic/memgentic/mcp/server.py` | + 4 tools |
| Docs | `docs/MCP-TOOLS.md` | regenerated by `scripts/generate_mcp_docs.py` |
| Tests | `memgentic/tests/test_dream_pipeline.py` | NEW |
| Tests | `memgentic/tests/test_dream_apply.py` | NEW |
| Tests | `memgentic/tests/test_dream_integration.py` | NEW |
| Tests | `memgentic/tests/test_cli.py` | + dream cases |
| Tests | `memgentic/tests/test_mcp_server.py` | + dream cases |

**Files reused, not modified:**
- `memgentic/memgentic/processing/llm.py` — `LLMClient.generate_structured()` directly callable
- `memgentic/memgentic/processing/intelligence.py` — pattern reference only
- `memgentic/memgentic/processing/consolidation.py` — runs unchanged; dream is *additive*
- `memgentic/memgentic/processing/project.py` — `derive_project()` for cwd-based default
- `metadata_store.get_recent_session_handoffs()` — already supports project filter via `SessionConfig`

---

## Test plan

### `tests/test_dream_pipeline.py` (NEW)

- `test_orient_node_inventories_active_memories`
- `test_gather_signal_node_with_mocked_llm`
- `test_consolidate_node_proposes_merge_for_duplicates`
- `test_index_node_persists_dream_run_and_patches`
- `test_run_dream_full_pipeline_e2e_with_mocked_llm`
- `test_run_dream_falls_back_when_llm_unavailable`

### `tests/test_dream_apply.py` (NEW)

- `test_apply_merge_marks_duplicates_superseded`
- `test_apply_normalize_date_writes_chronograph_triple_only`
- `test_apply_insert_insight_creates_new_memory_with_dream_source`
- `test_apply_idempotent_when_called_twice`
- `test_reject_marks_all_patches_rejected`
- `test_apply_after_reject_is_400`
- `test_auto_apply_only_runs_non_destructive_patches`
- `test_auto_apply_followed_by_explicit_apply_completes_destructive`
- `test_phase3_falls_back_to_default_llm_when_anthropic_key_missing`

### `tests/test_dream_integration.py` (NEW)

End-to-end with a real SQLite fixture + mocked LLM client.

### Extends `tests/test_cli.py` and `tests/test_mcp_server.py`

CLI + MCP tool wiring tests.

---

## Verification (end-to-end smoke)

```powershell
# 1. Migration check
memgentic doctor

# 2. Run on the active project
memgentic dream run --project memgentic-public-export --limit-sessions 5

# 3. Inspect output
memgentic dream list --project memgentic-public-export
memgentic dream show <dream_id>

# 4. Apply (or reject)
memgentic dream apply <dream_id> --yes

# 5. Verify via MCP: call memgentic_recall("project pivot")
```

Cross-check input is untouched until apply (snapshot `COUNT(*) FROM memories WHERE status='active'` before/after run-without-apply → identical).

---

## Open questions / future work (post-Phase 0)

1. **Auto-trigger via daemon scheduler** — tick in `daemon/watcher.py` runs a dream when ≥24h elapsed AND ≥N new captures since last dream. Off by default, opt-in via `MEMGENTIC_AUTO_DREAM=1`.
2. **Dashboard "Dreams" tab** — proposed-patch diff viewer with checkboxes per patch.
3. **Cross-project dream** — only after we can guarantee the LLM doesn't bleed context across projects.
4. **Stop-hook integration with Claude Code** — `~/.claude/hooks/SessionEnd` calls `memgentic dream run` if 24h elapsed.
5. **Patch evidence linking** — store the (chunk_id, line_range) tuple that justified each patch.
