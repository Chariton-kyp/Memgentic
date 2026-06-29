# Recommended setup (W6a defaults)

This page documents the recommended production configuration for Memgentic
as of the W6a defaults change. All components below are what the shipped
defaults now target; every item is optional and configurable.

---

## Components

| Component | What | Notes |
|---|---|---|
| **Ollama** | Embedding server | `ollama pull qwen3-embedding:4b` |
| **Qdrant** | Vector store | Docker image `qdrant/qdrant` |
| **llama-server** | Reranker (optional) | `llama.cpp`, serves `/v1/rerank` |
| **Voodisss Qwen3-Reranker GGUF** | Cross-encoder (optional) | ~396 MB |

---

## 1. Qdrant server

Qdrant is now the **default vector backend** (`MEMGENTIC_STORAGE_BACKEND=qdrant`).
Run it via Docker:

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant
```

Or use [Qdrant Cloud](https://cloud.qdrant.io/) and set
`MEMGENTIC_QDRANT_URL` + `MEMGENTIC_QDRANT_API_KEY`.

The fallback zero-config backend (sqlite-vec) remains available:
```bash
export MEMGENTIC_STORAGE_BACKEND=sqlite_vec
```

---

## 2. Embedding model — qwen3-embedding:4b

`qwen3-embedding:4b` is the new default (`MEMGENTIC_EMBEDDING_MODEL`).
It is natively 2560-dim; Memgentic requests 1024 dims via Ollama's
`dimensions` parameter, activating Matryoshka (MRL) truncation at the
model level. This gives roughly +5 MTEB points vs the 0.6B model.

```bash
ollama pull qwen3-embedding:4b
```

Size: ~2.5 GB (q4_K_M). For constrained environments use the lighter
fallback:
```bash
export MEMGENTIC_EMBEDDING_MODEL=qwen3-embedding:0.6b
export MEMGENTIC_EMBEDDING_DIMENSIONS=768
```

---

## 2b. Embeddings via an OpenAI-compatible server (drop Ollama)

Embeddings don't have to come from Ollama. Any server that speaks the OpenAI
`/v1/embeddings` API works — llama.cpp's `llama-server`, vLLM, LM Studio, or
Text-Embeddings-Inference — so you can run **one** inference engine (e.g.
llama.cpp) for both embeddings and the reranker and skip Ollama entirely.

Set the provider + base URL (treat the base URL like the OpenAI SDK `base_url` —
include the `/v1`; `/embeddings` is appended automatically):

```bash
export MEMGENTIC_EMBEDDING_PROVIDER=openai_compat
export MEMGENTIC_EMBEDDING_BASE_URL=http://localhost:8082/v1
export MEMGENTIC_EMBEDDING_API_KEY=         # optional; most local servers need none
export MEMGENTIC_EMBEDDING_MODEL=bge-m3     # informational for most local servers
export MEMGENTIC_EMBEDDING_DIMENSIONS=1024  # MUST match what the server returns
```

### Example: bge-m3 on llama.cpp's llama-server

```bash
llama-server -m bge-m3-Q8_0.gguf --embedding --pooling cls --port 8082
```

### Example: vLLM

```bash
vllm serve BAAI/bge-m3 --task embed --port 8082
# then: MEMGENTIC_EMBEDDING_BASE_URL=http://localhost:8082/v1
```

> **Switching engines for an existing store:** the same model on a different
> engine (Ollama → llama.cpp/vLLM) can produce subtly different vectors
> (quantisation, pooling). If recall quality drops after switching, run
> `memgentic re-embed` to rebuild the collection on the new engine.

---

## 3. Reranker (optional) — Qwen3-Reranker-0.6B via llama-server

The reranker is **off by default** (`MEMGENTIC_ENABLE_RERANKER=false`).
When enabled, Memgentic POSTs the top fused recall candidates to a
`llama-server` `/v1/rerank` endpoint and reorders by absolute relevance.
A wedged or missing server never breaks recall — it always falls back to
the fused order.

### 3a. Get the verified GGUF

Many community Qwen3-Reranker GGUFs silently drop the classifier head
and emit garbage scores. Use the **Voodisss** repos which are verified
correct (the broken ones fail visibly at server start, not silently):

```bash
# Light default (~396 MB)
huggingface-cli download Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp \
    Qwen3-Reranker-0.6B-Q4_K_M.gguf --local-dir ./models

# Max quality opt-in (~2.3 GB)
# huggingface-cli download Voodisss/Qwen3-Reranker-4B-GGUF-llama_cpp \
#     Qwen3-Reranker-4B-Q4_K_M.gguf --local-dir ./models
```

### 3b. Start llama-server

```bash
llama-server \
    -m ./models/Qwen3-Reranker-0.6B-Q4_K_M.gguf \
    --reranking --pooling rank --embedding \
    --port 8081
```

The `--reranking --pooling rank --embedding` flags are required: they
expose the `/v1/rerank` endpoint Memgentic calls.

### 3c. Enable the reranker

```bash
export MEMGENTIC_ENABLE_RERANKER=true
export MEMGENTIC_RERANKER_URL=http://localhost:8081   # default
# Optional tuning:
export MEMGENTIC_RERANKER_TOP_K=20          # candidates to rerank (default)
export MEMGENTIC_RERANKER_MIN_SCORE=0.0     # absolute floor; raise (e.g. 0.3) to prune
export MEMGENTIC_RERANKER_TIMEOUT_S=2.0     # connect timeout before fallback
export MEMGENTIC_RERANKER_MODEL=Qwen3-Reranker-0.6B-Q4_K_M   # informational
```

---

## 4. Complete env-var reference

```bash
# Vector backend
MEMGENTIC_STORAGE_BACKEND=qdrant          # new default; sqlite_vec = zero-config fallback
MEMGENTIC_QDRANT_URL=http://localhost:6333
MEMGENTIC_QDRANT_API_KEY=                 # leave unset for local Docker

# Embedding
MEMGENTIC_EMBEDDING_PROVIDER=ollama        # ollama (default) | openai | openai_compat
MEMGENTIC_EMBEDDING_MODEL=qwen3-embedding:4b
MEMGENTIC_EMBEDDING_DIMENSIONS=1024
MEMGENTIC_OLLAMA_URL=http://localhost:11434
# For provider=openai_compat (llama.cpp / vLLM / LM Studio / TEI — no Ollama):
MEMGENTIC_EMBEDDING_BASE_URL=              # e.g. http://localhost:8082/v1 ('/embeddings' appended)
MEMGENTIC_EMBEDDING_API_KEY=               # optional bearer token; local servers usually need none

# Reranker (optional)
MEMGENTIC_ENABLE_RERANKER=false           # set true to activate
MEMGENTIC_RERANKER_URL=http://localhost:8081
MEMGENTIC_RERANKER_TOP_K=20
MEMGENTIC_RERANKER_MIN_SCORE=0.0
MEMGENTIC_RERANKER_TIMEOUT_S=2.0
MEMGENTIC_RERANKER_MODEL=Qwen3-Reranker-0.6B-Q4_K_M
```

---

## 5. Migration / upgrade guide

Follow these steps in order when upgrading from an older install.

### Step 1 — Start Qdrant

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant
```

Verify it responds:
```bash
curl http://localhost:6333/healthz
```

### Step 2 — Pull the new embedding model

```bash
ollama pull qwen3-embedding:4b
```

### Step 3 — Set config (`.env` or shell)

```bash
MEMGENTIC_STORAGE_BACKEND=qdrant
MEMGENTIC_EMBEDDING_MODEL=qwen3-embedding:4b
MEMGENTIC_EMBEDDING_DIMENSIONS=1024
```

### Step 4 — Re-embed the store

The new model lives in a different vector space than the old one. Run:

```bash
memgentic re-embed
```

This iterates every active memory, re-embeds it with the new model, and
upserts into Qdrant. It is resumable (idempotent per memory ID).

### Step 5 — (Optional) enable reranker

Follow §3 above to install and start `llama-server`, then set
`MEMGENTIC_ENABLE_RERANKER=true`.

---

## Notes

- **Existing sqlite-vec installs**: set `MEMGENTIC_STORAGE_BACKEND=sqlite_vec` to
  keep the old backend. Run `memgentic re-embed` only if you also change the
  embedding model.
- **Model mismatch guard**: Memgentic refuses to start if the configured model /
  dimensions disagree with what the collection was built with, and prints an
  actionable error message. Run `memgentic re-embed` or revert the env vars.
- **Reranker is always optional**: if `llama-server` is down or unreachable,
  recall falls back to the fused order transparently.
