"""Qdrant vector store — async, local file-based or remote server."""

from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient, models

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.exceptions import StorageError
from memgentic.models import Memory, SessionConfig

logger = structlog.get_logger()


class VectorStore:
    """Qdrant-backed vector store for semantic memory retrieval.

    Supports two modes:
    - LOCAL: File-based Qdrant (no server required, zero-config)
    - QDRANT: Remote Qdrant server (Docker or Qdrant Cloud)

    All operations are truly async via AsyncQdrantClient.
    """

    def __init__(self, settings: MemgenticSettings) -> None:
        self._settings = settings
        self._client: AsyncQdrantClient | None = None

    async def initialize(self) -> None:
        """Initialize async Qdrant client and create collection if needed.

        When storage_backend is LOCAL, first probes the Qdrant server URL.
        If a server is already running (e.g. via Docker), it is used
        transparently — avoiding file-lock conflicts between CLI and API.
        """
        if self._settings.storage_backend == StorageBackend.LOCAL:
            # Auto-detect: prefer a running Qdrant server over local file mode
            if await self._try_server_connection():
                logger.info(
                    "vector_store.auto_detected_server",
                    url=self._settings.qdrant_url,
                    hint="Qdrant server found — using server mode instead of local files",
                )
                self._client = AsyncQdrantClient(url=self._settings.qdrant_url)
            else:
                path = self._settings.qdrant_local_path
                path.mkdir(parents=True, exist_ok=True)
                self._client = AsyncQdrantClient(path=str(path))
                logger.info("vector_store.initialized", mode="local", path=str(path))
        else:
            self._client = AsyncQdrantClient(
                url=self._settings.qdrant_url,
                api_key=self._settings.qdrant_api_key,
            )
            logger.info("vector_store.initialized", mode="remote", url=self._settings.qdrant_url)

        # Create collection if it doesn't exist
        collections = await self._client.get_collections()
        collection_names = [c.name for c in collections.collections]

        if self._settings.collection_name not in collection_names:
            await self._client.create_collection(
                collection_name=self._settings.collection_name,
                vectors_config=models.VectorParams(
                    size=self._settings.embedding_dimensions,
                    distance=models.Distance.COSINE,
                ),
            )
            # Create payload indices for filtering (no-op in local mode)
            for field_name in ["platform", "content_type", "status", "user_id"]:
                await self._client.create_payload_index(
                    collection_name=self._settings.collection_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            await self._client.create_payload_index(
                collection_name=self._settings.collection_name,
                field_name="confidence",
                field_schema=models.PayloadSchemaType.FLOAT,
            )
            logger.info(
                "vector_store.collection_created",
                name=self._settings.collection_name,
                dimensions=self._settings.embedding_dimensions,
            )

    async def close(self) -> None:
        """Close Qdrant client."""
        if self._client:
            await self._client.close()
            self._client = None

    async def upsert_memory(self, memory: Memory, embedding: list[float]) -> None:
        """Store a memory with its embedding vector."""
        if not self._client:
            raise StorageError("VectorStore not initialized — call initialize() first")

        await self._client.upsert(
            collection_name=self._settings.collection_name,
            points=[
                models.PointStruct(
                    id=memory.id,
                    vector=embedding,
                    payload=self._memory_to_payload(memory),
                )
            ],
        )

    async def upsert_memories_batch(
        self, memories: list[Memory], embeddings: list[list[float]]
    ) -> None:
        """Batch upsert memories with embeddings."""
        if not self._client:
            raise StorageError("VectorStore not initialized — call initialize() first")
        if len(memories) != len(embeddings):
            raise StorageError(
                f"Memories/embeddings count mismatch: {len(memories)} vs {len(embeddings)}"
            )

        points = [
            models.PointStruct(
                id=memory.id,
                vector=embedding,
                payload=self._memory_to_payload(memory),
            )
            for memory, embedding in zip(memories, embeddings, strict=False)
        ]
        await self._client.upsert(
            collection_name=self._settings.collection_name,
            points=points,
        )
        logger.info("vector_store.batch_upserted", count=len(points))

    async def search(
        self,
        query_embedding: list[float],
        session_config: SessionConfig | None = None,
        limit: int = 10,
        user_id: str = "",
    ) -> list[dict]:
        """Semantic search with optional source filtering.

        Returns list of dicts with 'id', 'score', and 'payload'.
        """
        if not self._client:
            raise StorageError("VectorStore not initialized — call initialize() first")

        qdrant_filter = self._build_filter(session_config, user_id=user_id)

        results = await self._client.query_points(
            collection_name=self._settings.collection_name,
            query=query_embedding,
            query_filter=qdrant_filter,
            limit=limit,
        )

        return [
            {
                "id": str(point.id),
                "score": point.score,
                "payload": point.payload,
            }
            for point in results.points
        ]

    async def delete_memory(self, memory_id: str) -> None:
        """Delete a memory vector."""
        if not self._client:
            raise StorageError("VectorStore not initialized")
        await self._client.delete(
            collection_name=self._settings.collection_name,
            points_selector=models.PointIdsList(points=[memory_id]),
        )

    async def get_collection_info(self) -> dict:
        """Get collection statistics."""
        if not self._client:
            raise StorageError("VectorStore not initialized")
        info = await self._client.get_collection(self._settings.collection_name)
        return {
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "status": info.status.value if info.status else "unknown",
        }

    # --- Private helpers ---

    async def _try_server_connection(self) -> bool:
        """Probe the Qdrant server URL; return True if it responds healthy."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._settings.qdrant_url}/healthz")
                return resp.status_code == 200  # noqa: TRY300
        except Exception:
            return False

    @staticmethod
    def _memory_to_payload(memory: Memory) -> dict:
        """Convert memory to Qdrant payload for filtering."""
        return {
            "content": memory.content,
            "content_type": memory.content_type.value,
            "platform": memory.source.platform.value,
            "platform_version": memory.source.platform_version,
            "session_id": memory.source.session_id,
            "session_title": memory.source.session_title,
            "topics": memory.topics,
            "entities": memory.entities,
            "confidence": memory.confidence,
            "status": memory.status.value,
            "created_at": memory.created_at.isoformat(),
            "user_id": memory.user_id,
        }

    @staticmethod
    def _build_filter(config: SessionConfig | None, user_id: str = "") -> models.Filter | None:
        """Build Qdrant filter from session config."""
        conditions: list[models.Condition] = []

        # Always filter active memories
        conditions.append(
            models.FieldCondition(
                key="status",
                match=models.MatchValue(value="active"),
            )
        )

        # Filter by user_id when provided
        if user_id:
            conditions.append(
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id),
                )
            )

        if not config:
            return models.Filter(must=conditions) if conditions else None

        if config.include_sources:
            conditions.append(
                models.FieldCondition(
                    key="platform",
                    match=models.MatchAny(any=[s.value for s in config.include_sources]),
                )
            )

        if config.exclude_sources:
            for source in config.exclude_sources:
                conditions.append(
                    models.FieldCondition(
                        key="platform",
                        match=models.MatchExcept(**{"except": [source.value]}),
                    )
                )

        if config.include_content_types:
            conditions.append(
                models.FieldCondition(
                    key="content_type",
                    match=models.MatchAny(any=[ct.value for ct in config.include_content_types]),
                )
            )

        if config.min_confidence > 0:
            conditions.append(
                models.FieldCondition(
                    key="confidence",
                    range=models.Range(gte=config.min_confidence),
                )
            )

        return models.Filter(must=conditions) if conditions else None
