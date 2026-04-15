"""Ingestion job routes — list, inspect, and cancel running ingestion jobs."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from memgentic.config import settings
from memgentic.events import EventType, MemgenticEvent, event_bus
from memgentic.models import IngestionJob, IngestionJobStatus

from memgentic_api.deps import MetadataStoreDep, limiter
from memgentic_api.schemas import IngestionJobListResponse, IngestionJobResponse

logger = structlog.get_logger()
router = APIRouter()


def _job_to_response(job: IngestionJob) -> IngestionJobResponse:
    """Serialize an ``IngestionJob`` model into an API response."""
    return IngestionJobResponse(
        id=job.id,
        source_type=job.source_type,
        source_path=job.source_path,
        status=job.status.value,
        total_items=job.total_items,
        processed_items=job.processed_items,
        failed_items=job.failed_items,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/ingestion/jobs")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_ingestion_jobs(
    request: Request,
    metadata_store: MetadataStoreDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> IngestionJobListResponse:
    """List ingestion jobs (most recent first, paginated)."""
    jobs, total = await metadata_store.get_ingestion_jobs(limit=limit, offset=offset)
    return IngestionJobListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=total,
    )


@router.get("/ingestion/jobs/{job_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_ingestion_job(
    request: Request,
    job_id: str,
    metadata_store: MetadataStoreDep,
) -> IngestionJobResponse:
    """Fetch a single ingestion job by id."""
    job = await metadata_store.get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return _job_to_response(job)


@router.post("/ingestion/jobs/{job_id}/cancel")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def cancel_ingestion_job(
    request: Request,
    job_id: str,
    metadata_store: MetadataStoreDep,
) -> IngestionJobResponse:
    """Cancel a running or queued ingestion job.

    Terminal jobs (``completed``/``failed``) are returned unchanged with a
    409 so that callers can distinguish a true cancel from a no-op.
    """
    job = await metadata_store.get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    if job.status in (IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job in status '{job.status.value}'",
        )

    now = datetime.now(UTC)
    await metadata_store.update_ingestion_job(
        job_id,
        status=IngestionJobStatus.FAILED,
        error_message="Cancelled by user",
        completed_at=now,
    )

    updated = await metadata_store.get_ingestion_job(job_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to reload cancelled job")

    await event_bus.emit(
        MemgenticEvent(
            type=EventType.INGESTION_COMPLETED,
            data={
                "id": updated.id,
                "status": updated.status.value,
                "cancelled": True,
            },
        )
    )

    return _job_to_response(updated)
