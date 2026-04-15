"""Collection CRUD and membership endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from memgentic.config import settings
from memgentic.events import EventType, MemgenticEvent, event_bus
from memgentic.models import Collection

from memgentic_api.deps import MetadataStoreDep, limiter
from memgentic_api.schemas import (
    AddMemoryToCollectionRequest,
    CollectionListResponse,
    CollectionResponse,
    CreateCollectionRequest,
    MemoryListResponse,
    MemoryResponse,
    SourceResponse,
    UpdateCollectionRequest,
)

logger = structlog.get_logger()
router = APIRouter()


def _collection_to_response(collection: Collection, memory_count: int = 0) -> CollectionResponse:
    """Convert a core Collection model to an API CollectionResponse."""
    return CollectionResponse(
        id=collection.id,
        user_id=collection.user_id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        icon=collection.icon,
        position=collection.position,
        memory_count=memory_count,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


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
    )


# --- Collection CRUD ---


@router.get("/collections")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_collections(
    request: Request,
    metadata_store: MetadataStoreDep,
) -> CollectionListResponse:
    """List all collections with memory counts."""
    collections = await metadata_store.get_collections()
    responses = []
    for coll in collections:
        count = await metadata_store.get_collection_memory_count(coll.id)
        responses.append(_collection_to_response(coll, memory_count=count))
    return CollectionListResponse(collections=responses, total=len(responses))


@router.post("/collections", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def create_collection(
    request: Request,
    body: CreateCollectionRequest,
    metadata_store: MetadataStoreDep,
) -> CollectionResponse:
    """Create a new collection."""
    collection = Collection(
        name=body.name,
        description=body.description,
        color=body.color,
        icon=body.icon,
    )
    await metadata_store.create_collection(collection)
    logger.info("collections.created", id=collection.id, name=collection.name)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.COLLECTION_CREATED,
            data={
                "id": collection.id,
                "name": collection.name,
            },
        )
    )
    return _collection_to_response(collection, memory_count=0)


@router.patch("/collections/{collection_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def update_collection(
    request: Request,
    collection_id: str,
    body: UpdateCollectionRequest,
    metadata_store: MetadataStoreDep,
) -> CollectionResponse:
    """Update a collection's metadata."""
    existing = await metadata_store.get_collection(collection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")

    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        await metadata_store.update_collection(collection_id, **update_data)

    updated = await metadata_store.get_collection(collection_id)
    count = await metadata_store.get_collection_memory_count(collection_id)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.COLLECTION_UPDATED,
            data={
                "id": collection_id,
                "name": updated.name,
            },
        )
    )
    return _collection_to_response(updated, memory_count=count)


@router.delete("/collections/{collection_id}", status_code=204)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def delete_collection(
    request: Request,
    collection_id: str,
    metadata_store: MetadataStoreDep,
) -> None:
    """Delete a collection and its membership links."""
    existing = await metadata_store.get_collection(collection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")
    await metadata_store.delete_collection(collection_id)
    logger.info("collections.deleted", id=collection_id)
    await event_bus.emit(
        MemgenticEvent(
            type=EventType.COLLECTION_DELETED,
            data={"id": collection_id},
        )
    )


# --- Collection Membership ---


@router.get("/collections/{collection_id}/memories")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_collection_memories(
    request: Request,
    collection_id: str,
    metadata_store: MetadataStoreDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> MemoryListResponse:
    """List memories in a collection."""
    existing = await metadata_store.get_collection(collection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")

    offset = (page - 1) * page_size
    memories = await metadata_store.get_collection_memories(
        collection_id, limit=page_size, offset=offset
    )
    total = await metadata_store.get_collection_memory_count(collection_id)
    return MemoryListResponse(
        memories=[_memory_to_response(m) for m in memories],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/collections/{collection_id}/memories", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def add_memory_to_collection(
    request: Request,
    collection_id: str,
    body: AddMemoryToCollectionRequest,
    metadata_store: MetadataStoreDep,
) -> dict:
    """Add a memory to a collection."""
    existing = await metadata_store.get_collection(collection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")

    memory = await metadata_store.get_memory(body.memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    await metadata_store.add_memory_to_collection(collection_id, body.memory_id)
    logger.info(
        "collections.memory_added",
        collection_id=collection_id,
        memory_id=body.memory_id,
    )
    return {"status": "added", "collection_id": collection_id, "memory_id": body.memory_id}


@router.delete("/collections/{collection_id}/memories/{memory_id}", status_code=204)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def remove_memory_from_collection(
    request: Request,
    collection_id: str,
    memory_id: str,
    metadata_store: MetadataStoreDep,
) -> None:
    """Remove a memory from a collection."""
    existing = await metadata_store.get_collection(collection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Collection not found")
    await metadata_store.remove_memory_from_collection(collection_id, memory_id)
    logger.info(
        "collections.memory_removed",
        collection_id=collection_id,
        memory_id=memory_id,
    )
