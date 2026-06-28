# Reranker setup (optional cross-encoder relevance gate)

Memgentic can re-score recall candidates with a Qwen3-Reranker cross-encoder.
Unlike the relative min-max `relevance` floor from RRF fusion, the rerank score
is an **absolute** [0, 1] relevance value, so it doubles as a "drop clearly-weak
results" gate (`reranker_min_score`).

The reranker is **OFF by default** and entirely optional. When it is off, or the
server is unreachable, recall falls back to the fused order unchanged — it never
breaks because the reranker is off or down.

## Ollama cannot serve rerankers

Ollama has no rank-pooling support (llama.cpp issue #16076), so it cannot serve
a reranker. Run llama.cpp's `llama-server` instead.

## 1. Get a verified-working GGUF

Many community Qwen3-Reranker GGUF conversions silently drop the classifier head
and emit garbage scores (e.g. `4.5e-23`). Use the **Voodisss** repos:

- Light (default), ~396 MB: `Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp`
- Max quality (opt-in): `Voodisss/Qwen3-Reranker-4B-GGUF-llama_cpp`

```bash
# Example: download the 0.6B Q4_K_M GGUF from the verified repo
huggingface-cli download Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp \
    Qwen3-Reranker-0.6B-Q4_K_M.gguf --local-dir ./models
```

## 2. Start llama-server with rank pooling

```bash
llama-server \
    -m ./models/Qwen3-Reranker-0.6B-Q4_K_M.gguf \
    --reranking --pooling rank --embedding \
    --port 8081
```

`--reranking --pooling rank --embedding` is required: it exposes the
Jina/Cohere-style `POST /v1/rerank` endpoint Memgentic calls. A broken GGUF
fails loudly here at server start (not silently at query time).

## 3. Enable it in Memgentic

```bash
export MEMGENTIC_ENABLE_RERANKER=true
export MEMGENTIC_RERANKER_URL=http://localhost:8081   # default
# Optional tuning:
export MEMGENTIC_RERANKER_TOP_K=20          # how many fused candidates to rerank
export MEMGENTIC_RERANKER_MIN_SCORE=0.0     # absolute floor; raise (e.g. 0.3) to prune
export MEMGENTIC_RERANKER_TIMEOUT_S=2.0     # short, so a wedged server can't stall recall
export MEMGENTIC_RERANKER_MODEL=Qwen3-Reranker-0.6B   # informational only
```

That is all. On the next recall, the top `reranker_top_k` fused candidates are
re-scored, reordered by the absolute rerank score (written back as the result's
`relevance`), and any candidate below `reranker_min_score` is dropped. Candidates
beyond the rerank window keep their fused order so recall is never shrunk.

## Behaviour notes

- **Graceful degradation:** if the server is unreachable / errors / times out,
  Memgentic logs a single throttled warning and returns the fused order. A short
  "down" cache (~30 s) means one outage does not make every subsequent query pay
  the connect timeout.
- **Where it runs:** both search paths — hybrid (intelligence extras installed)
  and basic (vector-only fallback) — go through the same `maybe_rerank` gate.
- **Absolute floor vs. fused floor:** `recall_min_relevance` is a *relative*
  min-max floor applied during fusion; `reranker_min_score` is an *absolute* floor
  on the cross-encoder score. They are complementary — fusion trims first, the
  reranker provides the absolute "is this actually relevant?" gate.
