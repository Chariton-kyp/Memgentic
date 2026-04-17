"""Memgentic exception hierarchy."""


class MemgenticError(Exception):
    """Base exception for all Memgentic errors."""


class EmbeddingError(MemgenticError):
    """Failed to generate embeddings."""


class StorageError(MemgenticError):
    """Failed to read/write from storage."""


class EmbeddingMismatchError(StorageError):
    """Raised when the configured embedding model or dimensions differ from
    what was used to build the existing vector collection.

    Mixing embeddings produced by different models yields meaningless similarity
    scores, so Memgentic refuses to start rather than silently corrupt results.
    The message includes the migration steps the user needs to run.
    """


class AdapterError(MemgenticError):
    """Failed to parse conversation files."""


class PipelineError(MemgenticError):
    """Failed during ingestion pipeline processing."""
