"""Persona CRUD + bootstrap endpoints.

Routes:
    GET    /api/v1/persona                  Current persona (JSON)
    PUT    /api/v1/persona                  Replace entirely (validated)
    PATCH  /api/v1/persona                  RFC-7396 merge patch
    POST   /api/v1/persona/bootstrap        Return an LLM-proposed persona (no save)
    POST   /api/v1/persona/bootstrap/accept Persist a client-supplied persona
    GET    /api/v1/persona/schema           JSON Schema for client-side validation

The ``bootstrap`` flow is intentionally stateless: the proposal is
returned to the client, which then POSTs it back to ``/accept`` (or
PUTs it over ``/persona``) to persist. This avoids a per-worker
in-memory cache that would break across API replicas and in tests.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from memgentic.config import settings
from memgentic.persona import (
    bootstrap as persona_bootstrap,
)
from memgentic.persona import (
    default_persona,
    load,
    save,
)
from memgentic.persona.loader import PersonaLockError, PersonaMalformedError
from memgentic.persona.schema import Persona, validate
from pydantic import BaseModel, Field, ValidationError

from memgentic_api.deps import limiter

logger = structlog.get_logger()
router = APIRouter()


# --- Request models ------------------------------------------------------


class PersonaBootstrapRequest(BaseModel):
    """Options for ``POST /persona/bootstrap``."""

    source: str = Field(default="recent", pattern="^(recent|skills)$")
    limit: int = Field(default=100, ge=1, le=500)


class PersonaBootstrapAcceptRequest(BaseModel):
    """Body for ``POST /persona/bootstrap/accept``."""

    persona: dict[str, Any]


# --- Helpers -------------------------------------------------------------


def _persona_or_default() -> Persona:
    try:
        persona = load()
    except PersonaMalformedError as exc:
        raise HTTPException(status_code=500, detail=f"Persona file is malformed: {exc}") from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Persona file failed validation: {exc}",
        ) from exc
    return persona or default_persona()


def _validate_body(data: Any) -> Persona:
    """Validate an incoming persona body, translating failures to 400."""
    try:
        return validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _deep_merge(base: dict, patch: dict) -> dict:
    """RFC-7396 merge patch: nulls delete keys, nested dicts merge recursively."""
    result = dict(base)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# --- Routes --------------------------------------------------------------


@router.get("/persona")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_persona(request: Request) -> dict[str, Any]:
    """Return the current persona (or the safe default when none exists)."""
    persona = _persona_or_default()
    return persona.model_dump(mode="json")


@router.put("/persona")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def put_persona(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Replace the persona entirely (after validation)."""
    persona = _validate_body(body)
    persona.metadata.generated_by = "edited"
    try:
        save(persona)
    except PersonaLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return persona.model_dump(mode="json")


@router.patch("/persona")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def patch_persona(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """RFC-7396 JSON merge patch against the current persona."""
    current = _persona_or_default().model_dump(mode="json")
    merged = _deep_merge(current, body)
    persona = _validate_body(merged)
    persona.metadata.generated_by = "edited"
    try:
        save(persona)
    except PersonaLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return persona.model_dump(mode="json")


@router.post("/persona/bootstrap")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def bootstrap_endpoint(
    request: Request,
    body: PersonaBootstrapRequest | None = None,
) -> dict[str, Any]:
    """Ask the LLM to propose a persona. Does NOT persist."""
    opts = body or PersonaBootstrapRequest()
    try:
        proposed = await persona_bootstrap(source=opts.source, limit=opts.limit)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("persona.api.bootstrap_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Bootstrap failed: {exc}") from exc

    if proposed is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Bootstrap unavailable — configure an LLM "
                "(set GOOGLE_API_KEY or run a local Ollama model)."
            ),
        )
    return {"persona": proposed.model_dump(mode="json")}


@router.post("/persona/bootstrap/accept")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def bootstrap_accept(
    request: Request,
    body: PersonaBootstrapAcceptRequest,
) -> dict[str, Any]:
    """Persist a client-supplied persona (typically the one returned by bootstrap)."""
    persona = _validate_body(body.persona)
    persona.metadata.generated_by = "bootstrap"
    try:
        save(persona)
    except PersonaLockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return persona.model_dump(mode="json")


@router.get("/persona/schema")
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def persona_schema(request: Request) -> dict[str, Any]:
    """Return the Persona JSON schema for client-side validation."""
    return Persona.model_json_schema()
