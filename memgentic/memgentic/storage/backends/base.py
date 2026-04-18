"""Backend protocol for Memgentic vector stores.

The protocol mirrors the public surface of ``VectorStore`` today so we can swap
implementations without churning callers. We intentionally keep the filter
input as :class:`SessionConfig` (reusing the existing model) rather than
introducing a neutral ``FilterSpec`` — minimising blast radius for this PR.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from memgentic.models import Memory, SessionConfig


@runtime_checkable
class VectorBackend(Protocol):
    """Protocol for a pluggable vector storage backend."""

    async def initialize(self) -> None:
        """Prepare the backend (connect, create collections/tables, pin model)."""
        ...

    async def close(self) -> None:
        """Release underlying resources."""
        ...

    async def upsert_memory(self, memory: Memory, embedding: list[float]) -> None:
        """Insert or update a single memory + embedding."""
        ...

    async def upsert_memories_batch(
        self, memories: list[Memory], embeddings: list[list[float]]
    ) -> None:
        """Batch insert/update memories with parallel embeddings list."""
        ...

    async def search(
        self,
        query_embedding: list[float],
        session_config: SessionConfig | None = None,
        limit: int = 10,
        user_id: str = "",
    ) -> list[dict]:
        """Top-k nearest-neighbour search. Returns ``[{id, score, payload}, ...]``."""
        ...

    async def delete_memory(self, memory_id: str) -> None:
        """Delete the vector + payload for the given memory id."""
        ...

    async def get_collection_info(self) -> dict:
        """Return a dict with ``indexed_vectors_count``, ``points_count``, ``status``."""
        ...
