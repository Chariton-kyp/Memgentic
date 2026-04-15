"""Memgentic exception hierarchy."""


class MemgenticError(Exception):
    """Base exception for all Memgentic errors."""


class EmbeddingError(MemgenticError):
    """Failed to generate embeddings."""


class StorageError(MemgenticError):
    """Failed to read/write from storage."""


class AdapterError(MemgenticError):
    """Failed to parse conversation files."""


class PipelineError(MemgenticError):
    """Failed during ingestion pipeline processing."""
