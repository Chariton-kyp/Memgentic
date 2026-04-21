"""Memory CRUD and search endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from memgentic.config import settings
from memgentic.events import EventType, MemgenticEvent, event_bus
from memgentic.models import ContentType, MemoryStatus, Platform, SessionConfig

from memgentic_api.deps import (
    EmbedderDep,
    MetadataStoreDep,
    PipelineDep,
    VectorStoreDep,
    limiter,
)
from memgentic_api.schemas import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    BatchUpdateRequest,
    BatchUpdateResponse,
    CreateMemoryRequest,
    KeywordSearchRequest,
    MemoryListResponse,
    MemoryResponse,
    SearchRequest,
    SearchResultItem,
    SearchResultResponse,
    SourceResponse,
    UpdateMemoryRequest,
)

logger = structlog.get_logger()
router = APIRouter()


def _memory_to_response(memory) -> MemoryResponse:
    """Convert a core Memory model to an API MemoryResponse."""
    return MemoryResponse(
        id=memory.id,
        content=memory.content,
        content_type=memory.content_type.value,
        platform=memory.source.platform.value,
        topics=memory.topics,
        entities=memory.entities,
        confidence=memory.confidence,
        status=memory.status.value,
        created_at=memory.created_at,
        last_accessed=memory.last_accessed,
        access_count=memory.access_count,
        source=SourceResponse(
            platform=memory.source.platform.value,
            platform_version=memory.source.platform_version,
            session_id=memory.source.session_id,
            session_title=memory.source.session_title,
            capture_method=memory.source.capture_method.value,
            original_timestamp=memory.source.original_timestamp,
            file_path=memory.source.file_path,
        ),
        is_pinned=memory.is_pinned,
        pinned_at=memory.pinned_at,
        capture_profile=memory.capture_profile,
        dual_sibling_id=memory.dual_sibling_id,
    )


def _payload_to_response(payload: dict, memory_id: str) -> MemoryResponse:
    """Convert a Qdrant payload dict to an API MemoryResponse."""
    return MemoryResponse(
        id=memory_id,
        content=payload.get("content", ""),
        content_type=payload.get("content_type", "fact"),
        platform=payload.get("platform", "unknown"),
        topics=payload.get("topics", []),
        entities=payload.get("entities", []),
        confidence=payload.get("confidence", 1.0),
        status=payload.get("status", "active"),
        created_at=(
            datetime.fromisoformat(payload["created_at"])
            if payload.get("created_at")
            else datetime.now(UTC)
        ),
        source=SourceResponse(
            platform=payload.get("platform", "unknown"),
            platform_version=payload.get("platform_version"),
            session_id=payload.get("session_id"),
            session_title=payload.get("session_title"),
            capture_method="mcp_tool",
        ),
    )


# --- Topics (autocomplete) ---


@router.get("/topics")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_topics(
    request: Request,
    metadata_store: MetadataStoreDep,
) -> dict:
    """List all distinct topics with counts for autocomplete."""
    if not metadata_store._db:
        return {"topics": [], "counts": {}}
    cursor = await metadata_store._db.execute(
        "SELECT topics FROM memories WHERE status = 'active' AND topics != '[]'"
    )
    rows = await cursor.fetchall()
    import json as _json

    topic_counts: dict[str, int] = {}
    for row in rows:
        try:
            topics = _json.loads(row[0])
            for t in topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1
        except (ValueError, TypeError):
            continue
    sorted_topics = sorted(topic_counts.keys(), key=lambda t: topic_counts[t], reverse=True)
    return {"topics": sorted_topics, "counts": topic_counts}


# --- List / Get / Create / Update / Delete ---


@router.get("/memories")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_memories(
    request: Request,
    metadata_store: MetadataStoreDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source: str | None = None,
    content_type: str | None = None,
) -> MemoryListResponse:
    """List memories with pagination and optional filtering."""
    config = SessionConfig()
    if source:
        try:
            config.include_sources = [Platform(source)]
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Invalid source platform: {source}"
            ) from None

    try:
        ct = ContentType(content_type) if content_type else None
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"Invalid content_type: {content_type}"
        ) from None

    offset = (page - 1) * page_size

    total = await metadata_store.get_filtered_count(session_config=config, content_type=ct)
    memories = await metadata_store.get_memories_by_filter(
        session_config=config,
        content_type=ct,
        limit=page_size,
        offset=offset,
    )

    return MemoryListResponse(
        memories=[_memory_to_response(m) for m in memories],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- Pin routes MUST be before /memories/{memory_id} to avoid route shadowing ---


@router.get("/memories/pinned")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_pinned_memories(
    request: Request,
    metadata_store: MetadataStoreDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> MemoryListResponse:
    """List pinned memories ordered by pin time."""
    memories = await metadata_store.get_pinned_memories(limit=limit)
    return MemoryListResponse(
        memories=[_memory_to_response(m) for m in memories],
        total=len(memories),
        page=1,
        page_size=limit,
    )


@router.get("/memories/{memory_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_memory(
    request: Request,
    memory_id: str,
    metadata_store: MetadataStoreDep,
) -> MemoryResponse:
    """Get a single memory by ID."""
    memory = await metadata_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    await metadata_store.update_access(memory_id)
    return _memory_to_response(memory)


@router.post("/memories", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def create_memory(
    request: Request,
    body: CreateMemoryRequest,
    pipeline: PipelineDep,
) -> MemoryResponse:
    """Create a new memory."""
    try:
        ct = ContentType(body.content_type)
    except ValueError:
        ct = ContentType.FACT

    try:
        platform = Platform(body.source)
    except ValueError:
        platform = Platform.UNKNOWN

    memory = await pipeline.ingest_single(
        content=body.content,
        content_type=ct,
        platform=platform,
        topics=body.topics,
        entities=body.entities,
        capture_profile=body.capture_profile,
    )
    return _memory_to_response(memory)


@router.patch("/memories/{memory_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def update_memory(
    request: Request,
    memory_id: str,
    body: UpdateMemoryRequest,
    metadata_store: MetadataStoreDep,
) -> MemoryResponse:
    """Update memory metadata (topics, entities, status)."""
    memory = await metadata_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    if body.topics is not None:
        memory.topics = body.topics
    if body.entities is not None:
        memory.entities = body.entities
    if body.status is not None:
        try:
            memory.status = MemoryStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}") from None

    await metadata_store.save_memory(memory)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.MEMORY_UPDATED,
            data={"id": memory_id},
        )
    )
    return _memory_to_response(memory)


@router.delete("/memories/{memory_id}", status_code=204)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def delete_memory(
    request: Request,
    memory_id: str,
    metadata_store: MetadataStoreDep,
    vector_store: VectorStoreDep,
) -> None:
    """Archive a memory (soft delete)."""
    memory = await metadata_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    memory.status = MemoryStatus.ARCHIVED
    await metadata_store.save_memory(memory)
    await vector_store.delete_memory(memory_id)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.MEMORY_DELETED,
            data={"id": memory_id},
        )
    )


# --- Search ---


@router.post("/memories/search")
@limiter.limit(lambda: f"{settings.rate_limit_search}/minute")
async def semantic_search(
    request: Request,
    body: SearchRequest,
    embedder: EmbedderDep,
    vector_store: VectorStoreDep,
    metadata_store: MetadataStoreDep,
) -> SearchResultResponse:
    """Semantic similarity search across memories.

    Uses hybrid search (semantic + keyword + graph) when intelligence extras
    is installed, otherwise falls back to vector-only search.
    """
    config = SessionConfig()
    if body.sources:
        config.include_sources = [Platform(s) for s in body.sources]
    if body.exclude_sources:
        config.exclude_sources = [Platform(s) for s in body.exclude_sources]
    if body.content_types:
        config.include_content_types = [ContentType(ct) for ct in body.content_types]

    try:
        from memgentic.graph.search import hybrid_search

        graph = getattr(request.app.state, "graph", None)
        results = await hybrid_search(
            query=body.query,
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedder=embedder,
            graph=graph,
            session_config=config,
            limit=body.limit,
        )
    except ImportError:
        from memgentic.processing.search_basic import basic_search

        results = await basic_search(
            query=body.query,
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedder=embedder,
            session_config=config,
            limit=body.limit,
        )

    items = []
    for r in results:
        await metadata_store.update_access(r["id"])
        items.append(
            SearchResultItem(
                memory=_payload_to_response(r["payload"], r["id"]),
                score=r["score"],
            )
        )

    return SearchResultResponse(results=items, query=body.query, total=len(items))


@router.get("/briefing")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_briefing(
    request: Request,
    metadata_store: MetadataStoreDep,
    since_hours: int = Query(default=24, ge=1, le=720),
) -> dict:
    """Get a briefing of recent memories grouped by platform."""
    from collections import Counter
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(hours=since_hours)
    memories = await metadata_store.get_memories_since(since, limit=100)

    platform_counts = Counter(m.source.platform.value for m in memories)
    all_topics: list[str] = []
    for m in memories:
        all_topics.extend(m.topics)
    top_topics = Counter(all_topics).most_common(10)

    return {
        "since_hours": since_hours,
        "total_new": len(memories),
        "by_platform": dict(platform_counts.most_common()),
        "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        "latest": [
            {
                "id": m.id,
                "content_preview": m.content[:150],
                "platform": m.source.platform.value,
                "content_type": m.content_type.value,
                "created_at": m.created_at.isoformat(),
            }
            for m in memories[:10]
        ],
    }


@router.post("/memories/keyword-search")
@limiter.limit(lambda: f"{settings.rate_limit_search}/minute")
async def keyword_search(
    request: Request,
    body: KeywordSearchRequest,
    metadata_store: MetadataStoreDep,
) -> SearchResultResponse:
    """Full-text keyword search using SQLite FTS5."""
    memories = await metadata_store.search_fulltext(query=body.query, limit=body.limit)

    items = [SearchResultItem(memory=_memory_to_response(m), score=1.0) for m in memories]
    return SearchResultResponse(results=items, query=body.query, total=len(items))


@router.post("/memories/{memory_id}/pin", status_code=200)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def pin_memory(
    request: Request,
    memory_id: str,
    metadata_store: MetadataStoreDep,
) -> MemoryResponse:
    """Pin a memory for quick access."""
    memory = await metadata_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    await metadata_store.pin_memory(memory_id)
    memory = await metadata_store.get_memory(memory_id)
    await event_bus.emit(
        MemgenticEvent(type=EventType.MEMORY_PINNED, data={"id": memory_id, "pinned": True})
    )
    return _memory_to_response(memory)


@router.delete("/memories/{memory_id}/pin", status_code=200)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def unpin_memory(
    request: Request,
    memory_id: str,
    metadata_store: MetadataStoreDep,
) -> MemoryResponse:
    """Unpin a memory."""
    memory = await metadata_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    await metadata_store.unpin_memory(memory_id)
    memory = await metadata_store.get_memory(memory_id)
    await event_bus.emit(
        MemgenticEvent(type=EventType.MEMORY_PINNED, data={"id": memory_id, "pinned": False})
    )
    return _memory_to_response(memory)


# --- Batch Operations ---


@router.post("/memories/batch-update")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def batch_update_memories(
    request: Request,
    body: BatchUpdateRequest,
    metadata_store: MetadataStoreDep,
) -> BatchUpdateResponse:
    """Batch update multiple memories (status, topics)."""
    # Validate status value if provided
    if "status" in body.updates:
        status_val = body.updates["status"]
        if isinstance(status_val, str):
            try:
                MemoryStatus(status_val)
            except ValueError:
                raise HTTPException(
                    status_code=422, detail=f"Invalid status: {status_val}"
                ) from None
        else:
            raise HTTPException(status_code=422, detail="status must be a string")

    updated = await metadata_store.batch_update_memories(
        memory_ids=body.memory_ids,
        updates=body.updates,
    )
    return BatchUpdateResponse(updated=updated)


@router.post("/memories/batch-delete")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def batch_delete_memories(
    request: Request,
    body: BatchDeleteRequest,
    metadata_store: MetadataStoreDep,
) -> BatchDeleteResponse:
    """Batch archive (soft-delete) multiple memories."""
    deleted = await metadata_store.batch_archive_memories(body.memory_ids)
    return BatchDeleteResponse(deleted=deleted)


# --- Related Memories ---


@router.get("/memories/{memory_id}/related")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_related_memories(
    request: Request,
    memory_id: str,
    metadata_store: MetadataStoreDep,
    embedder: EmbedderDep,
    vector_store: VectorStoreDep,
    limit: int = Query(default=5, ge=1, le=20),
) -> SearchResultResponse:
    """Find memories related to a given memory by vector proximity."""
    memory = await metadata_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Embed the memory's content and search for similar vectors
    embedding = await embedder.embed(memory.content)
    results = await vector_store.search(embedding, limit=limit + 1)

    # Filter out the source memory itself
    items = []
    for r in results:
        if r["id"] == memory_id:
            continue
        items.append(
            SearchResultItem(
                memory=_payload_to_response(r["payload"], r["id"]),
                score=r["score"],
            )
        )
    items = items[:limit]

    return SearchResultResponse(results=items, query=f"related:{memory_id}", total=len(items))
