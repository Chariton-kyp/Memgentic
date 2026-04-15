"""Source platform endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from memgentic.config import settings

from memgentic_api.deps import MetadataStoreDep, limiter
from memgentic_api.schemas import SourcesListResponse, SourceStatsResponse

router = APIRouter()


@router.get("/sources")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_sources(
    request: Request,
    metadata_store: MetadataStoreDep,
) -> SourcesListResponse:
    """List all source platforms with memory counts."""
    stats = await metadata_store.get_source_stats()
    total = await metadata_store.get_total_count()

    sources = [
        SourceStatsResponse(
            platform=platform,
            count=count,
            percentage=round((count / total * 100) if total > 0 else 0, 1),
        )
        for platform, count in sorted(stats.items(), key=lambda x: x[1], reverse=True)
    ]
    return SourcesListResponse(sources=sources, total=total)
