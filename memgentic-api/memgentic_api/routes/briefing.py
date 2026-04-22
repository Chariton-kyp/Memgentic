"""Recall Tiers briefing endpoints.

Routes:
    GET  /api/v1/briefing?tier=&collection=&topic=&query=&entity=&max_tokens=
    GET  /api/v1/briefing/tiers          List tiers + their resolved budgets
    POST /api/v1/briefing/weights        Validate + preview scorer weights

The briefing endpoints are intentionally stateless — each call builds
a fresh :class:`memgentic.briefing.RecallStack`, renders the requested
tier(s), and returns the text plus accounting metadata. Clients that
want to diff weights without saving them should POST to ``/weights``:
we validate and echo back the resulting :class:`ScorerWeights`, but
never persist to disk (the design doc calls weight persistence out as
a separate user setting, so it lives in the Settings endpoint once it
ships).
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from memgentic.briefing import (
    BriefingContext,
    RecallStack,
    ScorerWeights,
    load_weights,
    resolve_budget,
)
from memgentic.config import settings
from pydantic import BaseModel, Field

from memgentic_api.deps import limiter

logger = structlog.get_logger()
router = APIRouter()


VALID_TIERS = ("T0", "T1", "T2", "T3", "T4", "default")


class BriefingResponse(BaseModel):
    """Response shape for ``GET /api/v1/briefing``."""

    tier: str
    text: str
    tokens: int
    model_context: int
    max_memories: int
    status: dict[str, Any]


class WeightsRequest(BaseModel):
    """Request body for ``POST /api/v1/briefing/weights``."""

    importance: float | None = Field(default=None, ge=0.0)
    recency: float | None = Field(default=None, ge=0.0)
    pinned: float | None = Field(default=None, ge=0.0)
    cluster: float | None = Field(default=None, ge=0.0)
    skill_link: float | None = Field(default=None, ge=0.0)
    tau_days: float | None = Field(default=None, gt=0.0)


def _overrides_from(body: WeightsRequest) -> dict[str, float]:
    """Filter unset fields — everything else becomes a scorer override."""
    out: dict[str, float] = {}
    for field in ("importance", "recency", "pinned", "cluster", "skill_link", "tau_days"):
        value = getattr(body, field)
        if value is not None:
            out[field] = float(value)
    return out


def _build_context(
    request: Request,
    *,
    collection: str | None,
    topic: str | None,
    query: str | None,
    entity: str | None,
    model_context: int | None,
    max_tokens: int | None,
    weights: ScorerWeights | None,
) -> BriefingContext:
    """Pull lifespan-attached stores off ``request.app.state`` into a context."""
    app_state = request.app.state
    return BriefingContext(
        metadata_store=getattr(app_state, "metadata_store", None),
        vector_store=getattr(app_state, "vector_store", None),
        embedder=getattr(app_state, "embedder", None),
        graph=getattr(app_state, "graph", None),
        collection=collection,
        topic=topic,
        query=query,
        entity=entity,
        model_context=model_context,
        max_tokens=max_tokens,
        weights=weights,
    )


@router.get("/briefing", response_model=BriefingResponse)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_briefing(
    request: Request,
    tier: str = "default",
    collection: str | None = None,
    topic: str | None = None,
    query: str | None = None,
    entity: str | None = None,
    model_context: int | None = None,
    max_tokens: int | None = None,
) -> BriefingResponse:
    """Render a Recall Tiers briefing (default: T0+T1).

    Mirrors the CLI ``memgentic briefing`` command so the dashboard and
    downstream services stay in lockstep. For weights overrides, POST
    to ``/briefing/weights`` first — that endpoint builds a validated
    :class:`ScorerWeights` the dashboard can round-trip.
    """
    if tier not in VALID_TIERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tier {tier!r}. Expected one of: {', '.join(VALID_TIERS)}",
        )

    stack = RecallStack()
    ctx = _build_context(
        request,
        collection=collection,
        topic=topic,
        query=query,
        entity=entity,
        model_context=model_context,
        max_tokens=max_tokens,
        weights=None,
    )

    try:
        if tier == "default":
            text = await stack.briefing(ctx)
            budget = resolve_budget("T1", model_context, max_tokens=max_tokens)
        else:
            out = await stack.tier_recall(tier, ctx)
            text = out.text
            budget = out.budget
    except Exception as exc:
        logger.error("briefing.api.render_failed", tier=tier, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Briefing failed: {exc}") from exc

    status = stack.status()
    tokens = int(status["last_run"].get("tokens", 0))
    return BriefingResponse(
        tier=tier,
        text=text,
        tokens=tokens,
        model_context=budget.model_context,
        max_memories=budget.max_memories,
        status=status,
    )


@router.get("/briefing/tiers")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_tiers(
    request: Request,
    model_context: int | None = None,
) -> dict[str, Any]:
    """List tiers and their resolved budgets for the given context size.

    Drives the dashboard status panel — no stores touched, so this
    endpoint is cheap enough to poll from the UI.
    """
    return {
        "tiers": {
            tier: {
                "label": label,
                "budget": resolve_budget(tier, model_context).__dict__,
            }
            for tier, label in (
                ("T0", "Persona"),
                ("T1", "Horizon"),
                ("T2", "Orbit"),
                ("T3", "Deep Recall"),
                ("T4", "Atlas"),
            )
        }
    }


@router.post("/briefing/weights")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def preview_weights(request: Request, body: WeightsRequest) -> dict[str, Any]:
    """Validate a weights override bundle and echo the resolved weights.

    The endpoint does not persist — the dashboard uses this to verify
    a candidate weight set before saving it elsewhere (e.g. user
    settings). If persistence ships, wire it into the Settings route.
    """
    overrides = _overrides_from(body)
    try:
        weights = load_weights(overrides)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"weights": weights.as_dict(), "overrides": overrides}
