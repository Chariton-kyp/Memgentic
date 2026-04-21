"""Memgentic Persona — structured "who is this agent" card.

The persona is a versioned YAML file at ``~/.memgentic/persona.yaml`` that
replaces ad-hoc per-session identity blobs with a validatable, diffable,
machine-editable card. It is the T0 tier of the Recall Tiers stack — the
card the agent sees at the top of every session.

Public surface:

- :func:`load`     — read the persona file and return a :class:`Persona`
- :func:`save`     — atomic write + ``chmod 0600`` / ``0700`` (POSIX)
- :func:`bootstrap`— LLM-driven draft from recent memories
- :func:`validate` — schema check for an already-parsed dict/YAML string
- :func:`default_persona` — safe fallback when the file is missing

See :mod:`memgentic.persona.schema` for the data model and
:mod:`memgentic.persona.loader` for the on-disk format and locking.
"""

from __future__ import annotations

from memgentic.persona.bootstrap import bootstrap
from memgentic.persona.defaults import default_persona
from memgentic.persona.loader import (
    file_lock,
    get_persona_path,
    load,
    save,
)
from memgentic.persona.schema import (
    IdentityBlock,
    Person,
    Persona,
    PersonaMetadata,
    PreferencesBlock,
    Project,
    validate,
)


def load_or_default(path=None) -> Persona:
    """Load the persona, falling back to :func:`default_persona` on miss.

    This is the ergonomic helper the MCP tool and T0 tier use — they
    never want a ``None`` because T0 must always render something.
    """
    try:
        persona = load(path)
    except Exception:
        return default_persona()
    return persona or default_persona()


def render_t0(persona: Persona | None = None, *, max_people: int = 3, max_projects: int = 2) -> str:
    """Render the Persona as a compact T0 briefing (< 200 tokens).

    Token budget estimate uses the GPT-style ``len(text) // 4`` heuristic;
    the output is intentionally short so the wake-up tier stays within
    its ~100-token allowance.
    """
    p = persona or default_persona()
    lines: list[str] = []
    lines.append(f"# Persona — {p.identity.name}")
    if p.identity.role:
        lines.append(f"Role: {p.identity.role}")
    if p.identity.tone:
        lines.append(f"Tone: {p.identity.tone}")

    if p.people:
        ppl = ", ".join(
            f"{person.name}" + (f" ({person.relationship})" if person.relationship else "")
            for person in p.people[:max_people]
        )
        lines.append(f"People: {ppl}")

    if p.projects:
        projs = ", ".join(
            f"{proj.name}" + (f" [{proj.status}]" if proj.status != "active" else "")
            for proj in p.projects[:max_projects]
        )
        lines.append(f"Projects: {projs}")

    if p.preferences.remember:
        lines.append("Remember: " + "; ".join(p.preferences.remember[:3]))
    if p.preferences.avoid:
        lines.append("Avoid: " + "; ".join(p.preferences.avoid[:3]))

    return "\n".join(lines)


__all__ = [
    "IdentityBlock",
    "Persona",
    "PersonaMetadata",
    "PreferencesBlock",
    "Person",
    "Project",
    "bootstrap",
    "default_persona",
    "file_lock",
    "get_persona_path",
    "load",
    "load_or_default",
    "render_t0",
    "save",
    "validate",
]
