"""Tests for the fallback persona."""

from __future__ import annotations

from memgentic.persona import default_persona, render_t0
from memgentic.persona.schema import Persona


def test_default_persona_is_valid_persona():
    p = default_persona()
    assert isinstance(p, Persona)
    assert p.identity.name == "Assistant"
    assert p.version == 1


def test_default_persona_is_independent_per_call():
    """Repeated calls should not share mutable state."""
    a = default_persona()
    b = default_persona()
    assert a is not b
    assert a.preferences is not b.preferences
    # Mutating one default must not leak into another.
    a.preferences.remember.append("only on a")
    assert b.preferences.remember == []


def test_render_t0_under_200_tokens_for_default():
    text = render_t0(default_persona())
    # GPT-style token estimator: ~1 token per 4 characters
    approx_tokens = len(text) // 4
    assert approx_tokens < 200


def test_render_t0_under_200_tokens_for_rich_persona():
    """A reasonably-populated persona must still fit the T0 budget."""
    from memgentic.persona.schema import (
        IdentityBlock,
        Person,
        PreferencesBlock,
        Project,
    )

    p = Persona(
        identity=IdentityBlock(
            name="Atlas", role="Personal AI assistant for Alice", tone="warm, direct"
        ),
        people=[
            Person(name="Alice", relationship="creator"),
            Person(name="Bob", relationship="Alice's partner"),
            Person(name="Cara", relationship="teammate"),
        ],
        projects=[
            Project(name="journaling-app", status="active", stack=["next.js"]),
            Project(name="memgentic", status="active", stack=["python", "fastapi"]),
        ],
        preferences=PreferencesBlock(
            remember=["code stack choices", "naming conventions", "decisions with rationale"],
            avoid=["apology-heavy responses", "suggest unrelated refactors"],
        ),
    )
    text = render_t0(p)
    assert len(text) // 4 < 200


def test_render_t0_uses_fallback_when_none():
    text = render_t0(None)
    assert "Persona" in text
    assert "Assistant" in text
