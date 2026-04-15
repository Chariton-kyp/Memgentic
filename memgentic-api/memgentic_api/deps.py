"""FastAPI dependency injection for Memgentic stores and services."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from memgentic.processing.embedder import Embedder
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def get_metadata_store(request: Request) -> MetadataStore:
    """Get the shared MetadataStore from app state."""
    return request.app.state.metadata_store


def get_vector_store(request: Request) -> VectorStore:
    """Get the shared VectorStore from app state."""
    return request.app.state.vector_store


def get_embedder(request: Request) -> Embedder:
    """Get the shared Embedder from app state."""
    return request.app.state.embedder


def get_pipeline(request: Request) -> IngestionPipeline:
    """Get the shared IngestionPipeline from app state."""
    return request.app.state.pipeline


# Type aliases for cleaner route signatures
MetadataStoreDep = Annotated[MetadataStore, Depends(get_metadata_store)]
VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
PipelineDep = Annotated[IngestionPipeline, Depends(get_pipeline)]
