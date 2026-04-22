"""Response formatters shared by MCP tools added in the expansion pass.

Kept deliberately small — each helper produces a stable shape so snapshot
tests can pin on it. The MCP server is the only expected caller.
"""

from __future__ import annotations

from datetime import UTC, datetime


def preview_text(text: str | None, *, length: int = 200) -> str:
    """Return a single-line preview truncated with an ellipsis when cut."""
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= length:
        return collapsed
    return collapsed[: length - 1].rstrip() + "…"


def utc_now_iso() -> str:
    """Return a naive-free UTC timestamp formatted to ISO 8601."""
    return datetime.now(UTC).isoformat()


__all__ = ["preview_text", "utc_now_iso"]
