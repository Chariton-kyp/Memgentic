"""Schema-level tests for the Persona card."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from memgentic.persona.schema import (
    CURRENT_SCHEMA_VERSION,
    IdentityBlock,
    Person,
    Persona,
    Project,
    validate,
)


def test_minimal_persona_validates():
    """Only an ``identity.name`` is required to produce a valid persona."""
    p = Persona(identity=IdentityBlock(name="Atlas"))
    assert p.identity.name == "Atlas"
    assert p.version == 1
    assert p.people == []
    assert p.projects == []
    assert p.preferences.remember == []


def test_full_persona_round_trip_via_validate():
    """A dict roundtrip through :func:`validate` produces the same model."""
    data = {
        "version": 1,
        "identity": {"name": "Atlas", "role": "AI for Alice", "tone": "warm"},
        "people": [{"name": "Alice", "relationship": "creator", "preferences": ["PostgreSQL"]}],
        "projects": [{"name": "journaling-app", "status": "active", "stack": ["next.js"]}],
        "preferences": {"remember": ["decisions"], "avoid": ["apologies"]},
        "metadata": {"workspace_inherit": True, "generated_by": "bootstrap"},
    }
    persona = validate(data)
    assert persona.identity.role == "AI for Alice"
    assert persona.people[0].preferences == ["PostgreSQL"]
    assert persona.projects[0].status == "active"
    assert persona.metadata.workspace_inherit is True
    assert persona.metadata.generated_by == "bootstrap"


def test_validate_rejects_non_mapping():
    with pytest.raises(ValueError, match="mapping"):
        validate(["not", "a", "dict"])


def test_validate_rejects_missing_identity_name():
    with pytest.raises(ValidationError):
        validate({"identity": {}})


def test_validate_rejects_newer_schema_version():
    with pytest.raises(ValueError, match="newer than"):
        validate({"version": CURRENT_SCHEMA_VERSION + 1, "identity": {"name": "x"}})


def test_validate_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError):
        validate({"identity": {"name": "x"}, "unexpected_field": "nope"})


def test_project_status_is_constrained():
    with pytest.raises(ValidationError):
        Project(name="p", status="wip")  # type: ignore[arg-type]


def test_generated_by_is_constrained():
    with pytest.raises(ValidationError):
        Persona.model_validate(
            {
                "identity": {"name": "x"},
                "metadata": {"generated_by": "auto-magic"},
            }
        )


def test_person_defaults_empty_collections():
    person = Person(name="Alice")
    assert person.preferences == []
    assert person.do_not == []


def test_validate_passes_through_persona_instance():
    """Passing a :class:`Persona` directly returns it unchanged."""
    p = Persona(identity=IdentityBlock(name="Atlas"))
    assert validate(p) is p
