"""Pydantic input schemas for MCP tools added by the expansion pass.

Historically, MCP input models lived inline in :mod:`memgentic.mcp.server`
next to the tool that used them. The expansion pass adds four new tools
(`memgentic_dedupe_check`, `memgentic_overview`, `memgentic_refresh`,
`memgentic_watchers_status`) whose inputs live here so the server module
stays under one thousand lines of tool wiring and new tools have a clear
home.

Existing inline models are intentionally left untouched — the goal is to
establish a landing zone for new work, not to churn working code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DedupeCheckInput(BaseModel):
    """Input for :func:`memgentic_dedupe_check`."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(
        ...,
        description="Candidate content to check for near-duplicates before a write.",
        min_length=3,
        max_length=10000,
    )
    threshold: float = Field(
        default=0.90,
        description=(
            "Cosine-similarity cutoff. Matches with score ≥ threshold count as "
            "duplicates. Vector backend returns similarity (higher = closer)."
        ),
        ge=0.0,
        le=1.0,
    )
    limit: int = Field(
        default=5,
        description="Maximum number of near-duplicate matches to return.",
        ge=1,
        le=50,
    )
    scope: Literal["all", "session", "collection"] = Field(
        default="all",
        description=(
            "Search scope. 'all' spans every memory; 'session' and "
            "'collection' reserve surface for future filtering (currently "
            "behave as 'all')."
        ),
    )


class OverviewInput(BaseModel):
    """Input for :func:`memgentic_overview` (all fields optional)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    top_topics_limit: int = Field(
        default=10,
        description="Number of top topics to return, ranked by memory count.",
        ge=1,
        le=100,
    )


class WatchersStatusInput(BaseModel):
    """Input for :func:`memgentic_watchers_status`."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    include_disabled: bool = Field(
        default=True,
        description="If False, only currently-installed + enabled watchers are returned.",
    )


__all__ = [
    "DedupeCheckInput",
    "OverviewInput",
    "WatchersStatusInput",
]
