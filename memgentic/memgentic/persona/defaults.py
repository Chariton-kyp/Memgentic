"""Fallback persona used when ``persona.yaml`` is missing.

The defaults are deliberately bland — Memgentic should feel useful without
any onboarding, but must not invent facts about the user. Run
``memgentic persona init`` to generate a richer, memory-informed card.
"""

from __future__ import annotations

from memgentic.persona.schema import IdentityBlock, Persona, PersonaMetadata


def default_persona() -> Persona:
    """Return a safe, empty Persona that validates cleanly.

    Used by the T0 render path when ``~/.memgentic/persona.yaml`` is
    missing, and as the starting point for ``memgentic persona edit``
    when the file has never been written.
    """
    return Persona(
        version=1,
        identity=IdentityBlock(
            name="Assistant",
            role="Memory-enabled AI assistant",
            tone="helpful, concise",
        ),
        metadata=PersonaMetadata(generated_by="manual"),
    )


__all__ = ["default_persona"]
