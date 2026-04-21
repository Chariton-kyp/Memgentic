"""Ingestion pipeline — processes conversations into source-aware memories."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import time
from typing import Any

import structlog

from memgentic.config import MemgenticSettings
from memgentic.exceptions import EmbeddingError
from memgentic.models import (
    CAPTURE_PROFILES,
    CaptureMethod,
    CaptureProfile,
    ContentType,
    ConversationChunk,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.observability import record_counter, record_histogram, trace_span
from memgentic.processing.embedder import Embedder
from memgentic.processing.heuristics import is_noise
from memgentic.processing.scrubber import scrub_text
from memgentic.processing.utils import text_overlap
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

# Intelligence imports — available when [intelligence] extras are installed
try:
    from memgentic.graph.knowledge import KnowledgeGraph
    from memgentic.processing.corroboration import check_corroboration
    from memgentic.processing.intelligence import build_intelligence_graph

    HAS_INTELLIGENCE = True
except ImportError:
    HAS_INTELLIGENCE = False
    KnowledgeGraph = None  # type: ignore[assignment,misc]
    build_intelligence_graph = None  # type: ignore[assignment]
    check_corroboration = None  # type: ignore[assignment]

logger = structlog.get_logger()


def _resolve_capture_profile(
    override: CaptureProfile | None,
    settings: MemgenticSettings,
) -> CaptureProfile:
    """Pick the effective capture profile for an ingestion call.

    Falls back to the configured default when no explicit override is given.
    Unknown values are replaced with ``"enriched"`` to keep legacy callers safe.
    """
    candidate = override if override is not None else settings.default_capture_profile
    if candidate not in CAPTURE_PROFILES:
        logger.warning(
            "pipeline.invalid_capture_profile",
            value=candidate,
            fallback="enriched",
        )
        return "enriched"
    return candidate


class IngestionPipeline:
    """Processes raw conversations into stored, searchable memories.

    Pipeline steps:
    1. Deduplicate (skip already-processed files)
    2. Chunk conversation by topic/turn
    3. Extract metadata (topics, entities, decisions)
    4. Generate embeddings
    5. Store in SQLite (metadata) + Qdrant (vectors)
    """

    def __init__(
        self,
        settings: MemgenticSettings,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        embedder: Embedder,
        llm_client: Any | None = None,
        graph: Any | None = None,
    ) -> None:
        self._settings = settings
        self._metadata = metadata_store
        self._vectors = vector_store
        self._embedder = embedder
        self._llm_client = llm_client
        self._graph = graph

    @property
    def llm_client(self) -> Any | None:
        """The LLM client used for classification/extraction (if configured)."""
        return self._llm_client

    async def ingest_conversation(
        self,
        chunks: list[ConversationChunk],
        platform: Platform,
        session_id: str | None = None,
        session_title: str | None = None,
        capture_method: CaptureMethod = CaptureMethod.AUTO_DAEMON,
        file_path: str | None = None,
        platform_version: str | None = None,
        user_id: str = "",
        capture_profile: CaptureProfile | None = None,
    ) -> list[Memory]:
        """Ingest a parsed conversation into Memgentic.

        Args:
            chunks: Pre-processed conversation chunks (from an adapter).
            platform: Source platform.
            session_id: Original session/conversation ID.
            session_title: Conversation title.
            capture_method: How this was captured.
            file_path: Source file path (for deduplication).
            platform_version: Model/tool version.
            capture_profile: Override the configured default capture profile
                for this ingestion call. One of ``raw`` / ``enriched`` / ``dual``.

        Returns:
            List of created Memory objects.
        """
        profile = _resolve_capture_profile(capture_profile, self._settings)
        with trace_span(
            "pipeline.ingest",
            chunks=len(chunks),
            platform=platform.value,
            capture_profile=profile,
        ):
            _ingest_start = time.perf_counter()
            result = await self._ingest_conversation_impl(
                chunks=chunks,
                platform=platform,
                session_id=session_id,
                session_title=session_title,
                capture_method=capture_method,
                file_path=file_path,
                platform_version=platform_version,
                user_id=user_id,
                capture_profile=profile,
            )
            record_counter(
                "memgentic.memories.ingested",
                value=len(result),
                platform=platform.value,
            )
            record_histogram(
                "memgentic.pipeline.duration_seconds",
                time.perf_counter() - _ingest_start,
                platform=platform.value,
            )
            return result

    async def _ingest_conversation_impl(
        self,
        chunks: list[ConversationChunk],
        platform: Platform,
        session_id: str | None = None,
        session_title: str | None = None,
        capture_method: CaptureMethod = CaptureMethod.AUTO_DAEMON,
        file_path: str | None = None,
        platform_version: str | None = None,
        user_id: str = "",
        capture_profile: CaptureProfile = "enriched",
    ) -> list[Memory]:
        # Step 1: Deduplication check — compute hash ONCE and reuse
        file_hash: str | None = None
        if file_path:
            file_hash = await self._compute_file_hash(file_path)
            if await self._metadata.is_file_processed(file_path, file_hash):
                logger.info(
                    "pipeline.skip_duplicate",
                    file=file_path,
                    platform=platform.value,
                )
                return []

        # Step 2: Create Memory objects with full source metadata
        source = SourceMetadata(
            platform=platform,
            platform_version=platform_version,
            session_id=session_id,
            session_title=session_title,
            capture_method=capture_method,
            file_path=file_path,
        )

        # Raw-profile memories store verbatim content with no LLM-derived
        # metadata. They get a neutral importance so downstream ranking falls
        # back to pure vector + recency scoring.
        if capture_profile == "raw":
            memories = [
                Memory(
                    content=chunk.content,
                    content_type=chunk.content_type,
                    source=source,
                    topics=[],
                    entities=[],
                    confidence=chunk.confidence,
                    user_id=user_id,
                    importance_score=0.5,
                    capture_profile="raw",
                )
                for chunk in chunks
                if chunk.content.strip()  # Skip empty chunks
            ]
        else:
            # enriched / dual both start with enriched rows; dual spawns raw
            # siblings after the enriched path completes.
            memories = [
                Memory(
                    content=chunk.content,
                    content_type=chunk.content_type,
                    source=source,
                    topics=chunk.topics,
                    entities=chunk.entities,
                    confidence=chunk.confidence,
                    user_id=user_id,
                    capture_profile=capture_profile,
                )
                for chunk in chunks
                if chunk.content.strip()  # Skip empty chunks
            ]

        if not memories:
            logger.info("pipeline.no_memories", file=file_path)
            return []

        # Step 2b: Credential scrubbing — redact secrets before storage/LLM
        if self._settings.enable_credential_scrubbing:
            total_redacted = 0
            for memory in memories:
                result = scrub_text(memory.content)
                if result.redaction_count > 0:
                    memory.content = result.text
                    total_redacted += result.redaction_count
            if total_redacted:
                logger.info("pipeline.credentials_scrubbed", count=total_redacted)

        # Step 2b-2: Drop noise chunks (pleasantries, tool dumps, stack traces)
        before_noise = len(memories)
        memories = [m for m in memories if not is_noise(m.content)]
        chunks = [c for c in chunks if not is_noise(c.content)]
        if before_noise != len(memories):
            logger.info(
                "pipeline.noise_filtered",
                dropped=before_noise - len(memories),
                kept=len(memories),
            )
        if not memories:
            logger.info("pipeline.no_memories_after_noise", file=file_path)
            return []

        # Step 2c: Run intelligence pipeline (requires intelligence extras).
        # Raw-profile ingestion deliberately bypasses LLM classification /
        # extraction so the content is stored verbatim with no LLM-derived
        # metadata — this is the guarantee raw mode advertises.
        if (
            capture_profile != "raw"
            and HAS_INTELLIGENCE
            and self._llm_client
            and self._llm_client.available
        ):
            try:
                intel_graph = build_intelligence_graph(
                    enable_distillation=getattr(self._settings, "enable_fact_distillation", True)
                )
                intel_state: dict[str, Any] = {
                    "chunks": [
                        {
                            "content": c.content,
                            "content_type": c.content_type.value,
                            "confidence": c.confidence,
                            "topics": c.topics,
                        }
                        for c in chunks
                    ],
                    "llm_client": self._llm_client,
                    "errors": [],
                }
                intel_result = await intel_graph.ainvoke(intel_state)  # type: ignore[arg-type]

                # Apply classification results (content_type, confidence) to memories
                classified = intel_result.get("classified_chunks", [])
                for memory, classified_chunk in zip(memories, classified, strict=False):
                    ct_value = classified_chunk.get("content_type")
                    if ct_value:
                        with contextlib.suppress(ValueError):
                            memory.content_type = ContentType(ct_value)
                    conf = classified_chunk.get("confidence")
                    if conf is not None:
                        memory.confidence = conf

                # Apply intelligence results back to chunks
                if intel_result.get("all_topics"):
                    for chunk in chunks:
                        chunk.topics = list(set(chunk.topics + intel_result["all_topics"]))
                if intel_result.get("all_entities"):
                    for chunk in chunks:
                        chunk.entities = list(
                            set(chunk.entities + intel_result.get("all_entities", []))
                        )
                # Re-apply enriched topics/entities to memories
                for memory, chunk in zip(memories, chunks, strict=False):
                    memory.topics = chunk.topics
                    memory.entities = chunk.entities

                # Apply LLM summary to session title if available
                summary = intel_result.get("summary", "")
                if summary and not source.session_title:
                    source.session_title = summary[:500]
                    for memory in memories:
                        memory.source = source

                if intel_result.get("errors"):
                    logger.warning(
                        "pipeline.intelligence_warnings",
                        errors=intel_result["errors"],
                    )
            except Exception as exc:
                logger.warning("pipeline.intelligence_failed", error=str(exc))
        elif capture_profile == "raw":
            logger.info(
                "pipeline.raw_profile",
                msg="Raw capture profile — skipping LLM classification/extraction.",
                count=len(memories),
            )
        else:
            if not HAS_INTELLIGENCE:
                logger.info(
                    "pipeline.no_intelligence_package",
                    msg="Intelligence extras not installed. Using heuristic classification only. "
                    "Install with: pip install mneme-core[intelligence]",
                )
            else:
                logger.info(
                    "pipeline.intelligence_heuristic_only",
                    msg="No LLM provider configured. Set GOOGLE_API_KEY for better classification.",
                )

        # Step 3: Generate embeddings
        texts = [m.content for m in memories]
        logger.info("pipeline.embedding", count=len(texts), platform=platform.value)

        t0 = time.perf_counter()
        try:
            embeddings = await self._embedder.embed_batch(texts)
        except (EmbeddingError, Exception) as exc:
            logger.error(
                "pipeline.embedding_failed",
                error=str(exc),
                count=len(texts),
                platform=platform.value,
            )
            return []
        embed_elapsed = time.perf_counter() - t0

        # Step 3b: Corroboration — check if similar memories exist from other platforms.
        # Raw-profile rows bypass corroboration so they stay verbatim-only.
        if capture_profile != "raw" and HAS_INTELLIGENCE and self._settings.enable_corroboration:
            for memory, embedding in zip(memories, embeddings, strict=False):
                await check_corroboration(
                    memory, embedding, self._vectors, self._metadata, self._settings
                )

        # Step 3c: Write-time dedup — skip near-duplicates already in the store
        if self._settings.enable_write_time_dedup:
            filtered_memories: list[Memory] = []
            filtered_embeddings: list[list[float]] = []
            skipped = 0
            for memory, embedding in zip(memories, embeddings, strict=False):
                is_duplicate = False
                try:
                    similar = await self._vectors.search(embedding, limit=3)
                except Exception:
                    similar = []
                if not isinstance(similar, list):
                    similar = []
                for match in similar:
                    if not isinstance(match, dict):
                        continue
                    if match.get("score", 0) > 0.90:
                        match_content = (match.get("payload") or {}).get("content", "")
                        overlap = text_overlap(memory.content, match_content)
                        if overlap > 0.7:
                            logger.info(
                                "pipeline.dedup_skip",
                                memory_id=memory.id,
                                match_score=match.get("score"),
                                overlap=round(overlap, 3),
                            )
                            is_duplicate = True
                            skipped += 1
                            break
                if not is_duplicate:
                    filtered_memories.append(memory)
                    filtered_embeddings.append(embedding)
            memories = filtered_memories
            embeddings = filtered_embeddings
            if skipped:
                logger.info("pipeline.dedup_summary", skipped=skipped, kept=len(memories))
            if not memories:
                logger.info("pipeline.no_memories_after_dedup", file=file_path)
                return []

        # Step 4: Store in both stores
        t1 = time.perf_counter()
        await self._metadata.save_memories_batch(memories)
        await self._vectors.upsert_memories_batch(memories, embeddings)
        storage_elapsed = time.perf_counter() - t1

        # Step 4b: Update knowledge graph
        if self._graph:
            for memory in memories:
                if memory.topics or memory.entities:
                    await self._graph.add_memory(memory.id, memory.topics, memory.entities)

        # Step 4c: Contradiction detection — check new memories against existing ones.
        # Skipped for raw-profile writes (no LLM allowed).
        if (
            capture_profile != "raw"
            and HAS_INTELLIGENCE
            and self._llm_client
            and self._llm_client.available
        ):
            await self._detect_contradictions(memories)

        # Step 4c-2: Chronograph triple extraction — LLM proposes bitemporal
        # subject-predicate-object triples from enriched memories. Gated on
        # ``MEMGENTIC_EXTRACT_TRIPLES=1`` during the initial rollout so the
        # default ingestion path is unchanged; raw memories still bypass it.
        if (
            capture_profile != "raw"
            and HAS_INTELLIGENCE
            and self._llm_client
            and self._llm_client.available
            and os.getenv("MEMGENTIC_EXTRACT_TRIPLES") == "1"
        ):
            await self._extract_chronograph_triples(memories)

        # Step 4d: Dual-profile sibling — for every enriched memory just stored,
        # write a matching raw sibling containing the verbatim chunk text, no
        # topics/entities, importance 0.5. Pair them both ways via
        # ``dual_sibling_id`` so the dashboard can collapse the pair to one row.
        if capture_profile == "dual" and memories:
            raw_siblings: list[Memory] = []
            raw_texts: list[str] = []
            original_chunks = [c for c in chunks if c.content.strip()]
            for enriched_mem, orig_chunk in zip(memories, original_chunks, strict=False):
                raw_sibling = Memory(
                    content=orig_chunk.content,
                    content_type=orig_chunk.content_type,
                    source=enriched_mem.source,
                    topics=[],
                    entities=[],
                    confidence=orig_chunk.confidence,
                    user_id=user_id,
                    importance_score=0.5,
                    capture_profile="dual",
                    dual_sibling_id=enriched_mem.id,
                )
                raw_siblings.append(raw_sibling)
                raw_texts.append(orig_chunk.content)

            if raw_siblings:
                try:
                    raw_embeddings = await self._embedder.embed_batch(raw_texts)
                except (EmbeddingError, Exception) as exc:
                    logger.warning(
                        "pipeline.dual_sibling_embedding_failed",
                        error=str(exc),
                        count=len(raw_texts),
                    )
                    raw_embeddings = []

                if raw_embeddings:
                    await self._metadata.save_memories_batch(raw_siblings)
                    await self._vectors.upsert_memories_batch(raw_siblings, raw_embeddings)
                    # Patch enriched rows so both sides of the pair reference each other.
                    for enriched_mem, raw_sibling in zip(memories, raw_siblings, strict=False):
                        enriched_mem.dual_sibling_id = raw_sibling.id
                        await self._metadata.update_dual_sibling(enriched_mem.id, raw_sibling.id)
                    logger.info(
                        "pipeline.dual_siblings_stored",
                        count=len(raw_siblings),
                    )
                    memories = memories + raw_siblings

        # Step 5: Mark file as processed — reuse the hash computed in Step 1
        if file_path and file_hash is not None:
            await self._metadata.mark_file_processed(
                file_path=file_path,
                file_hash=file_hash,
                platform=platform.value,
                memory_count=len(memories),
            )

        logger.info(
            "pipeline.ingested",
            memories=len(memories),
            platform=platform.value,
            session=session_id,
            embed_ms=round(embed_elapsed * 1000, 1),
            storage_ms=round(storage_elapsed * 1000, 1),
        )

        # Emit events for each created memory
        await self._emit_memory_created_events(memories)

        return memories

    async def ingest_single(
        self,
        content: str,
        content_type: ContentType = ContentType.FACT,
        platform: Platform = Platform.UNKNOWN,
        topics: list[str] | None = None,
        entities: list[str] | None = None,
        user_id: str = "",
        capture_method: CaptureMethod = CaptureMethod.MCP_TOOL,
        capture_profile: CaptureProfile | None = None,
    ) -> Memory:
        """Quick-ingest a single memory (e.g., from MCP 'remember' tool).

        Respects ``capture_profile``: raw drops supplied topics/entities and
        uses a neutral importance; dual spawns an extra raw sibling linked via
        ``dual_sibling_id``.
        """
        profile = _resolve_capture_profile(capture_profile, self._settings)
        source = SourceMetadata(
            platform=platform,
            capture_method=capture_method,
        )

        # Scrub credentials before storage
        if self._settings.enable_credential_scrubbing:
            result = scrub_text(content)
            if result.redaction_count > 0:
                content = result.text
                logger.info("pipeline.single_credentials_scrubbed", count=result.redaction_count)

        if profile == "raw":
            memory = Memory(
                content=content,
                content_type=content_type,
                source=source,
                topics=[],
                entities=[],
                user_id=user_id,
                importance_score=0.5,
                capture_profile="raw",
            )
        else:
            memory = Memory(
                content=content,
                content_type=content_type,
                source=source,
                topics=topics or [],
                entities=entities or [],
                user_id=user_id,
                capture_profile=profile,
            )

        t0 = time.perf_counter()
        try:
            embedding = await self._embedder.embed(content)
        except (EmbeddingError, Exception) as exc:
            logger.error("pipeline.single_embedding_failed", error=str(exc))
            raise EmbeddingError(f"Failed to embed single memory: {exc}") from exc
        embed_elapsed = time.perf_counter() - t0

        t1 = time.perf_counter()
        await self._metadata.save_memory(memory)
        await self._vectors.upsert_memory(memory, embedding)
        storage_elapsed = time.perf_counter() - t1

        # Update knowledge graph
        if self._graph and (memory.topics or memory.entities):
            await self._graph.add_memory(memory.id, memory.topics, memory.entities)

        # Chronograph triple extraction (gated by MEMGENTIC_EXTRACT_TRIPLES=1)
        if (
            profile != "raw"
            and HAS_INTELLIGENCE
            and self._llm_client
            and self._llm_client.available
            and os.getenv("MEMGENTIC_EXTRACT_TRIPLES") == "1"
        ):
            await self._extract_chronograph_triples([memory])

        # Dual profile: spawn a verbatim raw sibling paired with this memory.
        if profile == "dual":
            raw_sibling = Memory(
                content=content,
                content_type=content_type,
                source=source,
                topics=[],
                entities=[],
                user_id=user_id,
                importance_score=0.5,
                capture_profile="dual",
                dual_sibling_id=memory.id,
            )
            try:
                raw_embedding = await self._embedder.embed(content)
            except (EmbeddingError, Exception) as exc:
                logger.warning("pipeline.single_dual_sibling_embedding_failed", error=str(exc))
            else:
                await self._metadata.save_memory(raw_sibling)
                await self._vectors.upsert_memory(raw_sibling, raw_embedding)
                memory.dual_sibling_id = raw_sibling.id
                await self._metadata.update_dual_sibling(memory.id, raw_sibling.id)
                await self._emit_memory_created_events([raw_sibling])

        logger.info(
            "pipeline.single_ingested",
            id=memory.id,
            type=content_type.value,
            capture_profile=profile,
            embed_ms=round(embed_elapsed * 1000, 1),
            storage_ms=round(storage_elapsed * 1000, 1),
        )

        # Emit event for the created memory
        await self._emit_memory_created_events([memory])

        return memory

    async def _detect_contradictions(self, memories: list[Memory]) -> None:
        """Check new memories against existing similar memories for contradictions.

        When a contradiction is detected (high semantic similarity but low text overlap),
        the older memory is marked as superseded.
        """
        for memory in memories:
            try:
                embedding = await self._embedder.embed(memory.content)
                results = await self._vectors.search(embedding, limit=5)
            except Exception:
                continue

            for result in results:
                other_id = result["id"]
                if other_id == memory.id:
                    continue

                score = result.get("score", 0)
                if score < 0.85:
                    continue

                other = await self._metadata.get_memory(other_id)
                if not other or other.status != MemoryStatus.ACTIVE:
                    continue

                # High similarity + low text overlap = contradiction
                overlap = text_overlap(memory.content, other.content)
                if overlap < 0.3:
                    # Mark the older memory as superseded
                    await self._metadata.update_memory_status(
                        other.id, MemoryStatus.SUPERSEDED.value
                    )
                    memory.supersedes = list(set(memory.supersedes + [other.id]))
                    await self._metadata.save_memory(memory)

                    logger.info(
                        "pipeline.contradiction_detected",
                        new_memory=memory.id[:8],
                        superseded_memory=other.id[:8],
                        similarity=round(score, 3),
                        text_overlap=round(overlap, 3),
                    )

    async def _extract_chronograph_triples(self, memories: list[Memory]) -> None:
        """Propose Chronograph triples for newly-stored memories.

        Any failure is logged and swallowed — triple extraction is best-effort
        and must never block the ingestion pipeline. Triples land with
        ``status="proposed"`` so the dashboard validation queue gates them.
        """
        try:
            from memgentic.graph import get_chronograph
            from memgentic.graph.extractor import extract_triples, store_proposed
        except ImportError as exc:  # pragma: no cover — intelligence extras required
            logger.debug("pipeline.chronograph_unavailable", error=str(exc))
            return

        try:
            chronograph = await get_chronograph()
        except Exception as exc:
            logger.warning("pipeline.chronograph_init_failed", error=str(exc))
            return

        for memory in memories:
            try:
                proposed = await extract_triples(memory, self._llm_client, chronograph)
                if proposed:
                    await store_proposed(proposed, chronograph)
                    logger.info(
                        "pipeline.triples_proposed",
                        memory_id=memory.id[:8],
                        count=len(proposed),
                    )
            except Exception as exc:
                logger.warning(
                    "pipeline.triple_extraction_failed",
                    memory_id=memory.id[:8],
                    error=str(exc),
                )

    @staticmethod
    async def _compute_file_hash(file_path: str) -> str:
        """Compute SHA-256 hash of a file for deduplication.

        Offloads blocking file I/O to a thread to avoid stalling the event loop.
        """

        def _read_and_hash() -> str:
            hasher = hashlib.sha256()
            try:
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        hasher.update(chunk)
                return hasher.hexdigest()
            except FileNotFoundError:
                return hashlib.sha256(file_path.encode()).hexdigest()

        return await asyncio.to_thread(_read_and_hash)

    async def _emit_memory_created_events(self, memories: list[Memory]) -> None:
        """Emit ``MEMORY_CREATED`` events via the global event bus.

        Each event carries the memory's ID, content type, platform, topics,
        and a 150-character content preview. Subscribers (e.g., the MCP
        server) can react to these events for real-time notifications.

        Args:
            memories: List of newly created Memory objects to announce.
        """
        from memgentic.events import EventType, MemgenticEvent, event_bus

        for memory in memories:
            event = MemgenticEvent(
                type=EventType.MEMORY_CREATED,
                data={
                    "id": memory.id,
                    "content_type": memory.content_type.value,
                    "platform": memory.source.platform.value,
                    "topics": memory.topics,
                    "content_preview": memory.content[:150],
                },
            )
            await event_bus.emit(event)
