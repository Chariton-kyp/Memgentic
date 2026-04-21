"""LLM-driven persona bootstrap.

Scans recent memories (or top skills) and asks an LLM to propose a
Persona card. The LLM must return a Persona-shaped object; we validate
the result against :mod:`memgentic.persona.schema` before handing it
back. If no LLM is configured, or the LLM returns malformed output,
``bootstrap`` returns ``None`` so the caller can surface a clear error.
"""

from __future__ import annotations

import json
from typing import Literal

import structlog

from memgentic.config import MemgenticSettings
from memgentic.config import settings as default_settings
from memgentic.persona.schema import Persona, PersonaMetadata, validate
from memgentic.storage.metadata import MetadataStore

logger = structlog.get_logger()

BOOTSTRAP_LIMIT_DEFAULT = 100

BootstrapSource = Literal["recent", "skills"]


_SYSTEM_PROMPT = """\
You are an assistant that writes a short, structured "persona card" for an AI
agent. Given a snapshot of the user's recent AI-assistant interactions (or
their most-used skills), propose a persona describing how the agent should
introduce itself in future sessions.

Return a JSON object that matches the Persona schema. Keys:
- version (int, always 1)
- identity: { name, role, tone, pronouns?, voice_sample? }
- people: [ { name, relationship, preferences[], do_not[] } ]
- projects: [ { name, status, stack[], tldr } ]
- preferences: { remember[], avoid[] }
- metadata: { workspace_inherit: false, generated_by: "bootstrap" }

Rules:
- NEVER invent facts. If the snapshot doesn't support a field, leave it out or empty.
- Keep identity.name generic ("Assistant", "Atlas", etc.) unless the user has named the agent.
- Prefer short strings (under 80 characters).
- Return ONLY the JSON object, no prose, no code fences.
"""


def _build_user_prompt(snippets: list[str], mode: BootstrapSource) -> str:
    """Render the user-side prompt from a list of memory/skill snippets."""
    header = (
        "Recent memories (newest first):"
        if mode == "recent"
        else "Top user skills (most used first):"
    )
    body = "\n".join(f"- {s}" for s in snippets) if snippets else "(no content available)"
    return f"{header}\n{body}\n\nPropose the Persona JSON now."


async def _fetch_recent_snippets(store: MetadataStore, limit: int) -> list[str]:
    """Return up to ``limit`` recent memory summaries as short strings."""
    memories = await store.get_memories_by_filter(limit=limit, offset=0)
    snippets: list[str] = []
    for mem in memories:
        content = (mem.content or "").replace("\n", " ").strip()
        if not content:
            continue
        if len(content) > 280:
            content = content[:277] + "..."
        platform = mem.source.platform.value if mem.source else "unknown"
        ctype = mem.content_type.value if mem.content_type else "fact"
        snippets.append(f"[{platform}/{ctype}] {content}")
    return snippets


async def _fetch_top_skills(store: MetadataStore, limit: int) -> list[str]:
    """Return up to ``limit`` skill name/description pairs as short strings."""
    try:
        skills = await store.get_skills()
    except Exception as exc:  # pragma: no cover — storage wiring issues
        logger.warning("persona.bootstrap.skills_unavailable", error=str(exc))
        return []
    snippets: list[str] = []
    for skill in skills[:limit]:
        desc = (skill.description or "").replace("\n", " ").strip()
        if len(desc) > 160:
            desc = desc[:157] + "..."
        snippets.append(f"{skill.name}: {desc}" if desc else skill.name)
    return snippets


def _strip_code_fence(text: str) -> str:
    """Remove ```json ... ``` fences if the LLM adds them anyway."""
    t = text.strip()
    if t.startswith("```"):
        # drop first line (``` or ```json) and the trailing ```
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _parse_llm_json(text: str) -> dict | None:
    """Attempt to parse a JSON object out of an LLM response."""
    candidate = _strip_code_fence(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("persona.bootstrap.non_json", preview=candidate[:160])
        return None
    if not isinstance(data, dict):
        return None
    return data


async def bootstrap(
    *,
    source: BootstrapSource = "recent",
    limit: int = BOOTSTRAP_LIMIT_DEFAULT,
    store: MetadataStore | None = None,
    llm_client=None,  # type: ignore[assignment]
    settings_override: MemgenticSettings | None = None,
) -> Persona | None:
    """Propose a Persona by asking an LLM to summarise recent activity.

    Args:
        source: ``"recent"`` scans the last N memories; ``"skills"`` uses
            the user's saved skills list.
        limit: Number of items to feed the LLM. Defaults to 100.
        store: Optional pre-initialised metadata store (tests).
        llm_client: Optional pre-built LLM client (tests).
        settings_override: Optional settings instance (tests).

    Returns:
        A validated :class:`Persona`, or ``None`` when no LLM is
        configured or the LLM response failed to parse/validate.
    """
    cfg = settings_override or default_settings

    owns_store = store is None
    if store is None:
        store = MetadataStore(cfg.sqlite_path)
        await store.initialize()

    try:
        if source == "skills":
            snippets = await _fetch_top_skills(store, limit)
        else:
            snippets = await _fetch_recent_snippets(store, limit)
    finally:
        if owns_store:
            await store.close()

    # Lazy-import the LLM client so ``memgentic.persona`` stays usable
    # when the [intelligence] extras aren't installed (e.g. pure-CLI
    # builds that only call ``show``/``validate``).
    if llm_client is None:
        try:
            from memgentic.processing.llm import LLMClient
        except ImportError:
            logger.warning("persona.bootstrap.llm_extras_missing")
            return None
        llm_client = LLMClient(cfg)

    if not getattr(llm_client, "available", False):
        logger.info("persona.bootstrap.no_llm")
        return None

    prompt = f"{_SYSTEM_PROMPT}\n\n{_build_user_prompt(snippets, source)}"

    raw = await llm_client.generate(prompt)
    if not raw:
        logger.info("persona.bootstrap.empty_response")
        return None

    data = _parse_llm_json(raw)
    if data is None:
        return None

    # Force sane defaults on the metadata block — the LLM shouldn't be
    # trusted to set provenance fields.
    data.setdefault("version", 1)
    data["metadata"] = PersonaMetadata(
        workspace_inherit=bool(data.get("metadata", {}).get("workspace_inherit", False)),
        generated_by="bootstrap",
    ).model_dump(mode="json")

    try:
        persona = validate(data)
    except Exception as exc:
        logger.warning("persona.bootstrap.invalid_shape", error=str(exc))
        return None
    return persona


__all__ = ["BOOTSTRAP_LIMIT_DEFAULT", "BootstrapSource", "bootstrap"]
