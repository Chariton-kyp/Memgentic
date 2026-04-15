"""LLM-based skill synthesis — turn a list of memories into a reusable skill.

Given a batch of related memories, we ask the configured LLM to:

1. Identify the common patterns/procedures in the memories
2. Synthesize them into reusable SKILL.md instructions
3. Pick a kebab-case name and a one-line description
4. Surface the most relevant tags

When no LLM is available we fall back to a deterministic naive concatenation so
that the endpoint keeps working in local/offline installs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

from memgentic.models import Memory

if TYPE_CHECKING:
    from memgentic.processing.llm import LLMClient

logger = structlog.get_logger()


class SkillSynthesisResult(BaseModel):
    """Structured LLM output for skill extraction."""

    name: str = Field(
        description=("Short kebab-case skill name (<=60 chars) summarising the skill")
    )
    description: str = Field(
        description="One-line description (120 chars max) of what the skill does"
    )
    content: str = Field(
        description=(
            "SKILL.md body in Markdown. Must be self-contained, written as "
            "reusable instructions for a future assistant."
        )
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Up to 10 short lowercase tags",
    )


_SKILL_EXTRACTION_PROMPT = (
    "You are distilling a set of AI conversation memories into a reusable "
    "SKILL.md file that another AI assistant will load as operating "
    "knowledge.\n\n"
    "Read the memories below and synthesize them into a single coherent "
    "skill document. Focus on:\n"
    "1. Identifying the common patterns, procedures, and conventions\n"
    "2. Rewriting them as reusable, imperative instructions for a future "
    "assistant (not as a conversation transcript)\n"
    "3. Keeping the content concise, actionable, and self-contained\n\n"
    "Return JSON with exactly these fields:\n"
    "- name: kebab-case skill name, max 60 chars\n"
    "- description: one-line description (<=120 chars) of what the skill does\n"
    "- content: the SKILL.md body (Markdown, reusable instructions only)\n"
    "- tags: up to 10 short lowercase tags\n\n"
    "Memories:\n"
    "---\n"
    "{memories}\n"
    "---\n"
)


def _format_memories_for_prompt(memories: list[Memory]) -> str:
    """Render memories into a compact prompt-friendly block."""
    lines: list[str] = []
    for idx, memory in enumerate(memories, start=1):
        snippet = memory.content.strip()
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "…"
        topics = ", ".join(memory.topics[:6]) if memory.topics else ""
        entities = ", ".join(memory.entities[:6]) if memory.entities else ""
        lines.append(f"[Memory {idx}]")
        if topics:
            lines.append(f"topics: {topics}")
        if entities:
            lines.append(f"entities: {entities}")
        lines.append(snippet)
        lines.append("")
    return "\n".join(lines).strip()


def _kebab_case(text: str, max_len: int = 60) -> str:
    """Coerce an arbitrary string into a safe kebab-case identifier."""
    lowered = text.strip().lower()
    kebab = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return kebab[:max_len] or "extracted-skill"


def _naive_fallback(memories: list[Memory]) -> dict:
    """Deterministic fallback used when no LLM is configured."""
    topics: list[str] = []
    for memory in memories:
        topics.extend(memory.topics)
    unique_topics: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        lowered = topic.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_topics.append(topic)

    name_parts = unique_topics[:3] if unique_topics else ["extracted-skill"]
    name = _kebab_case("-".join(name_parts))

    description = f"Auto-extracted from {len(memories)} memories"
    if unique_topics:
        description += f" covering {', '.join(unique_topics[:3])}"

    body_blocks = [m.content.strip() for m in memories if m.content.strip()]
    content = "\n\n---\n\n".join(body_blocks)

    return {
        "name": name,
        "description": description[:240],
        "content": content,
        "tags": unique_topics[:10],
    }


async def extract_skill_from_memories(
    memories: list[Memory],
    llm_client: LLMClient | None,
) -> dict:
    """Use an LLM (or deterministic fallback) to synthesize a structured skill.

    Returns a dict with keys ``name``, ``description``, ``content``, ``tags``.
    The caller is responsible for persisting the resulting skill.
    """
    if not memories:
        raise ValueError("extract_skill_from_memories requires at least one memory")

    if llm_client is None or not getattr(llm_client, "available", False):
        logger.info(
            "skill_extractor.fallback",
            reason="no_llm_client",
            memory_count=len(memories),
        )
        return _naive_fallback(memories)

    prompt = _SKILL_EXTRACTION_PROMPT.format(memories=_format_memories_for_prompt(memories))

    try:
        result = await llm_client.generate_structured(prompt, SkillSynthesisResult)
    except Exception as exc:  # defensive — LLMClient already catches, but be safe
        logger.warning(
            "skill_extractor.llm_failed",
            error=str(exc),
            memory_count=len(memories),
        )
        return _naive_fallback(memories)

    if not isinstance(result, SkillSynthesisResult):
        logger.info(
            "skill_extractor.fallback",
            reason="structured_output_missing",
            memory_count=len(memories),
        )
        return _naive_fallback(memories)

    # Normalize LLM output so downstream code always sees sane values
    name = (
        _kebab_case(result.name)
        if result.name
        else _kebab_case("-".join((memories[0].topics or ["extracted-skill"])[:3]))
    )
    description = (result.description or "").strip()[:240]
    content = (result.content or "").strip()
    if not content:
        content = _naive_fallback(memories)["content"]

    tags = [
        tag.strip().lower() for tag in (result.tags or []) if isinstance(tag, str) and tag.strip()
    ][:10]

    logger.info(
        "skill_extractor.llm_extracted",
        name=name,
        tag_count=len(tags),
        memory_count=len(memories),
    )
    return {
        "name": name,
        "description": description,
        "content": content,
        "tags": tags,
    }
