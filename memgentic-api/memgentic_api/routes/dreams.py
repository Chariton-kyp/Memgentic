"""Auto-dream REST endpoints — list, run, inspect, apply, reject."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from memgentic.config import settings
from memgentic.models import DreamPatch, DreamRun

from memgentic_api.deps import EmbedderDep, MetadataStoreDep, limiter
from memgentic_api.schemas import (
    ApplyDreamRequest,
    ApplyDreamResponse,
    CreateDreamRequest,
    DreamDetailResponse,
    DreamListResponse,
    DreamPatchResponse,
    DreamRunResponse,
    RejectDreamResponse,
)

logger = structlog.get_logger()
router = APIRouter()


def _run_to_response(run: DreamRun, patches_count: int = 0) -> DreamRunResponse:
    return DreamRunResponse(
        id=run.id,
        project=run.project,
        status=run.status.value,
        model=run.model,
        instructions=run.instructions,
        input_session_ids=run.input_session_ids,
        input_memory_count=run.input_memory_count,
        error=run.error,
        usage_input_tokens=run.usage_input_tokens,
        usage_output_tokens=run.usage_output_tokens,
        created_at=run.created_at,
        ended_at=run.ended_at,
        applied_at=run.applied_at,
        patches_count=patches_count,
    )


def _patch_to_response(patch: DreamPatch) -> DreamPatchResponse:
    return DreamPatchResponse(
        id=patch.id,
        dream_id=patch.dream_id,
        action=patch.action.value,
        target_memory_ids=patch.target_memory_ids,
        new_content=patch.new_content,
        new_metadata=patch.new_metadata,
        evidence=patch.evidence,
        status=patch.status.value,
        created_at=patch.created_at,
        applied_at=patch.applied_at,
    )


@router.get("/dreams")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_dreams(
    request: Request,
    metadata_store: MetadataStoreDep,
    project: str | None = Query(default=None, description="Filter by project key"),
    status: str | None = Query(default=None, description="Filter by lifecycle status"),
    limit: int = Query(default=20, ge=1, le=200),
) -> DreamListResponse:
    """List recent dream runs, optionally filtered by project or status."""
    runs = await metadata_store.list_dream_runs(project=project, status=status, limit=limit)
    out: list[DreamRunResponse] = []
    for run in runs:
        patches = await metadata_store.get_dream_patches(run.id)
        out.append(_run_to_response(run, patches_count=len(patches)))
    return DreamListResponse(dreams=out, total=len(out))


@router.get("/dreams/{dream_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_dream(
    request: Request,
    dream_id: str,
    metadata_store: MetadataStoreDep,
) -> DreamDetailResponse:
    """Inspect a single dream run with its full patch list."""
    run = await metadata_store.get_dream_run(dream_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Dream {dream_id} not found")

    patches = await metadata_store.get_dream_patches(dream_id)
    return DreamDetailResponse(
        run=_run_to_response(run, patches_count=len(patches)),
        patches=[_patch_to_response(p) for p in patches],
    )


@router.post("/dreams", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def create_dream(
    request: Request,
    body: CreateDreamRequest,
    metadata_store: MetadataStoreDep,
    embedder: EmbedderDep,
) -> DreamRunResponse:
    """Run a new dream cycle and persist proposed patches.

    Synchronous: the request blocks until the pipeline finishes. Long-running
    scopes (large stores, slow LLMs) should be invoked from a worker queue
    rather than from the request handler. Phase 3 with Sonnet over ~50
    clusters typically takes 5-10 minutes.
    """
    try:
        from memgentic.processing.dream import run_dream
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Dream pipeline requires the [intelligence] extras "
                "(pip install memgentic[intelligence])."
            ),
        ) from exc

    # Default project = empty (no filter). The dashboard surfaces a project
    # picker; the CLI does cwd-derivation, but a server has no cwd worth
    # deriving from.
    project_scope = body.project if body.project is not None else ""

    try:
        run = await run_dream(
            project=project_scope,
            metadata_store=metadata_store,
            embedder=embedder,
            settings=settings,
            signal_model=body.signal_model,
            consolidate_model=body.consolidate_model,
            instructions=body.instructions,
            limit_sessions=body.limit_sessions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("dreams.create.failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    patches = await metadata_store.get_dream_patches(run.id)
    return _run_to_response(run, patches_count=len(patches))


@router.post("/dreams/{dream_id}/apply")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def apply_dream_endpoint(
    request: Request,
    dream_id: str,
    body: ApplyDreamRequest,
    metadata_store: MetadataStoreDep,
) -> ApplyDreamResponse:
    """Execute proposed patches against the live memory store.

    This is destructive: when ``only_non_destructive=False``, merges, supersedes
    and archives all run. The dashboard SHOULD default to ``true`` in its UI
    and surface an explicit confirmation dialog for the destructive variant.
    """
    try:
        from memgentic.processing.dream import apply_dream
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Dream pipeline requires the [intelligence] extras.",
        ) from exc

    run = await metadata_store.get_dream_run(dream_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Dream {dream_id} not found")

    report = await apply_dream(
        dream_id,
        metadata_store=metadata_store,
        only_non_destructive=body.only_non_destructive,
    )
    return ApplyDreamResponse(
        dream_id=report.dream_id,
        applied=report.applied,
        skipped_destructive=report.skipped_destructive,
        inserted_memories=report.inserted_memories,
        superseded_memories=report.superseded_memories,
        archived_memories=report.archived_memories,
        chronograph_triples=report.chronograph_triples,
        errors=report.errors,
    )


@router.post("/dreams/{dream_id}/reject")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def reject_dream_endpoint(
    request: Request,
    dream_id: str,
    metadata_store: MetadataStoreDep,
) -> RejectDreamResponse:
    """Mark every still-proposed patch in this dream as rejected (no mutation)."""
    try:
        from memgentic.processing.dream import reject_dream
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Dream pipeline requires the [intelligence] extras.",
        ) from exc

    run = await metadata_store.get_dream_run(dream_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Dream {dream_id} not found")

    rejected = await reject_dream(dream_id, metadata_store=metadata_store)
    return RejectDreamResponse(dream_id=dream_id, rejected=rejected)
