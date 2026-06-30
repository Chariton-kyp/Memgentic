# Distillation Recall Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop discarding the atomic facts the ingest pipeline already distills — persist them as the embedded + displayed recall surface (verbatim retained in-row as the FTS5/audit backstop) — to cut recall noise without losing signal.

**Architecture:** Memgentic's `enriched` ingest already runs an LLM `distill_node` that emits 1–5 self-contained facts per chunk, but the pipeline embeds the verbatim `Human:/Assistant:` turn and uses the distillation only for the value-gate. We persist the distilled text on a new nullable `Memory.distilled` column, embed `distilled or content`, keep `content` verbatim (FTS5 + audit source-of-truth), and prefer the distilled snippet on display — all behind one off-by-default flag, validated by the eval harness before any default flip. Aggressive cross-session MERGE/SUPERSEDE stays in the offline DREAM pipeline.

**Tech Stack:** Python 3.12, Pydantic v2 (`models.py`), aiosqlite + SQLite FTS5 (`storage/metadata.py`), LangGraph intelligence pipeline (`processing/intelligence.py`), `bge-m3` @1024 in Qdrant/sqlite-vec, optional Qwen3-Reranker. Tests: pytest (`memgentic/tests/`), `uv run --no-sync pytest ...`.

## Source

Decision from the 2026-06-29 expert panel (`memory/` + workflow `memory-ingestion-cleaning-panel`). Recommended approach: *"Persist-the-distillation-you-already-compute: single distilled recall surface first, verbatim retained as FTS5/expand backstop; additive fact-rows and async timing deferred behind the eval harness."*

## Global Constraints

- **Local-first** — must work offline; the local LLM is a small Ollama model (`gemma4:e4b`) or cloud Gemini Flash Lite. No new synchronous LLM call (Phase 1 reuses the distillation call that already runs).
- **Never destroy `content`** — `distilled` is a *separate* nullable column; verbatim `content` stays the immutable source-of-truth for re-embed, audit, Chronograph triples, provenance.
- **Re-embed must NOT recompute distillation** — `memgentic re-embed` reads the *persisted* `distilled` text (zero LLM calls) or vectors become non-deterministic.
- **No 4th capture profile** — gate behind one setting under the existing `raw`/`enriched`/`dual` config surface.
- **Default OFF until measured** — do not flip the embedded surface until the R@5/MRR harness confirms `distilled`+FTS5 beats verbatim on the maintainer's own data.
- **Back-compat** — existing/raw/dual rows have `distilled = NULL` and must behave exactly as today (`distilled or content`).
- Tests run with services already up (Ollama `bge-m3`, Qdrant, reranker) but unit tests mock the LLM/embedder via `httpx.MockTransport` / fakes — never hit the network.

---

## Task ordering (do them in this order — hard dependencies)

| # | Phase | Task | Depends on |
|---|---|---|---|
| 1 | **0 (BLOCKING security)** | Scrub chunk content before it reaches the LLM | — |
| 2 | 1 | Add `enable_distilled_recall_surface` config flag (default off) | — |
| 3 | 1 | Add `Memory.distilled` field + migration 13 + store/read | 2 |
| 4 | 1 | Populate `memory.distilled` from distillation + grounding gate | 3 |
| 5 | 1 | Embed `distilled or content` behind the flag | 2, 4 |
| 6 | 1 | Recall display prefers the distilled snippet | 3 |
| 7 | 1 | Upgrade the distill prompt (mem0-style) + raise truncation | — (independent; do anytime after 1) |
| 8 | **2 (measure)** | Run R@5/MRR harness — verbatim vs distilled-single vs fanout | 5, 6 |
| 9 | **3 (conditional)** | Provider-adaptive async timing + DREAM consolidation | only if 8 shows the local daemon falls behind |

---

### Task 1 (Phase 0): Scrub chunk content before the LLM sees it — SECURITY

**Files:**
- Modify: `memgentic/memgentic/processing/pipeline.py:329-377` (scrub block + `intel_state` build)
- Test: `memgentic/tests/test_pipeline_scrub.py` (new, or extend existing pipeline test)

**The bug (confirmed):** `scrub_text` mutates `memory.content` (pipeline.py:333-335) but `intel_state` is built from the **unscrubbed** `chunk.content` (pipeline.py:371). When `GOOGLE_API_KEY` is set, raw secrets are sent to cloud Gemini. Promoting distillation to the recall surface would re-surface a scrubbed secret as a top row, so this **blocks Phase 1**.

**Interfaces:**
- Consumes: `scrub_text(text) -> ScrubResult(text, redaction_count)` (already imported in pipeline.py).
- Produces: `chunks` whose `.content` is scrubbed before `intel_state` is built. No new public API.

- [ ] **Step 1: Write the failing test** — a chunk carrying a fake secret; assert the content handed to the intelligence graph is scrubbed.

```python
# memgentic/tests/test_pipeline_scrub.py
import pytest
from memgentic.processing import pipeline as pipeline_mod

@pytest.mark.asyncio
async def test_chunks_scrubbed_before_llm(monkeypatch):
    """The intelligence graph must receive scrubbed chunk content, not raw secrets."""
    seen = {}

    class _FakeGraph:
        async def ainvoke(self, state):
            seen["contents"] = [c["content"] for c in state["chunks"]]
            return {"classified_chunks": [], "all_topics": [], "all_entities": [], "summary": ""}

    monkeypatch.setattr(pipeline_mod, "build_intelligence_graph", lambda **_: _FakeGraph())
    # ... build a Pipeline with credential scrubbing on + a chunk whose content
    # contains 'sk-secret AKIAIOSFODNN7EXAMPLE', run ingest of that chunk batch ...
    # assert no raw secret token survives in seen["contents"]:
    assert all("AKIAIOSFODNN7EXAMPLE" not in c for c in seen["contents"])
```

- [ ] **Step 2: Run it — verify it FAILS** (raw secret currently reaches the graph).

Run: `uv run --no-sync pytest memgentic/tests/test_pipeline_scrub.py -q`
Expected: FAIL (secret present in `seen["contents"]`).

- [ ] **Step 3: Minimal fix** — scrub `chunk.content` in the same scrub pass (chunks and memories are still 1:1 aligned here, before noise filtering). In the block at pipeline.py:330-338, after scrubbing memories, also scrub chunks:

```python
        if self._settings.enable_credential_scrubbing:
            total_redacted = 0
            for memory in memories:
                result = scrub_text(memory.content)
                if result.redaction_count > 0:
                    memory.content = result.text
                    total_redacted += result.redaction_count
            # Scrub the chunk list too — it (not `memories`) feeds the LLM
            # intelligence graph below (intel_state is built from c.content).
            for chunk in chunks:
                cres = scrub_text(chunk.content)
                if cres.redaction_count > 0:
                    chunk.content = cres.text
            if total_redacted:
                logger.info("pipeline.credentials_scrubbed", count=total_redacted)
```

- [ ] **Step 4: Run it — verify it PASSES.** Run the same command. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "fix(security): scrub chunk content before it reaches the LLM intelligence graph"` (type `fix`, releasable — this is a real security fix).

---

### Task 2 (Phase 1): Config flag `enable_distilled_recall_surface` (default OFF)

**Files:**
- Modify: `memgentic/memgentic/config.py` (near `enable_fact_distillation` / value-gate settings)
- Test: `memgentic/tests/test_config.py` (or assert default in any settings test)

**Interfaces:**
- Produces: `settings.enable_distilled_recall_surface: bool` (default `False`), env `MEMGENTIC_ENABLE_DISTILLED_RECALL_SURFACE`.

- [ ] **Step 1: Write failing test** asserting the field exists and defaults False.

```python
def test_distilled_recall_surface_defaults_off(tmp_path):
    from memgentic.config import MemgenticSettings
    s = MemgenticSettings(data_dir=tmp_path / "d")
    assert s.enable_distilled_recall_surface is False
```

- [ ] **Step 2: Run — verify FAIL** (AttributeError / unknown field).
- [ ] **Step 3: Add the field** in `config.py`:

```python
    enable_distilled_recall_surface: bool = Field(
        default=False,
        description=(
            "When True, embed + display the LLM-distilled facts (already computed "
            "by the enriched ingest distill_node) as the recall surface, keeping the "
            "verbatim turn in-row as the FTS5/audit backstop. OFF until the R@5/MRR "
            "harness confirms it beats verbatim. Override via "
            "MEMGENTIC_ENABLE_DISTILLED_RECALL_SURFACE."
        ),
    )
```

- [ ] **Step 4: Run — verify PASS.**
- [ ] **Step 5: Commit.** `git commit -m "feat(config): add enable_distilled_recall_surface flag (default off)"`

---

### Task 3 (Phase 1): `Memory.distilled` field + migration 13 + store/read

**Files:**
- Modify: `memgentic/memgentic/models.py:124` (Memory — add `distilled`)
- Modify: `memgentic/memgentic/storage/metadata.py` (migration runner: add migration **13** `ALTER TABLE memories ADD COLUMN distilled TEXT`; the two `INSERT ... INTO memories (... project, updated_at)` column lists at ~240 and ~322; `_row_to_memory` at ~962)
- Test: `memgentic/tests/test_metadata_distilled.py` (new)

**Interfaces:**
- Produces: `Memory.distilled: str | None = None`; persisted/read round-trip via `MetadataStore`.
- Consumes: existing migration pattern (see migrations 11/12) and `store` / `_row_to_memory`.

- [ ] **Step 1: Write failing round-trip test** — store a Memory with `distilled="X"`, read it back, assert it survives; and a Memory without it reads back `None`.
- [ ] **Step 2: Run — verify FAIL** (`Memory` has no `distilled` / column missing).
- [ ] **Step 3a: Add the model field** in `models.py` (under Content):

```python
    distilled: str | None = Field(
        default=None,
        description=(
            "LLM-distilled, self-contained fact(s) for this memory (the recall "
            "surface when enable_distilled_recall_surface is on). None for raw/legacy "
            "rows. content stays the verbatim source-of-truth."
        ),
    )
```

- [ ] **Step 3b: Add migration 13** in `metadata.py` following the existing numbered-migration pattern (the runner that logs `migration.up_to_date version=12`): `ALTER TABLE memories ADD COLUMN distilled TEXT;`. Read migrations 11/12 first to copy the exact registration shape. Additive, no backfill.
- [ ] **Step 3c: Persist + read** — add `distilled` to both `INSERT INTO memories (...)` column lists (~240, ~322) and their value tuples (`memory.distilled`), and read it in `_row_to_memory` (~962): `distilled=row["distilled"]` (guard for older rows with `row.keys()` / `try`).
- [ ] **Step 4: Run — verify PASS** (round-trip works; legacy rows read `None`).
- [ ] **Step 5: Commit.** `git commit -m "feat(storage): persist Memory.distilled column (migration 13)"`

---

### Task 4 (Phase 1): Populate `memory.distilled` from the distillation + grounding gate

**Files:**
- Modify: `memgentic/memgentic/processing/pipeline.py:427-446` (the value-gate zip loop already reads `classified_chunk.get("distillation")`)
- Create: `memgentic/memgentic/processing/_grounding.py` (small pure helper) — or inline a helper in pipeline.py
- Test: `memgentic/tests/test_pipeline_distilled.py` (new)

**Interfaces:**
- Consumes: `classified_chunk["distillation"] = {"facts": [...], "is_valuable": bool, "value_score": float}` (set by `distill_node`, intelligence.py:610).
- Produces: `memory.distilled` populated (joined facts) when the facts are non-empty AND pass the grounding gate; else left `None`.
- Produces: `is_grounded(distilled: str, source: str) -> bool` — entity/token-overlap heuristic (cheap, no embedding): true when a configurable fraction of distilled non-stopword tokens appear in the source.

- [ ] **Step 1: Write failing tests** — (a) a chunk whose distillation facts are grounded in source → `memory.distilled` set to the joined facts; (b) facts NOT grounded (hallucinated) → `memory.distilled is None`; (c) empty facts → `None`.
- [ ] **Step 2: Run — verify FAIL.**
- [ ] **Step 3: Implement `is_grounded`** (token-overlap, lowercased, drop a tiny stopword set; threshold e.g. 0.5 of distilled content tokens present in source) and, inside the value-gate loop (after the worthless check at line 435, where `distillation` is already in scope), set:

```python
                        facts = (distillation or {}).get("facts") or []
                        if facts:
                            joined = " ".join(f.strip() for f in facts if f.strip())
                            if joined and is_grounded(joined, memory.content):
                                memory.distilled = joined
```

- [ ] **Step 4: Run — verify PASS.**
- [ ] **Step 5: Commit.** `git commit -m "feat(pipeline): populate Memory.distilled from grounded distillation facts"`

---

### Task 5 (Phase 1): Embed `distilled or content` behind the flag

**Files:**
- Modify: `memgentic/memgentic/processing/pipeline.py:492`
- Test: extend `memgentic/tests/test_pipeline_distilled.py`

**Interfaces:**
- Consumes: `settings.enable_distilled_recall_surface` (Task 2), `memory.distilled` (Task 4).

- [ ] **Step 1: Write failing test** — with the flag ON and a memory having `distilled`, assert the text passed to `embed_batch_documents` is the distilled text; with flag OFF, assert it is `content`.
- [ ] **Step 2: Run — verify FAIL.**
- [ ] **Step 3: Change the embed source** at pipeline.py:492:

```python
        if self._settings.enable_distilled_recall_surface:
            texts = [m.distilled or m.content for m in memories]
        else:
            texts = [m.content for m in memories]
```

- [ ] **Step 4: Run — verify PASS** (and existing pipeline tests still pass — flag default off ⇒ unchanged).
- [ ] **Step 5: Commit.** `git commit -m "feat(pipeline): embed distilled recall surface when enabled (default off)"`

---

### Task 6 (Phase 1): Recall display prefers the distilled snippet

**Files:**
- Modify: the recall render paths — `memgentic/memgentic/mcp/server.py` (recall result dict), `memgentic/memgentic/cli.py` (search table), REST serializer if applicable. Grep for where `content` becomes the result `content`/snippet.
- Test: `memgentic/tests/` — assert the rendered snippet prefers `distilled` when present and the flag is on.

**Interfaces:**
- Consumes: `memory.distilled`, `settings.enable_distilled_recall_surface`.

- [ ] **Step 1: Write failing test** — a result row with `distilled` set renders the distilled text as the snippet (flag on); falls back to `content` when `distilled is None`.
- [ ] **Step 2: Run — verify FAIL.**
- [ ] **Step 3: Prefer distilled** in the snippet builder(s): `snippet = (m.distilled if settings.enable_distilled_recall_surface and m.distilled else m.content)`. Keep `expand`/full-content returning verbatim `content`.
- [ ] **Step 4: Run — verify PASS.**
- [ ] **Step 5: Commit.** `git commit -m "feat(recall): prefer distilled snippet on display, verbatim on expand"`

---

### Task 7 (Phase 1): Upgrade the distill prompt (mem0-style) + raise truncation

**Files:**
- Modify: `memgentic/memgentic/processing/intelligence.py:569-579` (prompt) and `:574` (`content[:2000]`)
- Test: `memgentic/tests/test_intelligence_distill.py` — assert the prompt string contains the new rules (cheap string assertions; LLM output itself is integration-tested separately).

**Interfaces:** unchanged signature `_distill_with_llm(llm_client, content, content_type) -> DistillationResult`.

- [ ] **Step 1: Write failing test** — assert the built prompt mentions: preserve identifiers/code/numbers/proper-nouns, resolve pronouns/coreference to named entities, keep a decision with its rationale, ground relative time to absolute.
- [ ] **Step 2: Run — verify FAIL.**
- [ ] **Step 3: Rewrite the prompt** (borrowing mem0's `ADDITIVE_EXTRACTION_PROMPT` rules) and raise truncation `content[:2000]` → a larger cap (e.g. `content[:4000]`, balanced against local `num_ctx=2048`; document the tradeoff). Keep the JSON output contract identical.
- [ ] **Step 4: Run — verify PASS** (and `_distill_heuristic` fallback unchanged).
- [ ] **Step 5: Commit.** `git commit -m "feat(intelligence): mem0-style detail-preserving distill prompt + larger context"`

---

### Task 8 (Phase 2): Measure — verbatim vs distilled-single vs fact-fanout

**Files:** `benchmarks/` harness (LongMemEval-style R@5 / MRR). No production code unless a fan-out arm is built.

- [ ] Run the existing harness on the maintainer's own DB across three arms: (a) verbatim (today), (b) distilled-single-surface (flag ON, Tasks 2–6), (c) distilled-fanout (N atomic fact sibling rows — only if needed).
- [ ] **Decision gate:** if (b) beats (a) and is sufficient → flip `enable_distilled_recall_surface` default ON + run a one-time `re-embed` over existing `raw_exchange` rows (LLM-free; reads persisted `distilled`, falls back to `content`). ONLY if (b) is insufficient on precision@k → implement the additive fact-row variant (`content_type=fact/decision/learning` sibling rows linked via the existing `dual_sibling_id`/`derived_from` pointer, write-time dedup, dashboard sibling-collapse). Do NOT build fan-out speculatively.

---

### Task 9 (Phase 3, CONDITIONAL): provider-adaptive async timing + DREAM consolidation

Build **only if** Task 8 shows the local-only daemon falling behind (gemma4:e4b serializes ~2–4 s/call; an 8-chunk session ≈ 40–70 s on the hot path). Then: write-time stores verbatim + heuristic class + embedding immediately and marks rows `pending_enrichment`; a throttled background worker (home it in the existing dream/consolidation path) runs distillation off the hot path and re-embeds. Optionally merge classify+distill into one structured call (2N→N). Cloud Gemini path stays synchronous. Reserve DREAM MERGE/SUPERSEDE for cross-session dedup of accumulated facts — never the synchronous ingest path.

---

## Do NOT do (panel red-lines)

- Do NOT "LLM-clean each session before chunking" at the adapter layer (forks 9 adapters; breaks adapters-produce-raw / pipeline-does-intelligence; multi-topic session still centroid-dilutes).
- Do NOT overwrite/replace verbatim `content` — `distilled` is a separate column.
- Do NOT recompute distillation during `re-embed`.
- Do NOT add a 4th capture profile.
- Do NOT flip the default before the harness confirms it on real data.
- Do NOT vector-embed BOTH verbatim and distilled (FTS5 covers the lexical backstop in-row).
- Do NOT over-atomize (decision + rationale stay together).
- Do NOT adopt mem0-classic's 2-call ADD/UPDATE/DELETE on the local hot path.

## Self-review

- **Spec coverage:** Phase 0 → Task 1; Phase 1 (persist distillation, flag, grounding, embed, display, prompt) → Tasks 2–7; Phase 2 measure/decide → Task 8; Phase 3 conditional → Task 9. ✓
- **Type consistency:** `Memory.distilled: str | None` used identically in Tasks 3/4/5/6; `enable_distilled_recall_surface` (Task 2) referenced in 5/6; `is_grounded(distilled, source) -> bool` defined in Task 4, used there only. ✓
- **Open items to verify during implementation (read exact code first):** the migration-registration shape in `metadata.py` (Task 3b), the exact `INSERT INTO memories` column lists (~240/~322) and `_row_to_memory` (~962), and the recall snippet builder location(s) for Task 6.
