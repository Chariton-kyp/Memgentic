"""Chronograph REST endpoints — bitemporal triple store.

Wraps :class:`memgentic.graph.Chronograph` behind a thin REST surface:

- ``GET  /chronograph`` — stats
- ``GET  /chronograph/entities`` / ``POST /chronograph/entities``
- ``GET  /chronograph/entities/{name}``
- ``GET  /chronograph/triples`` (filter) / ``POST /chronograph/triples``
- ``PATCH /chronograph/triples/{id}`` (edit)
- ``POST /chronograph/triples/{id}/accept`` / ``reject`` / ``invalidate``
- ``GET  /chronograph/proposed`` — validation queue
- ``GET  /chronograph/timeline``
- ``POST /chronograph/backfill`` / ``GET /chronograph/backfill/{job_id}``

The backfill endpoints run a small in-memory job registry so the
dashboard can kick off a long-running extractor without blocking the
request handler.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from memgentic.config import settings
from memgentic.graph import Chronograph, get_chronograph
from pydantic import BaseModel, ConfigDict, Field

from memgentic_api.deps import limiter

router = APIRouter()


async def _chronograph_dep() -> Chronograph:
    return await get_chronograph()


ChronographDep = Annotated[Chronograph, Depends(_chronograph_dep)]


# --------------------------------------------------------------------- models


class EntityCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1)
    type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str | None = None


class TripleCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    subject: str = Field(..., min_length=1)
    predicate: str = Field(..., min_length=1)
    object: str = Field(..., min_length=1)
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_memory_id: str | None = None
    proposer: str = Field(default="user")
    status: Literal["proposed", "accepted", "rejected", "edited"] = Field(default="accepted")
    workspace_id: str | None = None


class TriplePatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    predicate: str | None = None
    subject: str | None = None
    object: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class InvalidateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ended: str | None = None


class BackfillRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    batch: int = Field(default=50, ge=1, le=500)
    dry_run: bool = False


# --------------------------------------------------------------------- stats


@router.get("/chronograph")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def chronograph_stats(request: Request, cg: ChronographDep) -> dict:
    """Counts for the Chronograph — entities, triples, status distribution."""
    return await cg.stats()


# ------------------------------------------------------------------ entities


@router.get("/chronograph/entities")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_entities(
    request: Request,
    cg: ChronographDep,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workspace_id: str | None = Query(default=None),
) -> dict:
    entities = await cg.list_entities(limit=limit, offset=offset, workspace_id=workspace_id)
    return {
        "count": len(entities),
        "entities": [e.to_dict() for e in entities],
    }


@router.post("/chronograph/entities", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def create_entity(
    request: Request,
    cg: ChronographDep,
    payload: EntityCreateRequest,
) -> dict:
    entity = await cg.add_entity(
        name=payload.name,
        type=payload.type,
        aliases=payload.aliases,
        properties=payload.properties,
        workspace_id=payload.workspace_id,
    )
    return entity.to_dict()


@router.get("/chronograph/entities/{name}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_entity(request: Request, cg: ChronographDep, name: str) -> dict:
    entity = await cg.get_entity(name)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"entity '{name}' not found")
    return entity.to_dict()


# -------------------------------------------------------------------- triples


@router.get("/chronograph/triples")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_triples(
    request: Request,
    cg: ChronographDep,
    subject: str | None = Query(default=None),
    predicate: str | None = Query(default=None),
    object: str | None = Query(default=None),  # noqa: A002
    status: Literal["proposed", "accepted", "rejected", "edited", "any"] = Query(default="any"),
    as_of: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    triples = await cg.search_triples(
        subject=subject,
        predicate=predicate,
        object=object,
        status=status,
        as_of=as_of,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(triples),
        "triples": [t.to_dict() for t in triples],
    }


@router.post("/chronograph/triples", status_code=201)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def create_triple(
    request: Request,
    cg: ChronographDep,
    payload: TripleCreateRequest,
) -> dict:
    triple = await cg.add_triple(
        subject=payload.subject,
        predicate=payload.predicate,
        object=payload.object,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        confidence=payload.confidence,
        source_memory_id=payload.source_memory_id,
        proposer=payload.proposer,
        status=payload.status,
        workspace_id=payload.workspace_id,
    )
    return triple.to_dict()


@router.patch("/chronograph/triples/{triple_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def patch_triple(
    request: Request,
    cg: ChronographDep,
    triple_id: str,
    payload: TriplePatchRequest,
) -> dict:
    try:
        triple = await cg.edit(triple_id, **payload.model_dump(exclude_none=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return triple.to_dict()


@router.post("/chronograph/triples/{triple_id}/accept")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def accept_triple(
    request: Request,
    cg: ChronographDep,
    triple_id: str,
    user_id: str | None = Query(default=None),
) -> dict:
    try:
        triple = await cg.accept(triple_id, user_id=user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return triple.to_dict()


@router.post("/chronograph/triples/{triple_id}/reject")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def reject_triple(request: Request, cg: ChronographDep, triple_id: str) -> dict:
    try:
        triple = await cg.reject(triple_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return triple.to_dict()


@router.post("/chronograph/triples/{triple_id}/invalidate")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def invalidate_triple(
    request: Request,
    cg: ChronographDep,
    triple_id: str,
    payload: InvalidateRequest | None = None,
) -> dict:
    payload = payload or InvalidateRequest()
    triple = await cg.get_triple(triple_id)
    if triple is None:
        raise HTTPException(status_code=404, detail=f"triple {triple_id} not found")
    await cg.invalidate(triple.subject, triple.predicate, triple.object, ended=payload.ended)
    updated = await cg.get_triple(triple_id)
    return updated.to_dict() if updated else triple.to_dict()


# ------------------------------------------------------------- proposed queue


@router.get("/chronograph/proposed")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_proposed(
    request: Request,
    cg: ChronographDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    workspace_id: str | None = Query(default=None),
) -> dict:
    triples = await cg.list_proposed(limit=limit, offset=offset, workspace_id=workspace_id)
    return {"count": len(triples), "triples": [t.to_dict() for t in triples]}


@router.get("/chronograph/timeline")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_timeline(
    request: Request,
    cg: ChronographDep,
    entity: str | None = Query(default=None),
    status: Literal["proposed", "accepted", "rejected", "edited", "any"] = Query(
        default="accepted"
    ),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    triples = await cg.timeline(entity=entity, status=status, limit=limit)
    return {"count": len(triples), "triples": [t.to_dict() for t in triples]}


# ------------------------------------------------------------------- backfill

# Simple in-process job registry. Dashboard polls ``GET /backfill/{id}`` to
# follow progress. Entries persist for the lifetime of the API process; the
# registry is intentionally small because the dashboard typically reads a job
# once and discards the id.
_backfill_jobs: dict[str, dict[str, Any]] = {}


async def _run_backfill(
    job_id: str,
    batch: int,
    dry_run: bool,
    metadata_store: Any,
    cg: Chronograph,
) -> None:
    from memgentic.graph.extractor import extract_triples, store_proposed
    from memgentic.processing.llm import LLMClient

    job = _backfill_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.now(UTC).isoformat()

    try:
        llm = LLMClient(settings)
        if not llm.available:
            job["status"] = "failed"
            job["error"] = "no LLM configured"
            return
        memories = await metadata_store.get_memories_by_filter(limit=batch)
        total = 0
        for mem in memories:
            if getattr(mem, "capture_profile", "enriched") == "raw":
                continue
            proposed = await extract_triples(mem, llm, cg)
            if not dry_run:
                await store_proposed(proposed, cg)
            total += len(proposed)
            job["processed"] += 1
        job["triples_proposed"] = total
        job["status"] = "completed"
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["completed_at"] = datetime.now(UTC).isoformat()


@router.post("/chronograph/backfill", status_code=202)
@limiter.limit(lambda: f"{settings.rate_limit_import}/minute")
async def start_backfill(
    request: Request,
    cg: ChronographDep,
    payload: BackfillRequest | None = None,
) -> dict:
    payload = payload or BackfillRequest()
    metadata_store = request.app.state.metadata_store
    job_id = str(uuid.uuid4())
    _backfill_jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "batch": payload.batch,
        "dry_run": payload.dry_run,
        "processed": 0,
        "triples_proposed": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "error": None,
    }
    asyncio.create_task(_run_backfill(job_id, payload.batch, payload.dry_run, metadata_store, cg))
    return _backfill_jobs[job_id]


@router.get("/chronograph/backfill/{job_id}")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_backfill(request: Request, job_id: str) -> dict:
    job = _backfill_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"backfill job {job_id} not found")
    return job
