"""Pydantic models for the Persona card.

The schema deliberately mirrors the YAML layout documented in
``05-PLAN-PERSONA.md §2``. A ``version`` field sits at the top so future
migrations have a stable anchor; everything else is optional, with safe
defaults, so a minimally-specified persona still validates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class IdentityBlock(BaseModel):
    """The agent's self-concept — name, role, tone, and voice anchors."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Agent's self-concept name (e.g., 'Atlas')")
    role: str | None = Field(default=None, description="One-line role description")
    tone: str | None = Field(default=None, description="Voice/tone cues")
    pronouns: str | None = Field(default=None, description="Preferred pronouns")
    voice_sample: str | None = Field(
        default=None,
        description="Optional short prose sample for style anchoring",
    )


class Person(BaseModel):
    """A person the agent knows (creator, partner, collaborator, etc.)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Person's name or handle")
    relationship: str | None = Field(
        default=None,
        description="Relationship to the agent (e.g., 'creator', 'partner')",
    )
    preferences: list[str] = Field(
        default_factory=list,
        description="Things this person prefers (free-form tags)",
    )
    do_not: list[str] = Field(
        default_factory=list,
        description="Things the agent must not do regarding this person",
    )


class Project(BaseModel):
    """An active or archived project the agent tracks."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Project name")
    status: Literal["active", "paused", "archived"] = Field(
        default="active",
        description="Project status",
    )
    stack: list[str] = Field(
        default_factory=list,
        description="Tech stack tags (e.g., ['next.js', 'postgres'])",
    )
    tldr: str | None = Field(default=None, description="One-line summary")


class PreferencesBlock(BaseModel):
    """Behavioral preferences — what the agent should pay attention to or skip."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    remember: list[str] = Field(
        default_factory=list,
        description="Categories the agent should remember (e.g., 'decisions with rationale')",
    )
    avoid: list[str] = Field(
        default_factory=list,
        description="Behaviors the agent should avoid",
    )


class PersonaMetadata(BaseModel):
    """Provenance and workspace-inheritance hints."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    workspace_inherit: bool = Field(
        default=False,
        description=(
            "When true, a workspace-level persona will be merged on top of the local "
            "persona. Currently inert; activated when Phase C (workspaces) ships."
        ),
    )
    updated_at: datetime | None = Field(
        default=None,
        description="When the persona was last written (UTC ISO-8601)",
    )
    generated_by: Literal["bootstrap", "manual", "edited"] = Field(
        default="manual",
        description="How the current persona was created",
    )


class Persona(BaseModel):
    """The full Persona card — T0 of the Recall Tiers stack."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    version: int = Field(
        default=1,
        description="Schema version — bump when breaking changes land",
        ge=1,
    )
    identity: IdentityBlock
    people: list[Person] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    preferences: PreferencesBlock = Field(default_factory=PreferencesBlock)
    metadata: PersonaMetadata = Field(default_factory=PersonaMetadata)


CURRENT_SCHEMA_VERSION: int = 1
"""The schema version this module writes and natively understands."""


def validate(data: Any) -> Persona:
    """Validate a dict (parsed YAML) against the Persona schema.

    Raises:
        pydantic.ValidationError: when the shape is malformed.
        ValueError: when ``version`` is present but newer than what this
            build understands.
    """
    if isinstance(data, Persona):
        return data
    if not isinstance(data, dict):
        raise ValueError(
            f"Persona YAML must be a mapping at the top level, got {type(data).__name__}"
        )
    version = data.get("version", CURRENT_SCHEMA_VERSION)
    if isinstance(version, int) and version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Persona schema version {version} is newer than this build understands "
            f"(max {CURRENT_SCHEMA_VERSION}). Upgrade Memgentic."
        )
    return Persona.model_validate(data)


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "IdentityBlock",
    "Persona",
    "PersonaMetadata",
    "Person",
    "PreferencesBlock",
    "Project",
    "ValidationError",
    "validate",
]
