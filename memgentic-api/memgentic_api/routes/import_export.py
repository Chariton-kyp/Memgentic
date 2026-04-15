"""Import and export endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from memgentic.config import settings
from memgentic.models import ContentType, Platform

from memgentic_api.deps import MetadataStoreDep, PipelineDep, limiter
from memgentic_api.schemas import ImportMemoriesRequest

logger = structlog.get_logger()
router = APIRouter()


@router.post("/import/json", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_import}/minute")
async def import_json(
    request: Request,
    body: ImportMemoriesRequest,
    pipeline: PipelineDep,
) -> dict:
    """Import memories from a JSON array."""
    imported = 0
    errors = 0

    for item in body.memories:
        try:
            ct = ContentType(item.content_type)
        except ValueError:
            ct = ContentType.FACT
        try:
            platform = Platform(item.source)
        except ValueError:
            platform = Platform.UNKNOWN

        try:
            await pipeline.ingest_single(
                content=item.content,
                content_type=ct,
                platform=platform,
                topics=item.topics,
                entities=item.entities,
            )
            imported += 1
        except Exception as e:
            logger.warning("import.item_failed", error=str(e))
            errors += 1

    return {"imported": imported, "errors": errors, "total": len(body.memories)}


@router.get("/export")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def export_json(
    request: Request,
    metadata_store: MetadataStoreDep,
    source: str | None = None,
) -> dict:
    """Export all memories as JSON."""
    from memgentic.models import SessionConfig

    config = SessionConfig()
    if source:
        try:
            config.include_sources = [Platform(source)]
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Invalid source platform: {source}"
            ) from None

    memories = await metadata_store.get_memories_by_filter(
        session_config=config,
        limit=10000,
    )

    return {
        "count": len(memories),
        "memories": [
            {
                "id": m.id,
                "content": m.content,
                "content_type": m.content_type.value,
                "platform": m.source.platform.value,
                "platform_version": m.source.platform_version,
                "session_id": m.source.session_id,
                "session_title": m.source.session_title,
                "capture_method": m.source.capture_method.value,
                "topics": m.topics,
                "entities": m.entities,
                "confidence": m.confidence,
                "status": m.status.value,
                "created_at": m.created_at.isoformat(),
            }
            for m in memories
        ],
    }
