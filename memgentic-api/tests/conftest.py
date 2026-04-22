"""Shared fixtures for Memgentic API tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.graph.knowledge import KnowledgeGraph, create_knowledge_graph
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

from memgentic_api.routes import (
    briefing,
    collections,
    import_export,
    ingestion,
    memories,
    persona,
    skills,
    sources,
    stats,
    uploads,
)
from memgentic_api.routes import (
    settings as settings_routes,
)

EMBEDDING_DIM = 768


def _make_fake_embedding(seed: float = 0.1) -> list[float]:
    """Return a deterministic 768-dim embedding."""
    return [seed] * EMBEDDING_DIM


def _make_fake_embeddings(texts: list[str]) -> list[list[float]]:
    """Return one fake embedding per text."""
    return [_make_fake_embedding(0.1 + i * 0.01) for i in range(len(texts))]


def _build_mock_embedder() -> AsyncMock:
    """Create a mock Embedder whose embed/embed_batch return 768-dim vectors."""
    embedder = AsyncMock()
    embedder.embed = AsyncMock(side_effect=lambda text: _make_fake_embedding())
    embedder.embed_batch = AsyncMock(side_effect=lambda texts: _make_fake_embeddings(texts))
    embedder.close = AsyncMock()
    return embedder


def _create_test_app(
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: AsyncMock,
    pipeline: IngestionPipeline,
    graph: KnowledgeGraph,
) -> FastAPI:
    """Build a FastAPI app with stores injected via app.state (no lifespan)."""
    app = FastAPI()
    app.state.metadata_store = metadata_store
    app.state.vector_store = vector_store
    app.state.embedder = embedder
    app.state.pipeline = pipeline
    app.state.graph = graph

    app.include_router(memories.router, prefix="/api/v1")
    app.include_router(sources.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    app.include_router(import_export.router, prefix="/api/v1")
    app.include_router(collections.router, prefix="/api/v1")
    app.include_router(uploads.router, prefix="/api/v1")
    app.include_router(skills.router, prefix="/api/v1")
    app.include_router(ingestion.router, prefix="/api/v1")
    app.include_router(settings_routes.router, prefix="/api/v1")
    app.include_router(persona.router, prefix="/api/v1")
    app.include_router(briefing.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health_check():
        return {
            "status": "ok",
            "version": "0.1.0",
            "storage_backend": "local",
        }

    return app


@pytest.fixture
async def client(tmp_path: Path):
    """Yield an httpx.AsyncClient wired to a test FastAPI app with empty stores."""
    settings = MemgenticSettings(
        data_dir=tmp_path / "mneme_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",  # Unreachable — force local file mode for tests
        embedding_dimensions=EMBEDDING_DIM,
    )

    metadata_store = MetadataStore(settings.sqlite_path)
    vector_store = VectorStore(settings)
    embedder = _build_mock_embedder()

    await metadata_store.initialize()
    await vector_store.initialize()

    graph = create_knowledge_graph(settings.graph_path)
    pipeline = IngestionPipeline(settings, metadata_store, vector_store, embedder)
    app = _create_test_app(metadata_store, vector_store, embedder, pipeline, graph)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    await metadata_store.close()
    await vector_store.close()


def _sample_memories() -> list[Memory]:
    """Three sample memories for seeded tests."""
    return [
        Memory(
            content="Python uses indentation for block scoping",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CLAUDE_CODE,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["python", "syntax"],
            entities=["Python"],
        ),
        Memory(
            content="Qdrant supports both local and server modes",
            content_type=ContentType.LEARNING,
            source=SourceMetadata(
                platform=Platform.CHATGPT,
                capture_method=CaptureMethod.MCP_TOOL,
            ),
            topics=["qdrant", "vectors"],
            entities=["Qdrant"],
        ),
        Memory(
            content="FastAPI is built on top of Starlette and Pydantic",
            content_type=ContentType.FACT,
            source=SourceMetadata(
                platform=Platform.CLAUDE_CODE,
                capture_method=CaptureMethod.AUTO_DAEMON,
            ),
            topics=["fastapi", "python"],
            entities=["FastAPI", "Starlette", "Pydantic"],
        ),
    ]


@pytest.fixture
async def seeded_client(tmp_path: Path):
    """Yield an httpx.AsyncClient with 3 pre-seeded memories."""
    settings = MemgenticSettings(
        data_dir=tmp_path / "mneme_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",  # Unreachable — force local file mode for tests
        embedding_dimensions=EMBEDDING_DIM,
    )

    metadata_store = MetadataStore(settings.sqlite_path)
    vector_store = VectorStore(settings)
    embedder = _build_mock_embedder()

    await metadata_store.initialize()
    await vector_store.initialize()

    # Seed memories via the real stores
    sample = _sample_memories()
    for mem in sample:
        embedding = _make_fake_embedding()
        await metadata_store.save_memory(mem)
        await vector_store.upsert_memory(mem, embedding)

    graph = create_knowledge_graph(settings.graph_path)
    pipeline = IngestionPipeline(settings, metadata_store, vector_store, embedder)
    app = _create_test_app(metadata_store, vector_store, embedder, pipeline, graph)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        # Attach sample IDs for convenient lookup in tests
        ac.sample_ids = [m.id for m in sample]  # type: ignore[attr-defined]
        yield ac

    await metadata_store.close()
    await vector_store.close()
