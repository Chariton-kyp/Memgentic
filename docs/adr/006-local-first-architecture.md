# ADR-006: Local-First Architecture

## Status

Accepted (2026-03-15)

## Context

AI memory systems handle deeply personal data — conversation histories, decisions, code snippets, preferences, and work context. Users are justifiably concerned about:

- **Privacy**: Sending conversation data to third-party servers.
- **Vendor lock-in**: Being dependent on a SaaS provider for access to their own memories.
- **Offline access**: Needing internet connectivity to search their knowledge base.
- **Data ownership**: Unclear data retention and deletion policies.
- **Cost**: Per-query or per-storage pricing for a tool that should be a personal utility.

Competing tools (Mem0, Zep) are cloud-first with local modes as afterthoughts.

## Decision

Memgentic is **local-first by design**: all data stays on the user's machine by default, and every feature works fully offline.

- **SQLite + Qdrant local**: Metadata in SQLite, vectors in Qdrant file-based mode. No external database process required.
- **Ollama for embeddings**: Embedding model runs locally — no API keys, no network calls for core functionality.
- **No telemetry**: Zero analytics, tracking, or phone-home behavior.
- **User owns data**: Standard file formats (SQLite, JSON graph). GDPR Article 20 export built into the CLI (`memgentic export-gdpr`).

## Consequences

- **Positive**: Complete privacy, offline operation, no recurring costs, no vendor dependency, full data portability, GDPR compliance by design.
- **Negative**: No cross-device sync out of the box. Users must manage their own Ollama installation. No collaborative features without a multi-user backend.
- **Mitigated**: Docker Compose provides one-command setup. The `memgentic doctor` command validates prerequisites.
