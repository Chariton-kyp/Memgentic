# ADR-002: Vector Database Choice — Qdrant

## Status

Accepted (2026-03-15)

## Context

Memgentic needs a vector database for similarity search over memory embeddings. Requirements:

- Must support a zero-configuration local mode for single-user desktop use.
- Must scale to a proper server deployment for future cloud/multi-user scenarios.
- Must support metadata filtering (by platform, content type, date range) alongside vector search.
- Must have an async Python client for integration with our asyncio-based pipeline.
- Should not require a separate database process during local development.

We evaluated Qdrant, ChromaDB, Weaviate, Milvus, and pgvector.

## Decision

Use **Qdrant** (>=1.17) with its file-based local storage mode for development and single-user installs, and its server mode for Docker/cloud deployments.

- **File-based local mode**: `qdrant-client` can operate entirely in-process using local files — no separate server, no Docker dependency for basic use.
- **Server mode**: The same client API connects to a Qdrant server container when scaling up, requiring zero code changes.
- **Async client**: `qdrant_client.AsyncQdrantClient` integrates naturally with our async pipeline.
- **Efficient filtering**: Native payload filtering lets us apply source, platform, and date filters at the vector search level rather than post-filtering.
- **Proven at scale**: Qdrant handles millions of vectors efficiently with HNSW indexing.

## Consequences

- **Positive**: Zero-config local development, seamless local-to-server transition, strong filtering, async-native API.
- **Negative**: Less ecosystem tooling than pgvector (no SQL interface), additional container in Docker Compose for server mode.
- **Mitigated**: The `VectorStore` abstraction layer could support alternative backends if needed in the future.
