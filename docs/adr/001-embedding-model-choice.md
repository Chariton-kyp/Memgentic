# ADR-001: Embedding Model Choice — Qwen3-Embedding-4B

## Status

Accepted (2026-03-15)

## Context

Memgentic needs an embedding model to convert memory text into vectors for semantic search. Key requirements:

- Must run locally for privacy (no data leaves the user's machine).
- Must be the same model in local development and any future cloud deployment to avoid embedding drift.
- Must be open-source with a permissive license (BSL-1.1 project cannot depend on restrictively licensed models).
- Must produce high-quality multilingual embeddings at reasonable VRAM cost.
- Matryoshka Representation Learning (MRL) support is desirable so we can truncate dimensions for storage efficiency without retraining.

We evaluated OpenAI `text-embedding-3-small`, Nomic Embed, BGE-M3, and the Qwen3 embedding family.

## Decision

Use **Qwen3-Embedding-4B** served via Ollama 0.18+, with embeddings truncated to **768 dimensions** using MRL.

- **License**: Apache 2.0 — fully compatible with BSL-1.1.
- **Local-first**: Runs on consumer GPUs (4 GB+ VRAM) through Ollama, no API key required.
- **MRL truncation**: Native 2048-dimensional output truncated to 768d with minimal quality loss, cutting storage by 62%.
- **Same model everywhere**: Ollama serves the identical model binary locally and in Docker, eliminating embedding drift between environments.
- **No API costs**: Zero marginal cost per embedding, enabling aggressive re-embedding and consolidation.

## Consequences

- **Positive**: Full offline operation, no vendor dependency, consistent embeddings across environments, no recurring costs.
- **Negative**: Requires Ollama installation, ~2.5 GB disk for model weights, slower than API-based embedding on CPU-only machines.
- **Mitigated**: The `memgentic setup` command offers smaller model presets (0.6B, Nomic) for resource-constrained hardware.
