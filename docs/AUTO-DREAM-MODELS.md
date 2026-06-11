# Auto-Dream Model Configuration

This is the **central reference** for choosing LLM providers and models for the auto-dream pipeline.

The dream pipeline runs in two LLM phases:

- **Phase 2 — Gather Signal.** A single bulk-scan call over recent session transcripts. Cheap and fast is the right default.
- **Phase 3 — Consolidate.** N calls (one per topic cluster, capped at 20) that propose patches against the live memory store. Quality matters because hallucinated JSON or schema breaks corrupt consolidation.

Each phase has its **own configurable model**, so you can mix providers freely (e.g. cheap cloud for Phase 2, local for Phase 3).

---

## How model name → provider routing works

Routing is purely by **prefix match on the model name** (case-insensitive):

| Model name pattern | Provider | Required env |
|---|---|---|
| `claude-*` or `anthropic/...` | Anthropic API | `MEMGENTIC_ANTHROPIC_API_KEY` |
| `gemini-*` or `models/gemini-*` | Google API | `MEMGENTIC_GOOGLE_API_KEY` |
| `gpt-*`, `o1-*`, or `openai/...` | OpenAI-compat (LM Studio / vLLM / llama.cpp) | `MEMGENTIC_OPENAI_COMPAT_BASE_URL` |
| **anything else** (e.g. `qwen3.6:35b-a3b`, `gemma4:e4b`, `hf.co/unsloth/...`) | **Ollama** | Ollama running at `MEMGENTIC_OLLAMA_URL` |
| empty string | default `LLMClient` chain (Gemini → OpenAI-compat → Ollama → heuristics) | — |

If the chosen provider is misconfigured, the pipeline silently falls back to the default `LLMClient`. Watch the logs for `dream.<phase>.fallback` warnings.

---

## Where to configure (4 entry points)

### 1. `.env` — global defaults

```env
# Phase 2: cheap and fast (single call per dream)
MEMGENTIC_DREAM_SIGNAL_MODEL=claude-haiku-4-5

# Phase 3: quality (N calls per dream)
MEMGENTIC_DREAM_CONSOLIDATE_MODEL=claude-sonnet-4-6

# When you set a claude-* model above, this key is required:
MEMGENTIC_ANTHROPIC_API_KEY=sk-ant-...
```

### 2. `memgentic init` / `memgentic setup` — interactive wizard

Step 3b prompts for one of these bundled presets:

| Preset | Phase 2 | Phase 3 | Cost / run | Wall-clock | Needs |
|---|---|---|---|---|---|
| Cheapest cloud | `claude-haiku-4-5` | `claude-haiku-4-5` | ~$0.10 | 30-90 s | Anthropic key |
| Best balanced ⭐ | `claude-haiku-4-5` | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S` | ~$0.005 + local | 6-15 min | Anthropic key + Ollama |
| Fully local | `gemma4:e4b` | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S` | $0 | 8-15 min | Ollama (~25 GB disk) |
| Portable local | `gemma4:e4b` | `gemma4:26b-a4b` | $0 | 20-60 min on 16 GB | Ollama (~22 GB disk) |
| Quality cloud | `claude-haiku-4-5` | `claude-sonnet-4-6` | ~$0.90 | 5-10 min | Anthropic key |

### 3. CLI per-run override

```powershell
memgentic dream run --signal-model gemma4:e4b --consolidate-model qwen3.6:35b-a3b
```

Empty string forces the default `LLMClient` chain.

### 4. MCP / REST / Dashboard per-run override

- **MCP**: `memgentic_dream_run` accepts optional `signal_model` and `consolidate_model` params.
- **REST**: `POST /api/v1/dreams` body fields `signal_model` and `consolidate_model`.
- **Dashboard**: the `/dreams` page has an **Advanced** drop-down with per-phase model fields and provider chips.

`memgentic dream models` prints the currently-effective configuration plus a list of installed Ollama tags.

---

## Recommended models (May 2026)

### Cloud — cheap

| Model | Cost | Use for |
|---|---|---|
| `claude-haiku-4-5` ⭐ | $1 / $5 per 1M tokens | Excellent default for both phases. Tight schema adherence. |
| `gemini-3.1-flash-lite` | $0.25 / $1.50 per 1M tokens | Cheapest cloud option. Phase 2 ideal. |
| `gpt-4o-mini` (via OpenAI-compat) | varies | Solid for both phases when you have an OpenAI account. |

### Cloud — quality

| Model | Cost | Use for |
|---|---|---|
| `claude-sonnet-4-6` | $3 / $15 per 1M | Phase 3 when patch quality matters most. ~$0.90 / run with our default cluster cap. |
| `claude-opus-4-7` | $15 / $75 per 1M | Phase 3 only when you need state-of-the-art. ~$4 / run. |
| `gemini-3.1-pro` | varies | Long-context alternative. |

### Local — best (May 2026)

| Tag | Total / Active | RAM Q4 | JSON reliability | Notes |
|---|---|---|---|---|
| `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S` ⭐ | 35B / 3B (MoE) | ~21 GB | **5/5** | Top open-weight for Phase 3. Apache 2.0. |
| `qwen3.6:27b` | 27B dense | ~18 GB | 5/5 | Slower but strongest single-model option. |
| `gemma4:26b-a4b` | 26B / 3.8B (MoE) | ~18 GB | 4/5 | Strong runner-up. **Never** pass `think=false` — silent JSON corruption. |
| `gemma4:e4b` | ~4.5B effective | ~6 GB | 3/5 | Solid for Phase 2 (bulk scan); borderline for Phase 3. |
| `gemma4:e2b` | ~2.3B effective | ~3 GB | 2/5 | Phase 2 only on low-RAM machines. |
| `phi4-reasoning:14b` | 14B dense | ~11 GB | 4/5 | Good middle ground when Qwen 3.6 is unavailable. |

### Models to AVOID

| Tag | Why |
|---|---|
| `qwen3.5:9b` | Returns JSON-in-markdown despite schema ([ollama#15540](https://github.com/ollama/ollama/issues/15540)) |
| `qwen3-coder:30b` with `enable_thinking=False` | Malformed JSON ([vllm#18819](https://github.com/vllm-project/vllm/issues/18819)) |
| `gemma4:*` with `think=false` | Format constraint silently ignored ([ollama#15260](https://github.com/ollama/ollama/issues/15260)) |
| Older `qwen2.5:*` | Superseded by 3.5/3.6 — no reason to use today |

---

## Hardware sizing & NVMe streaming

Memgentic's local LLM stack is **mmap-based**, so any model fits on any machine — it's just slower when RAM is small. Per-token latency for `qwen3.6:35b-a3b` Q4 (~21 GB) on CPU:

| RAM | Hot working set | NVMe Gen4 spillover | Throughput |
|---|---|---|---|
| 64 GB+ | full model resident | none | 10-20 tok/s |
| 32 GB | most layers + hot experts | cold experts ~5 GB | 6-12 tok/s |
| 16 GB | dense layers + ~2-3 hot experts | ~14 GB streaming | 2-5 tok/s |
| 8 GB | dense layers only | most experts streaming | 0.5-1.5 tok/s — sluggish |

**Why MoE matters here**: only ~3 B params are touched per token, so the access pattern is sparse and cacheable. Dense 27B on the same hardware would thrash the page cache. Mixture-of-Experts models like `qwen3.6:35b-a3b` and `gemma4:26b-a4b` are the **only** realistic path on low-spec machines.

### Required Ollama env vars for the dream pipeline

```env
# Keep models warm between Phase 2 and Phase 3 (otherwise pay 5-30 s
# cold-fault penalty per phase change)
OLLAMA_KEEP_ALIVE=-1

# Avoid RAM × N scaling
OLLAMA_NUM_PARALLEL=1

# Speed up CPU attention on supported chips
OLLAMA_FLASH_ATTENTION=1

# When Phase 2 and Phase 3 use DIFFERENT Ollama models, allow both loaded
OLLAMA_MAX_LOADED_MODELS=2
```

Set these in your shell profile or service environment. They are not Memgentic-specific — they affect any Ollama client.

---

## Caveats and red flags

1. **Don't pass `think=false`** to Qwen 3.x or Gemma 4 in Ollama — both silently corrupt structured output. Memgentic doesn't pass this flag, but be aware if you proxy through a custom client.
2. **Mixing Ollama models between Phase 2 and Phase 3** invalidates the page cache between phases. On low-RAM boxes, prefer the same model for both phases (e.g. `qwen3.6:35b-a3b` everywhere).
3. **Gemini API requires `MEMGENTIC_GOOGLE_API_KEY`**. The model name `gemini-...` alone won't route there without the key set — it will silently fall back to the next provider in the chain.
4. **`MEMGENTIC_ANTHROPIC_API_KEY` lives in `.env`, not the shell**. Memgentic uses Pydantic Settings with `env_prefix="MEMGENTIC_"`, so the *unprefixed* `ANTHROPIC_API_KEY` is ignored.
5. **First Ollama run is slow** — up to 30 s cold-fault on Gen4 NVMe before the first token. This is one-time per model load. Subsequent calls are instant if `OLLAMA_KEEP_ALIVE=-1`.

---

## Quick decision tree

```
Do you have an Anthropic API key?
├── No  → Local route. Run `ollama pull hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S`
│         Set both MEMGENTIC_DREAM_*_MODEL to that tag (or use the wizard preset 3).
└── Yes → How much do you iterate?
         ├── Daily/hourly  → Cheapest cloud (Haiku × 2). Wizard preset 1.
         ├── Weekly        → Best balanced. Wizard preset 2.
         └── Production    → Quality cloud (Sonnet for Phase 3). Wizard preset 5.
```

---

## See also

- [`docs/plans/AUTO-DREAM.md`](plans/AUTO-DREAM.md) — full feature plan and architecture.
- [`docs/MCP-TOOLS.md`](MCP-TOOLS.md) — `memgentic_dream_run` MCP signature.
- `memgentic dream models` — runtime view of your current setup.
- `memgentic dream run --help` — CLI flag reference.
