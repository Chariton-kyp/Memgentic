"""Statistics, analytics, health, and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from memgentic.config import settings

from memgentic_api.deps import (
    MetadataStoreDep,
    VectorStoreDep,
    limiter,
)
from memgentic_api.schemas import SourceStatsResponse, StatsResponse

router = APIRouter()


@router.get("/stats")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_stats(
    request: Request,
    metadata_store: MetadataStoreDep,
    vector_store: VectorStoreDep,
) -> StatsResponse:
    """Get overall memory statistics."""
    source_stats = await metadata_store.get_source_stats()
    total = await metadata_store.get_total_count()
    vector_info = await vector_store.get_collection_info()

    sources = [
        SourceStatsResponse(
            platform=platform,
            count=count,
            percentage=round((count / total * 100) if total > 0 else 0, 1),
        )
        for platform, count in sorted(source_stats.items(), key=lambda x: x[1], reverse=True)
    ]

    return StatsResponse(
        total_memories=total,
        vector_count=vector_info.get("indexed_vectors_count", 0),
        store_status=vector_info.get("status", "unknown"),
        sources=sources,
    )


@router.get("/me")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_me(
    request: Request,
) -> dict:
    """Get current user info (single-user mode: always local)."""
    return {"authenticated": False, "mode": "local"}


@router.get("/health/detailed")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def detailed_health(
    request: Request,
    metadata_store: MetadataStoreDep,
    vector_store: VectorStoreDep,
) -> dict:
    """Detailed health check with component status."""
    components: dict[str, dict] = {}

    # Check metadata store
    try:
        count = await metadata_store.get_total_count()
        components["metadata_store"] = {"status": "healthy", "memory_count": count}
    except Exception as e:
        components["metadata_store"] = {"status": "unhealthy", "error": str(e)}

    # Check vector store
    try:
        info = await vector_store.get_collection_info()
        components["vector_store"] = {
            "status": "healthy",
            "vectors": info.get("indexed_vectors_count", 0),
        }
    except Exception as e:
        components["vector_store"] = {"status": "unhealthy", "error": str(e)}

    all_healthy = all(c["status"] == "healthy" for c in components.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "version": "0.1.0",
        "components": components,
    }


@router.get("/metrics")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def metrics(
    request: Request,
    metadata_store: MetadataStoreDep,
    vector_store: VectorStoreDep,
) -> dict:
    """Operational metrics for monitoring."""
    source_stats = await metadata_store.get_source_stats()
    total = await metadata_store.get_total_count()
    vector_info = await vector_store.get_collection_info()

    return {
        "memories_total": total,
        "memories_by_platform": source_stats,
        "vectors_indexed": vector_info.get("indexed_vectors_count", 0),
        "vector_store_status": vector_info.get("status", "unknown"),
    }
