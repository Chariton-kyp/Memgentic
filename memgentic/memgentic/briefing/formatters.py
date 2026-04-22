"""Consistent tier text output for the Recall Tiers briefing.

Each formatter emits a short, agent-friendly header + bullet list with
one line per memory. The formatters are pure functions operating on
pre-fetched data — no I/O, no side effects — which makes them easy to
snapshot-test and keeps the tier classes thin.

Output style (plan §4)::

    ## T1 — Horizon
    [collection:auth]
      - decided Clerk over Auth0 (pricing) — 2026-02-01, pinned
      - Kai fixed OAuth refresh — 2026-02-08
    [skills:top]
      - debugging/pr-review (used 34x)
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from memgentic.briefing.scorer import ScoredMemory
from memgentic.briefing.token_budget import estimate_tokens
from memgentic.models import Memory

# Hard cap so one giant memory can't swallow the whole T1 budget.
_CONTENT_PREVIEW_CHARS = 160


def _preview(content: str, max_chars: int = _CONTENT_PREVIEW_CHARS) -> str:
    """Strip newlines and trim content to a single-line preview."""
    cleaned = " ".join(content.split())
    if len(cleaned) <= max_chars:
        return cleaned
    trimmed = cleaned[:max_chars]
    # Break on the last word boundary to avoid cutting mid-token.
    last_space = trimmed.rfind(" ")
    if last_space > max_chars // 2:
        trimmed = trimmed[:last_space]
    return trimmed + "..."


def _format_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d")


def _memory_line(memory: Memory, *, show_score: float | None = None) -> str:
    """Render a single memory as a bullet suitable for any tier."""
    date = _format_date(memory.created_at)
    pin_marker = ", pinned" if memory.is_pinned else ""
    suffix_parts = [p for p in (date, pin_marker.strip(", ")) if p]
    suffix = " — " + ", ".join(suffix_parts) if suffix_parts else ""
    score_str = f" [score {show_score:.2f}]" if show_score is not None else ""
    return f"  - {_preview(memory.content)}{suffix}{score_str}"


def format_persona_tier(
    *,
    rendered: str,
    fallback_hint: str | None = None,
) -> str:
    """Format the T0 Persona block.

    ``rendered`` is the pre-rendered T0 text from ``memgentic.persona``
    — we never re-implement Persona rendering here. ``fallback_hint``
    is appended when the on-disk persona was missing (the tier wrapper
    decides whether it was missing; this function just renders).
    """
    lines = ["## T0 — Persona", "", rendered.rstrip()]
    if fallback_hint:
        lines.append("")
        lines.append(f"_Hint: {fallback_hint}_")
    return "\n".join(lines)


def format_horizon_tier(
    *,
    scored: Iterable[ScoredMemory],
    collection_name: str | None = None,
    active_skills: list[dict[str, Any]] | None = None,
    empty_message: str | None = None,
) -> str:
    """Format the T1 Horizon block.

    ``scored`` is the already-selected set (post-MMR). We do not
    re-rank or filter here — the caller owns the selection logic.

    ``active_skills`` is an optional list of ``{"name": str, "usage": int}``
    dicts (usage may be 0 when we don't yet track invocations — in
    that case the ``(used Nx)`` suffix is dropped).
    """
    scored_list = list(scored)

    lines = ["## T1 — Horizon"]
    header = f"[collection:{collection_name}]" if collection_name else "[memories]"
    lines.append(header)

    if not scored_list:
        lines.append(
            "  - "
            + (
                empty_message
                or "No memories yet. Import conversations with `memgentic import-existing`."
            )
        )
    else:
        for sm in scored_list:
            lines.append(_memory_line(sm.memory, show_score=sm.score))

    if active_skills:
        lines.append("[skills:top]")
        for skill in active_skills[:3]:
            name = skill.get("name", "?")
            usage = skill.get("usage")
            if isinstance(usage, int) and usage > 0:
                lines.append(f"  - {name} (used {usage}x)")
            else:
                lines.append(f"  - {name}")

    return "\n".join(lines)


def format_orbit_tier(
    *,
    memories: Iterable[Memory],
    collection_name: str | None = None,
    topic: str | None = None,
    empty_message: str | None = None,
) -> str:
    """Format the T2 Orbit block (collection/topic-filtered recall)."""
    label_parts: list[str] = []
    if collection_name:
        label_parts.append(f"collection:{collection_name}")
    if topic:
        label_parts.append(f"topic:{topic}")
    label = ",".join(label_parts) if label_parts else "orbit"

    mem_list = list(memories)
    lines = ["## T2 — Orbit", f"[{label}]"]
    if not mem_list:
        lines.append("  - " + (empty_message or "No memories match this collection or topic."))
    else:
        for mem in mem_list:
            lines.append(_memory_line(mem))
    return "\n".join(lines)


def format_deep_recall_tier(
    *,
    results: Iterable[dict[str, Any]],
    query: str,
    empty_message: str | None = None,
) -> str:
    """Format the T3 Deep Recall block.

    ``results`` follows the ``hybrid_search`` / ``basic_search``
    output shape: ``{"id", "score", "payload": {...}}``. We pull
    what we need from the payload directly so this formatter works
    without a second database round-trip.
    """
    result_list = list(results)
    lines = ["## T3 — Deep Recall", f"[query:{query}]"]
    if not result_list:
        lines.append("  - " + (empty_message or f"No matches for: {query}"))
        return "\n".join(lines)

    for r in result_list:
        payload = r.get("payload") or {}
        content = payload.get("content", "")
        platform = payload.get("platform", "unknown")
        created = payload.get("created_at") or ""
        date = created[:10] if isinstance(created, str) and created else ""
        score = r.get("score")
        score_str = f" [score {float(score):.2f}]" if score is not None else ""
        suffix_parts = [p for p in (platform, date) if p]
        suffix = " — " + ", ".join(suffix_parts) if suffix_parts else ""
        lines.append(f"  - {_preview(content)}{suffix}{score_str}")
    return "\n".join(lines)


def format_atlas_tier(
    *,
    entity: str | None,
    neighbors: list[dict[str, Any]] | None,
    graph_empty: bool,
    missing_entity_hint: str | None = None,
    empty_graph_message: str | None = None,
) -> str:
    """Format the T4 Atlas block with three-way fallback.

    - ``graph_empty`` → static placeholder (plan §3, MVP stub).
    - ``entity`` missing but graph populated → short "provide entity" hint.
    - both present → render the neighbour list.
    """
    lines = ["## T4 — Atlas"]

    if graph_empty:
        lines.append(
            "  - "
            + (
                empty_graph_message
                or "Knowledge graph not yet populated — run `memgentic graph backfill`."
            )
        )
        return "\n".join(lines)

    if not entity:
        lines.append(
            "  - "
            + (
                missing_entity_hint
                or "Provide an entity (e.g. `--entity Kai`) to traverse the knowledge graph."
            )
        )
        return "\n".join(lines)

    lines.append(f"[entity:{entity}]")
    neighbours = neighbors or []
    if not neighbours:
        lines.append("  - Entity not found in the knowledge graph.")
        return "\n".join(lines)

    for n in neighbours[:15]:
        name = n.get("name", "?")
        node_type = n.get("type", "node")
        count = n.get("count", 0)
        depth = n.get("depth", 1)
        lines.append(f"  - {name} ({node_type}, hops={depth}, seen {count}x)")
    return "\n".join(lines)


def assemble(blocks: Iterable[str]) -> str:
    """Join pre-rendered tier blocks with a blank line between each.

    Empty / whitespace-only blocks are dropped so the final briefing
    doesn't have accidental double-blank separators.
    """
    parts: list[str] = []
    for block in blocks:
        if block and block.strip():
            parts.append(block.rstrip())
    return "\n\n".join(parts)


def count_tokens(text: str) -> int:
    """Re-export :func:`estimate_tokens` for convenience."""
    return estimate_tokens(text)


__all__ = [
    "assemble",
    "count_tokens",
    "format_atlas_tier",
    "format_deep_recall_tier",
    "format_horizon_tier",
    "format_orbit_tier",
    "format_persona_tier",
]
