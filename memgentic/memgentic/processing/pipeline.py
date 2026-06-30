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
from memgentic.processing._grounding import is_grounded
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


# Default hard cap on a single chunk's content length, used when no settings
# value is supplied. Beyond this we truncate rather than refuse — but truncation
# should be rare in practice because adapters filter tool-output dumps before
# reaching the pipeline. The effective cap is configurable via
# ``MemgenticSettings.max_memory_content_chars`` (default 64 KB); this constant
# is only the fallback for callers that don't pass one in.
_MAX_CHUNK_CONTENT_CHARS: int = 65_536
_TRUNCATION_MARKER: str = "\n\n…[truncated by Memgentic — original length {orig} chars]"

# Write-time dedup thresholds (shared by the conversation and single-memory
# paths). A candidate is treated as a near-duplicate only when BOTH a high
# vector score AND a high lexical overlap hold — deliberately conservative so a
# deliberately rephrased ``memgentic_remember`` (high cosine, lower word
# overlap) is never silently dropped; only true near-identical content is.
_WRITE_DEDUP_SCORE_THRESHOLD: float = 0.90
_WRITE_DEDUP_OVERLAP_THRESHOLD: float = 0.7


def _truncate_if_oversized(content: str, cap: int) -> str:
    """Return ``content`` truncated to ``cap`` chars (plus a marker) if needed."""
    if len(content) <= cap:
        return content
    return content[:cap] + _TRUNCATION_MARKER.format(orig=len(content))


def _distillation_is_worthless(distillation: Any, min_score: float) -> bool:
    """Decide whether the value gate should drop a chunk (W1 / RC2).

    Conservative by design: returns True ONLY when the distillation node
    explicitly judged the chunk worthless — ``is_valuable is False`` AND a
    numeric ``value_score`` below ``min_score``. When the signal is missing,
    None, or merely uncertain, returns False so real knowledge is never
    dropped on absent evidence.
    """
    if not isinstance(distillation, dict):
        return False
    if distillation.get("is_valuable") is not False:
        return False
    value_score = distillation.get("value_score")
    if not isinstance(value_score, (int, float)) or isinstance(value_score, bool):
        return False
    return value_score < min_score


def _enforce_chunk_size_cap(
    chunks: list[ConversationChunk],
    platform: Platform,
    cap: int = _MAX_CHUNK_CONTENT_CHARS,
) -> list[ConversationChunk]:
    """Truncate any chunk whose content exceeds ``cap`` characters.

    Returns a new list of chunks (does not mutate the originals). Logs
    one ``pipeline.chunk_truncated`` warning per oversized chunk so the
    operator can find which adapter / file produced it and tighten the
    upstream filter.
    """
    capped: list[ConversationChunk] = []
    for chunk in chunks:
        content = chunk.content
        if len(content) <= cap:
            capped.append(chunk)
            continue
        truncated = _truncate_if_oversized(content, cap)
        logger.warning(
            "pipeline.chunk_truncated",
            platform=platform.value,
            original_length=len(content),
            truncated_length=len(truncated),
            content_type=str(chunk.content_type),
        )
        capped.append(chunk.model_copy(update={"content": truncated}))
    return capped


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
        project: str | None = None,
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
            project: Friendly project key derived by the adapter from the
                originating working directory. Empty/None when unknown.

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
                project=project,
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
        project: str | None = None,
    ) -> list[Memory]:
        # Step 0: Defensive cap on absurd chunk sizes. A single Gemini CLI
        # turn that wraps a ``[Function Response: read_many_files]`` dump
        # was observed at 765 KB on Chariton's machine on 2026-05-04 —
        # adapter-level filters now drop these, but anything that slips
        # through (e.g. very long Claude Code thinking blocks, future
        # adapter regressions) gets truncated here so it never bloats
        # the embedder, the SQLite row, or the vector store.
        chunks = _enforce_chunk_size_cap(chunks, platform, self._settings.max_memory_content_chars)

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

        project_key = (project or "").strip().lower()

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
                    project=project_key,
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
                    project=project_key,
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
            # Scrub the chunk list too — it (not ``memories``) is what feeds the
            # LLM intelligence graph below (``intel_state`` is built from
            # ``chunk.content``). Without this, raw secrets reach the LLM
            # provider (cloud Gemini when GOOGLE_API_KEY is set).
            for chunk in chunks:
                cres = scrub_text(chunk.content)
                if cres.redaction_count > 0:
                    chunk.content = cres.text
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
                    # Persist the distilled atomic facts as the recall surface,
                    # but only when they are lexically grounded in the verbatim
                    # turn — a cheap guard against promoting a hallucinated fact
                    # to a top recall row. ``content`` stays the verbatim
                    # source-of-truth; this only fills the separate ``distilled``
                    # column (embedded/displayed later behind the flag).
                    distillation = classified_chunk.get("distillation")
                    facts = (distillation or {}).get("facts") or []
                    if facts:
                        joined = " ".join(f.strip() for f in facts if f.strip())
                        if joined and is_grounded(joined, memory.content):
                            memory.distilled = joined

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

                # Step 2c-2: Value gate (W1 / RC2). The distillation node
                # produced an is_valuable / value_score signal per chunk; drop
                # the memories it judged clearly worthless before we spend an
                # embedding on them. Conservative: only drops when the signal
                # is explicitly negative (see _distillation_is_worthless), never
                # when it is absent. memories and chunks are kept aligned so the
                # downstream dual-sibling path stays correct.
                if self._settings.enable_value_gate and classified:
                    min_score = self._settings.value_gate_min_score
                    kept_memories: list[Memory] = []
                    kept_chunks: list[ConversationChunk] = []
                    gate_dropped = 0
                    for memory, chunk, classified_chunk in zip(
                        memories, chunks, classified, strict=False
                    ):
                        distillation = (
                            classified_chunk.get("distillation")
                            if isinstance(classified_chunk, dict)
                            else None
                        )
                        if _distillation_is_worthless(distillation, min_score):
                            gate_dropped += 1
                            continue
                        kept_memories.append(memory)
                        kept_chunks.append(chunk)
                    if gate_dropped:
                        # Only commit the filtered lists when alignment held
                        # (zip truncates on length mismatch — never drop the
                        # tail of an unaligned list).
                        if len(memories) == len(chunks) == len(classified):
                            memories = kept_memories
                            chunks = kept_chunks
                            logger.info(
                                "pipeline.value_gate_dropped",
                                dropped=gate_dropped,
                                kept=len(memories),
                            )
                        else:
                            logger.warning(
                                "pipeline.value_gate_skipped_misaligned",
                                memories=len(memories),
                                chunks=len(chunks),
                                classified=len(classified),
                            )

                if intel_result.get("errors"):
                    logger.warning(
                        "pipeline.intelligence_warnings",
                        errors=intel_result["errors"],
                    )
            except Exception as exc:
                logger.warning("pipeline.intelligence_failed", error=str(exc))

        # Value gate may have emptied the batch — bail out cleanly.
        if not memories:
            logger.info("pipeline.no_memories_after_value_gate", file=file_path)
            return []
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
                    "Install with: pip install memgentic[intelligence]",
                )
            else:
                logger.info(
                    "pipeline.intelligence_heuristic_only",
                    msg="No LLM provider configured. Set GOOGLE_API_KEY for better classification.",
                )

        # Step 3: Generate embeddings. When the distilled recall surface is
        # enabled, embed the grounded distillation (falling back to verbatim
        # content for raw/legacy/ungrounded rows where distilled is None);
        # otherwise embed verbatim content exactly as before.
        if self._settings.enable_distilled_recall_surface:
            texts = [m.distilled or m.content for m in memories]
        else:
            texts = [m.content for m in memories]
        logger.info("pipeline.embedding", count=len(texts), platform=platform.value)

        t0 = time.perf_counter()
        try:
            embeddings = await self._embedder.embed_batch_documents(texts)
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
                dup_id = await self._find_write_time_duplicate(memory.content, embedding)
                if dup_id is not None:
                    logger.info("pipeline.dedup_skip", memory_id=memory.id, match=dup_id)
                    skipped += 1
                    continue
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
                    raw_embeddings = await self._embedder.embed_batch_documents(raw_texts)
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
        project: str | None = None,
    ) -> Memory:
        """Quick-ingest a single memory (e.g., from MCP 'remember' tool).

        Respects ``capture_profile``: raw drops supplied topics/entities and
        uses a neutral importance; dual spawns an extra raw sibling linked via
        ``dual_sibling_id``. ``project`` stamps the memory's project key so
        manual remembers are scoped to the current project/repository like
        auto-captured ones (empty string when unknown → global).
        """
        profile = _resolve_capture_profile(capture_profile, self._settings)
        project_key = (project or "").strip().lower()
        source = SourceMetadata(
            platform=platform,
            capture_method=capture_method,
        )

        # Cap absurdly long single memories (e.g. a pasted file dump) before
        # embedding/storage. Same policy as the conversation path.
        capped = _truncate_if_oversized(content, self._settings.max_memory_content_chars)
        if capped != content:
            logger.warning(
                "pipeline.single_truncated",
                original_length=len(content),
                truncated_length=len(capped),
            )
            content = capped

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
                project=project_key,
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
                project=project_key,
            )

        t0 = time.perf_counter()
        try:
            embedding = await self._embedder.embed_document(content)
        except (EmbeddingError, Exception) as exc:
            logger.error("pipeline.single_embedding_failed", error=str(exc))
            raise EmbeddingError(f"Failed to embed single memory: {exc}") from exc
        embed_elapsed = time.perf_counter() - t0

        # Write-time dedup (W4) — the ``memgentic_remember`` path used to insert
        # unconditionally, so re-saying the same fact created a duplicate every
        # time. Reuse the same conservative near-duplicate test as the
        # conversation path (high cosine AND high overlap). When a near-identical
        # memory already exists we return IT instead of writing a second copy —
        # the owner's deliberate (and merely rephrased) saves still go through
        # because the overlap gate keeps them distinct.
        #
        # Protection promotion: when the incoming call is MORE protected than the
        # surviving duplicate (e.g. an mcp_tool remember that matches an
        # auto_daemon row), we promote the survivor so it inherits the higher
        # protection class — preventing the owner's deliberate save from silently
        # leaving an unprotected GC-eligible row as the sole copy.
        if self._settings.enable_write_time_dedup:
            dup_id = await self._find_write_time_duplicate(content, embedding)
            if dup_id is not None:
                existing = await self._metadata.get_memory(dup_id)
                if existing is not None:
                    incoming_is_mcp = capture_method == CaptureMethod.MCP_TOOL
                    incoming_is_pinned = memory.is_pinned
                    promote_method = (
                        incoming_is_mcp and existing.source.capture_method != CaptureMethod.MCP_TOOL
                    )
                    promote_pin = incoming_is_pinned and not existing.is_pinned
                    if promote_method or promote_pin:
                        updates: dict[str, Any] = {}
                        if promote_method:
                            updates["source"] = existing.source.model_copy(
                                update={"capture_method": CaptureMethod.MCP_TOOL}
                            )
                        if promote_pin:
                            updates["is_pinned"] = True
                        existing = existing.model_copy(update=updates)
                        await self._metadata.save_memory(existing)
                        logger.info(
                            "pipeline.single_dedup_promoted",
                            match=dup_id,
                            capture_method=existing.source.capture_method.value,
                            is_pinned=existing.is_pinned,
                        )
                    logger.info(
                        "pipeline.single_dedup_skip",
                        candidate=memory.id,
                        match=dup_id,
                        capture_method=capture_method.value,
                    )
                    return existing

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
                project=project_key,
            )
            try:
                raw_embedding = await self._embedder.embed_document(content)
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

    async def _find_write_time_duplicate(self, content: str, embedding: list[float]) -> str | None:
        """Return the id of an existing near-duplicate memory, or None.

        Near-duplicate := a top vector match with score above
        ``_WRITE_DEDUP_SCORE_THRESHOLD`` AND lexical overlap above
        ``_WRITE_DEDUP_OVERLAP_THRESHOLD``. Both signals are required so a
        deliberately rephrased memory (high cosine, lower word overlap) is never
        treated as a duplicate. Any vector-store error degrades to "no
        duplicate" so dedup can never block a write.
        """
        try:
            similar = await self._vectors.search(embedding, limit=3)
        except Exception:
            return None
        if not isinstance(similar, list):
            return None
        for match in similar:
            if not isinstance(match, dict):
                continue
            if match.get("score", 0) > _WRITE_DEDUP_SCORE_THRESHOLD:
                match_content = (match.get("payload") or {}).get("content", "")
                if text_overlap(content, match_content) > _WRITE_DEDUP_OVERLAP_THRESHOLD:
                    return str(match.get("id") or "") or None
        return None

    async def _detect_contradictions(self, memories: list[Memory]) -> None:
        """Check new memories against existing similar memories for contradictions.

        When a contradiction is detected (high semantic similarity but low text overlap),
        the older memory is marked as superseded.
        """
        for memory in memories:
            try:
                # Doc-vs-doc similarity (contradiction detection between two
                # stored memories) → use document encoding on both sides.
                embedding = await self._embedder.embed_document(memory.content)
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
