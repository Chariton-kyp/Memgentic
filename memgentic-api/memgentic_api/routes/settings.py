"""Runtime-mutable settings endpoints (capture profile, etc.)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from memgentic.config import settings as core_settings

from memgentic_api.deps import MetadataStoreDep, limiter
from memgentic_api.schemas import (
    CaptureProfileSettingResponse,
    UpdateCaptureProfileRequest,
)

logger = structlog.get_logger()
router = APIRouter()

# Persisted key inside ``runtime_settings`` — must match the CLI and MCP tool.
_CAPTURE_PROFILE_SETTING_KEY = "default_capture_profile"
_VALID_PROFILES = ("raw", "enriched", "dual")


async def _effective_capture_profile(metadata_store) -> str:
    """Return the runtime override if set, else the env/config baseline."""
    stored = await metadata_store.get_runtime_setting(_CAPTURE_PROFILE_SETTING_KEY)
    if stored and stored in _VALID_PROFILES:
        return stored
    return core_settings.default_capture_profile


@router.get("/settings/capture-profile", response_model=CaptureProfileSettingResponse)
@limiter.limit(lambda: f"{core_settings.rate_limit_default}/minute")
async def get_capture_profile_setting(
    request: Request,
    metadata_store: MetadataStoreDep,
) -> CaptureProfileSettingResponse:
    """Return the current default capture profile."""
    profile = await _effective_capture_profile(metadata_store)
    return CaptureProfileSettingResponse(profile=profile)  # type: ignore[arg-type]


@router.put("/settings/capture-profile", response_model=CaptureProfileSettingResponse)
@limiter.limit(lambda: f"{core_settings.rate_limit_default}/minute")
async def update_capture_profile_setting(
    request: Request,
    body: UpdateCaptureProfileRequest,
    metadata_store: MetadataStoreDep,
) -> CaptureProfileSettingResponse:
    """Persist a new default capture profile.

    The value is written to the ``runtime_settings`` kv table and also
    mirrored into the in-process ``core_settings`` instance so subsequent
    ingestion calls in the same API process pick it up immediately.
    """
    await metadata_store.set_runtime_setting(_CAPTURE_PROFILE_SETTING_KEY, body.profile)
    core_settings.default_capture_profile = body.profile  # type: ignore[assignment]
    logger.info("api.capture_profile_updated", profile=body.profile)
    return CaptureProfileSettingResponse(profile=body.profile)
