"""REST endpoints for the Watchers umbrella.

These mirror the ``memgentic watchers`` CLI subgroup — install, uninstall,
enable, disable, status, logs — so the dashboard can manage cross-tool
automatic capture without shelling out.

All endpoints are thin wrappers over :mod:`memgentic.daemon.watcher_install`
and :mod:`memgentic.daemon.watcher_state`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from memgentic.config import settings
from memgentic.daemon.watcher_install import INSTALLABLE_TOOLS, install, uninstall
from memgentic.daemon.watcher_state import WatcherStateStore
from memgentic.daemon.watchers import ALL_TOOLS, classify_tool
from pydantic import BaseModel, Field

from memgentic_api.deps import limiter

router = APIRouter()


def _store() -> WatcherStateStore:
    # The store is a thin wrapper over sqlite, safe to instantiate per-call.
    return WatcherStateStore()


class WatcherRow(BaseModel):
    tool: str
    mechanism: str = Field(
        description="hook | file_watcher | mcp | import | unknown",
    )
    installed: bool
    enabled: bool
    installed_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    captured_count: int = 0
    last_captured_at: str | None = None


class WatcherListResponse(BaseModel):
    watchers: list[WatcherRow]


class WatcherUpdate(BaseModel):
    enabled: bool


class WatcherActionResponse(BaseModel):
    tool: str
    changed: bool
    message: str


class WatcherLogRow(BaseModel):
    created_at: str
    level: str
    message: str


class WatcherLogsResponse(BaseModel):
    tool: str
    entries: list[WatcherLogRow]


def _row_for(tool: str, store: WatcherStateStore) -> WatcherRow:
    status = store.get_status(tool)
    return WatcherRow(
        tool=tool,
        mechanism=classify_tool(tool),
        installed=status is not None,
        enabled=bool(status.enabled) if status else False,
        installed_at=status.installed_at if status else None,
        last_error=status.last_error if status else None,
        last_error_at=status.last_error_at if status else None,
        captured_count=store.total_captured(tool),
        last_captured_at=store.last_captured_at(tool),
    )


@router.get("/watchers", response_model=WatcherListResponse)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def list_watchers(request: Request) -> WatcherListResponse:
    """Return one row per known tool with its install/capture status."""
    store = _store()
    return WatcherListResponse(watchers=[_row_for(tool, store) for tool in ALL_TOOLS])


@router.get("/watchers/{tool}", response_model=WatcherRow)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_watcher(request: Request, tool: str) -> WatcherRow:
    if tool not in ALL_TOOLS:
        raise HTTPException(status_code=404, detail=f"unknown tool {tool!r}")
    return _row_for(tool, _store())


@router.patch("/watchers/{tool}", response_model=WatcherRow)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def update_watcher(request: Request, tool: str, payload: WatcherUpdate) -> WatcherRow:
    if tool not in ALL_TOOLS:
        raise HTTPException(status_code=404, detail=f"unknown tool {tool!r}")
    store = _store()
    store.set_enabled(tool, payload.enabled)
    return _row_for(tool, store)


@router.post("/watchers/{tool}/install", response_model=WatcherActionResponse)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def install_watcher(request: Request, tool: str) -> WatcherActionResponse:
    if tool not in INSTALLABLE_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"tool {tool!r} does not support automatic install",
        )
    result = install(tool, _store())
    return WatcherActionResponse(tool=result.tool, changed=result.changed, message=result.message)


@router.post("/watchers/{tool}/uninstall", response_model=WatcherActionResponse)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def uninstall_watcher(request: Request, tool: str) -> WatcherActionResponse:
    if tool not in INSTALLABLE_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=f"tool {tool!r} does not support automatic uninstall",
        )
    result = uninstall(tool, _store())
    return WatcherActionResponse(tool=result.tool, changed=result.changed, message=result.message)


@router.get("/watchers/{tool}/logs", response_model=WatcherLogsResponse)
@limiter.limit(lambda: f"{settings.rate_limit_default}/minute")
async def get_watcher_logs(
    request: Request,
    tool: str,
    limit: int = 50,
) -> WatcherLogsResponse:
    if tool not in ALL_TOOLS:
        raise HTTPException(status_code=404, detail=f"unknown tool {tool!r}")
    entries = _store().tail_logs(tool, limit=max(1, min(limit, 500)))
    return WatcherLogsResponse(
        tool=tool,
        entries=[
            WatcherLogRow(created_at=entry.created_at, level=entry.level, message=entry.message)
            for entry in entries
        ],
    )
