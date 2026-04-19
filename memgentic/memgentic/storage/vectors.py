"""Vector store façade — Qdrant inline, sqlite-vec delegated.

Qdrant (``LOCAL`` file mode and ``QDRANT`` server mode) remains the default
and its logic lives inline here. ``SQLITE_VEC`` is an opt-in backend in
:mod:`memgentic.storage.backends.sqlite_vec`; when selected the façade
instantiates it and forwards every call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import structlog
from qdrant_client import AsyncQdrantClient, models

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.exceptions import EmbeddingMismatchError, StorageError
from memgentic.models import Memory, SessionConfig
from memgentic.storage.backends.base import VectorBackend

if TYPE_CHECKING:
    from memgentic.storage.metadata import MetadataStore

logger = structlog.get_logger()


def _format_mismatch_message(
    *,
    collection: str,
    pinned_model: str | None,
    pinned_dim: int,
    current_model: str,
    current_dim: int,
    actual_dim: int,
) -> str:
    """Produce an actionable error message for embedding-model / dimension mismatch.

    Mixing vectors from different embedding models yields nonsense similarity
    scores, so we refuse to start. The message is the primary UX here — it has
    to tell the user exactly what's wrong and exactly how to fix it.
    """
    lines = [
        "",
        "Embedding model / dimension mismatch — semantic search would be corrupted.",
        "",
        f"  Collection        : {collection}",
        f"  Pinned model      : {pinned_model or '(unknown — pre-v0.5.0 collection)'}",
        f"  Pinned dimensions : {pinned_dim}",
        f"  Collection on disk: {actual_dim} dimensions",
        f"  Now configured    : {current_model} ({current_dim} dimensions)",
        "",
        "This collection was built with a different embedding model than what's",
        "currently configured. Vectors produced by different models are NOT",
        "comparable, so Memgentic refuses to proceed rather than silently",
        "return meaningless results.",
        "",
        "To resolve, pick ONE:",
        "",
        "  (A) Keep your existing memories — revert the embedding model:",
        f"        # MEMGENTIC_EMBEDDING_MODEL='{pinned_model or 'qwen3-embedding:0.6b'}'",
        f"        # MEMGENTIC_EMBEDDING_DIMENSIONS={pinned_dim}",
        "",
        "  (B) Rebuild the collection with the new model (re-embeds every",
        "      memory — progress bar, resumable):",
        "        memgentic re-embed",
        "",
        "  (C) Start fresh (destroys existing memories):",
        "        memgentic doctor   # to confirm current config",
        "        # then manually remove ~/.memgentic/data/ and run `memgentic init`",
        "",
    ]
    return "\n".join(lines)


class VectorStore:
    """Vector store façade for semantic memory retrieval.

    Supports three modes:
    - LOCAL: File-based Qdrant (no server required, zero-config)
    - QDRANT: Remote Qdrant server (Docker or Qdrant Cloud)
    - SQLITE_VEC: sqlite-vec extension in the existing SQLite DB (opt-in,
      multi-process safe, no extra binary)

    All operations are truly async.
    """

    def __init__(self, settings: MemgenticSettings) -> None:
        self._settings = settings
        self._client: AsyncQdrantClient | None = None
        self._backend: VectorBackend | None = None

    async def initialize(self, metadata_store: MetadataStore | None = None) -> None:
        """Initialize backend — Qdrant client + safety-pin, or sqlite-vec.

        When storage_backend is LOCAL, first probes the Qdrant server URL.
        If a server is already running (e.g. via Docker), it is used
        transparently — avoiding file-lock conflicts between CLI and API.
        """
        if self._settings.storage_backend == StorageBackend.SQLITE_VEC:
            from memgentic.storage.backends.sqlite_vec import SqliteVecBackend

            self._backend = SqliteVecBackend(self._settings)
            await self._backend.initialize()
            self._warn_if_legacy_qdrant_data()
            return

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

        current_model = self._settings.embedding_model
        current_dim = self._settings.embedding_dimensions

        if self._settings.collection_name not in collection_names:
            await self._client.create_collection(
                collection_name=self._settings.collection_name,
                vectors_config=models.VectorParams(
                    size=current_dim,
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
                dimensions=current_dim,
            )
            # Pin the embedding model+dim that built this collection. Used by
            # future initialize() calls to detect silent mismatches.
            if metadata_store is not None:
                await metadata_store.set_embedding_config(
                    model=current_model, dimensions=current_dim
                )
        elif metadata_store is not None:
            await self._verify_embedding_compatibility(metadata_store)

    async def _verify_embedding_compatibility(self, metadata_store: MetadataStore) -> None:
        """Compare the configured embedding model + dimensions against what was
        pinned when the collection was first created. Refuse to proceed on a
        mismatch rather than corrupting the semantic search with mixed vectors.
        """
        if self._client is None:
            return

        pinned = await metadata_store.get_embedding_config()
        current_model = self._settings.embedding_model
        current_dim = self._settings.embedding_dimensions

        # Always reconcile against the collection's actual vector size on-disk,
        # not just the pinned row — catches cases where the SQLite entry was
        # deleted but the collection wasn't rebuilt.
        info = await self._client.get_collection(self._settings.collection_name)
        vectors_config = info.config.params.vectors
        if vectors_config is None:
            # Collection exists with no vector config — shouldn't happen for
            # Memgentic-created collections; skip the check rather than crash.
            logger.warning(
                "vector_store.embedding_config.no_vector_config",
                collection=self._settings.collection_name,
            )
            return
        if isinstance(vectors_config, dict):
            # Named vectors are not a layout Memgentic uses, but guard anyway.
            first = next(iter(vectors_config.values()))
            actual_dim = first.size
        else:
            actual_dim = vectors_config.size

        if actual_dim != current_dim:
            raise EmbeddingMismatchError(
                _format_mismatch_message(
                    collection=self._settings.collection_name,
                    pinned_model=(pinned or {}).get("model"),
                    pinned_dim=int((pinned or {}).get("dimensions", actual_dim)),
                    current_model=current_model,
                    current_dim=current_dim,
                    actual_dim=actual_dim,
                )
            )

        if pinned is None:
            # Collection exists but no pinned record — likely upgraded from
            # an earlier Memgentic version. Backfill the pin with what we see
            # in the collection (dim) and the currently configured model.
            # This is the only path that trusts current_model implicitly.
            logger.warning(
                "vector_store.embedding_config.backfill",
                collection=self._settings.collection_name,
                model=current_model,
                dimensions=actual_dim,
                hint=(
                    "Existing collection had no pinned model. Assuming the "
                    "currently configured model was the one that built it. "
                    "If that's wrong, run `memgentic re-embed` to rebuild."
                ),
            )
            await metadata_store.set_embedding_config(model=current_model, dimensions=actual_dim)
            return

        if pinned["model"] != current_model:
            raise EmbeddingMismatchError(
                _format_mismatch_message(
                    collection=self._settings.collection_name,
                    pinned_model=pinned["model"],
                    pinned_dim=int(pinned["dimensions"]),
                    current_model=current_model,
                    current_dim=current_dim,
                    actual_dim=actual_dim,
                )
            )

        logger.debug(
            "vector_store.embedding_config.verified",
            model=current_model,
            dimensions=current_dim,
        )

    async def close(self) -> None:
        """Close the underlying backend."""
        if self._backend is not None:
            await self._backend.close()
            self._backend = None
            return
        if self._client:
            await self._client.close()
            self._client = None

    async def upsert_memory(self, memory: Memory, embedding: list[float]) -> None:
        """Store a memory with its embedding vector."""
        if self._backend is not None:
            await self._backend.upsert_memory(memory, embedding)
            return
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
        if self._backend is not None:
            await self._backend.upsert_memories_batch(memories, embeddings)
            return
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
        if self._backend is not None:
            return await self._backend.search(
                query_embedding, session_config=session_config, limit=limit, user_id=user_id
            )
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
        if self._backend is not None:
            await self._backend.delete_memory(memory_id)
            return
        if not self._client:
            raise StorageError("VectorStore not initialized")
        await self._client.delete(
            collection_name=self._settings.collection_name,
            points_selector=models.PointIdsList(points=[memory_id]),
        )

    async def all_points(self) -> AsyncIterator[tuple[str, list[float]]]:
        """Yield every (id, embedding) pair from the underlying backend.

        Used by ``memgentic migrate-storage`` to copy vectors between backends
        without re-embedding.
        """
        if self._backend is not None:
            async for point in self._backend.all_points():
                yield point
            return

        if not self._client:
            raise StorageError("VectorStore not initialized")

        # Qdrant scroll API: page through all points with_vectors=True
        offset = None
        while True:
            result, next_offset = await self._client.scroll(
                collection_name=self._settings.collection_name,
                limit=256,
                offset=offset,
                with_vectors=True,
            )
            for point in result:
                vec = point.vector
                if vec is None:
                    continue
                # Named vectors (dict) — Memgentic always uses unnamed vectors
                if isinstance(vec, dict):
                    vec = next(iter(vec.values()))
                # ``VectorStruct`` from qdrant-client is a union type; for our
                # unnamed-vector collections the runtime value is a sequence
                # of floats. Rebuild as a plain list so the generator matches
                # its declared AsyncIterator[tuple[str, list[float]]] type.
                yield str(point.id), [float(x) for x in vec]  # type: ignore[union-attr]
            if next_offset is None:
                break
            offset = next_offset

    async def get_collection_info(self) -> dict:
        """Get collection statistics."""
        if self._backend is not None:
            return await self._backend.get_collection_info()
        if not self._client:
            raise StorageError("VectorStore not initialized")
        info = await self._client.get_collection(self._settings.collection_name)
        return {
            "indexed_vectors_count": info.indexed_vectors_count,
            "points_count": info.points_count,
            "status": info.status.value if info.status else "unknown",
        }

    # --- Private helpers ---

    def _warn_if_legacy_qdrant_data(self) -> None:
        """Emit a one-time loud warning when an old Qdrant data directory is found.

        Triggered on first sqlite-vec start when:
          1. The legacy Qdrant local directory exists (``~/.memgentic/data/qdrant/``), AND
          2. The sqlite-vec DB file is freshly created (size below a small threshold),
             which implies no memories have been migrated yet.

        The warning tells users what to run — it never auto-migrates.
        """
        qdrant_dir = self._settings.qdrant_local_path
        sqlite_path = self._settings.sqlite_path

        if not qdrant_dir.exists():
            return

        # Heuristic: newly-created SQLite DB (schema only, no memories) is small.
        # A DB with even one memory will be larger than 100 KB.
        try:
            db_size = sqlite_path.stat().st_size if sqlite_path.exists() else 0
        except OSError:
            db_size = 0

        if db_size > 102_400:  # 100 KB
            # DB already has data — user is aware of the situation, stay silent.
            return

        logger.warning(
            "vector_store.legacy_qdrant_data_detected",
            qdrant_dir=str(qdrant_dir),
            hint=(
                "Existing Qdrant data found. Run `memgentic migrate-storage "
                "--from local --to sqlite_vec` to copy your memories."
            ),
        )
        import rich.console

        console = rich.console.Console(stderr=True)
        console.print(
            "\n[bold yellow]Memgentic[/bold yellow] — [yellow]data migration notice[/yellow]\n"
            "\n"
            f"  Existing Qdrant data found at: [cyan]{qdrant_dir}[/cyan]\n"
            "  The default storage backend is now [bold]sqlite-vec[/bold] (zero-config,\n"
            "  multi-process safe). Your previous memories are [bold]not[/bold] lost —\n"
            "  they just live in the old Qdrant store and won't appear in search yet.\n"
            "\n"
            "  To migrate, run:\n"
            "\n"
            "    [bold green]memgentic migrate-storage "
            "--from local --to sqlite_vec[/bold green]\n"
            "\n"
            "  To keep using Qdrant instead, set:\n"
            "\n"
            "    [bold]MEMGENTIC_STORAGE_BACKEND=local[/bold]\n"
        )

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
