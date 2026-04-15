"""Context generator — produces standalone memory context files.

Generates a `.memgentic-context.md` file with recent decisions, learnings,
and topics. This file is standalone (never injected into CLAUDE.md or other
tool files). Tools that don't support MCP can be configured to read it.

Also provides a compact briefing function used by the SessionStart hook.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from memgentic.storage.metadata import MetadataStore

logger = structlog.get_logger()


async def generate_briefing(
    metadata_store: MetadataStore,
    *,
    hours: int = 48,
    limit: int = 5,
) -> str:
    """Generate a compact briefing of recent memories.

    Returns a short text suitable for hook additionalContext injection.
    Queries SQLite only — no embedding or vector search needed.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    memories = await metadata_store.get_memories_since(since, limit=limit)

    if not memories:
        # Fallback: surface the most important all-time memories so a fresh
        # session still gets useful context when nothing recent exists.
        memories = await metadata_store.get_top_memories(limit=limit)
        if not memories:
            return ""

    lines = []
    for m in memories:
        ct = m.content_type.value
        raw = m.content[:120].replace("\n", " ").strip()
        if len(m.content) > 120:
            last_space = raw.rfind(" ")
            preview = (raw[:last_space] + "...") if last_space > 50 else raw + "..."
        else:
            preview = raw
        platform = m.source.platform.value
        date = m.created_at.strftime("%Y-%m-%d")
        lines.append(f"[{ct}] {preview} | {platform} | {date}")

    # Top topics
    all_topics: list[str] = []
    for m in memories:
        all_topics.extend(m.topics)
    top_topics = [t for t, _ in Counter(all_topics).most_common(5)]

    result = "\n".join(lines)
    if top_topics:
        result += f"\n\nActive topics: {', '.join(top_topics)}"

    return result


async def generate_context_file(
    metadata_store: MetadataStore,
    output_path: Path,
    *,
    hours: int = 72,
    max_per_type: int = 5,
) -> bool:
    """Generate a standalone .memgentic-context.md file.

    This file can be referenced by any AI tool that supports reading
    context files (e.g., Aider --read, Cursor rules include).
    Never modifies existing tool config files.

    Returns True on success.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    memories = await metadata_store.get_memories_since(since, limit=50)

    if not memories:
        if output_path.exists():
            output_path.unlink()
        return True

    # Group by content type
    groups: dict[str, list[str]] = {
        "decision": [],
        "learning": [],
        "preference": [],
        "bug_fix": [],
        "other": [],
    }

    for m in memories:
        ct = m.content_type.value
        raw = m.content[:140].replace("\n", " ").strip()
        if len(m.content) > 140:
            last_space = raw.rfind(" ")
            preview = (raw[:last_space] + "...") if last_space > 50 else raw + "..."
        else:
            preview = raw
        platform = m.source.platform.value
        date = m.created_at.strftime("%Y-%m-%d")
        line = f"- [{date}] {preview} ({platform})"
        group = ct if ct in groups else "other"
        groups[group].append(line)

    # Topics
    all_topics: list[str] = []
    for m in memories:
        all_topics.extend(m.topics)
    top_topics = [t for t, _ in Counter(all_topics).most_common(10)]

    # Platform counts
    platform_counts = Counter(m.source.platform.value for m in memories)

    lines = [
        "# Memgentic Memory Context",
        "",
        f"Auto-generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC "
        f"| {len(memories)} memories from last {hours}h",
        "",
    ]

    section_names = {
        "decision": "Recent Decisions",
        "learning": "Recent Learnings",
        "preference": "Preferences & Conventions",
        "bug_fix": "Recent Bug Fixes",
        "other": "Other Context",
    }

    for key, title in section_names.items():
        items = groups[key][:max_per_type]
        if items:
            lines.append(f"## {title}")
            lines.extend(items)
            lines.append("")

    if top_topics:
        lines.append(f"**Active topics:** {', '.join(top_topics)}")
        lines.append("")

    if len(platform_counts) > 1:
        parts = [f"{p}: {c}" for p, c in platform_counts.most_common()]
        lines.append(f"**Sources:** {' | '.join(parts)}")
        lines.append("")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("context_generator.write_failed", error=str(e))
        return False
