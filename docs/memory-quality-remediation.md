# Memgentic memory-quality remediation — design + plan

> Authored 2026-06-28 after a 6-area forensic audit of the live store + code. Goal: make recall actually useful (signal over noise), add **per-project / per-repository scoping**, and upgrade embedding + reranker (quantized, light). Branch: `feat/memory-quality-remediation`.

## 1. Diagnosis (evidence base)

Live store at audit: **9,198 memories**, **5,554 vectors**, 90.8% claude_code. Recall returns cosine 0.2–0.5 with heavy noise. Six converging root causes:

| # | Root cause | Evidence | Where |
|---|---|---|---|
| RC1 | **~40% of memories have NO vector** → invisible to semantic recall; worst, it's the *curated* April-2026 `enriched` rows (importance 1.0). Backend switched Qdrant→sqlite-vec with no migration. The legacy-data warning silences itself when the DB > 100KB. | 3,643 missing (39.6%); 3,254 are April enriched | `storage/vectors.py:433`; `~/.memgentic/data/qdrant/` orphan |
| RC2 | **Auto-daemon ingests Claude Code internal task files** (daily-log summarizer, compaction compressor, suggestion-mode, adversarial-verifier, skill loaders) as "memories". **97.1% of all rows start with `Human: `** (raw turn text, not distilled facts). | summarizer-prompt ×222, compression ×141, continuation ×64; noise ≈ 43% of store | adapter only skips `role=system/file-history-snapshot` (`adapters/claude_code.py:141`); `is_valuable` computed but unused (`pipeline.py:349-385`); `is_noise()` misses instruction text (`heuristics.py:58`) |
| RC3 | **Recall has no relevance floor, no content-type weighting, and the ranking boosts are dead code.** `raw_exchange` is searched by default with importance 1.0 (same as a `decision`). `apply_feature_boosts` (proper-noun/phrase/temporal) and the `LlamaCppReranker` are implemented but **never called**. SessionStart briefing = pure recency → injects the meta-prompt noise into every new session. | min_score default 0.0; reranker/feature-boost orphaned | `graph/search.py:46`, `feature_boost.py`, `retrieval/reranker.py`, `context_generator.generate_briefing`, `pipeline.py:273` |
| RC4 | **No self-cleaning.** `ingest_single` (every `memgentic_remember`) has NO write-time dedup. Dream is additive (insights add rows; merge/supersede are soft-deletes only). Retention decays a float but no GC ever deletes. | 853 exact dups (9.3%); store only grows | `pipeline.py:578` (no dedup), `dream.py:915`, no GC anywhere |
| RC5 | **Weak embedding model.** `qwen3-embedding:0.6b` @ 768 dims (non-standard MRL slice). Small model → flat similarities (0.3–0.55 on-topic is "normal" for it). | observed 0.49 ceiling | `config.py:68-75` |
| RC6 | **Mis-classification + encoding.** No "meta-prompt" category; over-broad heuristic keywords (`"from "`, `"let "`, `"return "`) fire on plain English; 16% mojibake (broken Greek from non-UTF8 sources); one 765KB blob (a Gemini file-read dump). | — | `intelligence.py:103-129`, `heuristics.py:117-141` |

## 2. Design decisions

### 2a. Per-project / per-repository scoping (new capability)
Infra exists partially: a `project` column on `memories`, `processing/project.py` (`project_from_cwd`/`derive_project`), CLI `--project auto`, capture stamps `project` (`pipeline.py:267/285`). **Gaps:** the MCP `memgentic_recall` does NOT default to the current project, and there is no config knob. The MCP server is a per-Claude-Code-session stdio subprocess, so its cwd ≈ the workspace — but that is not guaranteed.

**Decision:**
- Add config `recall_scope: "project" | "global"` (default **`project`**) + `recall_scope_strict: bool` (default false → project-first with global fallback when a project yields nothing; strict = project-only). The user can set these per install or via env `MEMGENTIC_RECALL_SCOPE`.
- Resolve "current project" for the MCP server in priority order: (1) an explicit `project` arg, (2) `MEMGENTIC_PROJECT` env (set by the SessionStart hook from the workspace), (3) `project_from_cwd(subprocess cwd)`. The SessionStart hook calls `memgentic_configure_session(project=…)` and/or exports `MEMGENTIC_PROJECT` so recall is reliably scoped to the repo the user is in.
- Keep an easy global escape: `project="*"` / `recall(..., scope="global")`.
- Ensure EVERY adapter stamps `project` on capture (so cross-tool memories are scoped too).

### 2b. Models (configurable, quantized, light-by-default)
Research (mid-2026): there is **no Qwen3-Embedding-1.7B**; the family is 0.6B/4B/8B. Ollama cannot serve rerankers (issue #16076) → reranker runs on `llama-server`. Many community Qwen3-Reranker GGUFs are broken (missing `cls.output.weight`) → use the verified **Voodisss** repos.

**Decision (all configurable; these are the defaults we ship):**
- **Embedding:** make model+dims fully config-driven. Recommend `qwen3-embedding:4b` MRL-truncated to **1024 dims** (q4_K_M, ~2.5GB, +~5 MTEB vs 0.6B). Lighter fallback `qwen3-embedding:0.6b` (639MB, current). Switching requires a **full re-embed** (different space). Query prefix `Instruct: Retrieve relevant memories and past decisions\nQuery: …`; documents un-prefixed (already correct in `embedder.py` — verify).
- **Reranker:** add config + wire the existing `LlamaCppReranker`. Default **Qwen3-Reranker-0.6B Q4_K_M** (Voodisss, ~396MB — light) served by `llama-server --reranking --pooling rank --embedding` at `/v1/rerank`; **4B opt-in** for max quality. Reranker is OFF unless `enable_reranker=true` + a reachable server, so installs without llama-server are unaffected.

## 3. Workstreams (each = its own commit(s), with tests; `make test` green before merge)

**W1 — Capture hygiene (stop noise at the source).** Exclude internal/temp/observer dirs (`*-Local-Temp*`, `*observer*`) + `isSidechain` turns in `ClaudeCodeAdapter`; add meta-prompt patterns to `is_noise()` (e.g. `^(Human: )?You are (a|an|the|summarizing|classifying)\b`, `^Apply (maximum )?non-destructive compression`, `^(Rules?|Instructions?|Constraints?):`); **wire `distillation.is_valuable` as a write gate** in `pipeline.py`; tighten over-broad `code_snippet`/`decision` heuristic keywords; cap oversized blobs (skip or truncate > 64KB with a marker). Files: `adapters/claude_code.py`, `adapters/base.py`, `processing/heuristics.py`, `processing/pipeline.py`, `processing/intelligence.py`.

**W2 — Recall quality.** Add a relevance floor (`min_score` default > 0 for hybrid; cosine floor ~0.2 for basic); default-exclude `raw_exchange` from recall unless explicitly requested; set per-content-type `importance_score` at ingestion (decision/fact/preference/learning 1.0, code/action 0.9, conversation_summary 0.6, raw_exchange 0.4); filter the SessionStart briefing to curated types; **wire `apply_feature_boosts`** into hybrid search; fix the `_warn_if_legacy_qdrant_data` suppression (RC1 visibility). Files: `mcp/server.py`, `graph/search.py`, `processing/search_basic.py`, `processing/context_generator.py`, `hooks/session_start.py`, `processing/pipeline.py`, `storage/vectors.py`.

**W3 — Per-project / per-repo scoping** (per §2a). Files: `config.py`, `mcp/server.py`, `processing/project.py`, `hooks/session_start.py`, `processing/context_generator.py`, `processing/pipeline.py`, adapters' `get_project`.

**W4 — Self-cleaning + retention.** Write-time dedup in `ingest_single` (reuse the `ingest_conversation` dedup, gated by `enable_write_time_dedup`); make dream reductive (archive consumed source IDs after `INSERT_INSIGHT`); add retention config (`hard_delete_archived_after_days`) + a GC sweep (daemon loop or CLI); add a `memgentic clean` bulk-archive command driving `dedupe_check`→`forget`, **never touching pinned or `capture_method=mcp_tool`**. Files: `processing/pipeline.py`, `processing/dream.py`, `cli.py`, `config.py`, `storage/metadata.py`, daemon.

**W5 — Models (configurable embedding + reranker).** Make embedding model/dims config-driven with documented defaults; add reranker config (`enable_reranker`, `reranker_url`/model, `reranker_top_k`) and **wire `LlamaCppReranker`** into hybrid + basic search after the top-N candidates; verify the Qwen3 query/document prefixes. Files: `config.py`, `retrieval/reranker.py`, `graph/search.py`, `processing/search_basic.py`, `mcp/server.py`, `embedder.py`.

**W6 — Runtime ops (after W1–W5 land + verified).** (a) **Vector migration** Qdrant→sqlite-vec to restore the 3,643 orphans; (b) **one-time cleanup**: archive the dup/meta-prompt clusters (preserve pinned + mcp_tool + curated, soft-delete only); (c) optional **embedding upgrade**: pull `qwen3-embedding:4b` + re-embed; (d) optional **reranker**: pull the Voodisss GGUF + run `llama-server`. These mutate the live store/models, so they run last, each reversible-where-possible and reported.

## 4. Acceptance
- `make test` green; new tests cover each W1–W5 behavior change.
- Recall on a known query returns curated `decision`/`fact` above noise, with a relevance floor, and (with reranker on) sharper ordering.
- A new project's recall is scoped to that project by default; global is one flag away.
- Store stops growing monotonically (write-time dedup + reductive dream + GC); the orphaned vectors are restored.
