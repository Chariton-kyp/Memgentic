"""Predicate + entity normalisation edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from memgentic.graph.extractor import _fuzzy_ratio, _normalize_predicate, _resolve_entity
from memgentic.graph.temporal import Chronograph


@pytest.fixture()
async def chronograph(tmp_path: Path):
    cg = Chronograph(tmp_path / "cg.sqlite")
    await cg.initialize()
    yield cg
    await cg.close()


def test_predicate_snake_case_conversion():
    assert _normalize_predicate("Works On") == "works_on"
    assert _normalize_predicate("is-a") == "is_a"
    assert _normalize_predicate("  Prefers  ") == "prefers"
    assert _normalize_predicate("depends/on") == "depends_on"
    assert _normalize_predicate("") == "related_to"
    assert _normalize_predicate("___a__b___") == "a_b"


def test_fuzzy_ratio_is_100_for_identical():
    assert _fuzzy_ratio("Kai Wu", "Kai Wu") >= 99


def test_fuzzy_ratio_is_low_for_unrelated():
    assert _fuzzy_ratio("Helios", "Strawberry") < 70


async def test_resolve_entity_falls_back_when_no_match(chronograph: Chronograph):
    await chronograph.add_entity("Kai", aliases=["Kai Wu"])
    resolved = await chronograph.get_entity("Kai")
    assert resolved is not None
    # A new token should not be mapped to an existing entity when nothing is
    # close enough to the configured threshold.
    result = await _resolve_entity("Zelda Octavia Fitzgerald", chronograph)
    assert result == "Zelda Octavia Fitzgerald"


async def test_resolve_entity_matches_close_alias(chronograph: Chronograph):
    await chronograph.add_entity("Orion", aliases=["Orion Project"])
    result = await _resolve_entity("orion project", chronograph)
    # Should map back to the canonical "Orion" name.
    assert result == "Orion"


async def test_predicates_are_normalised_when_stored(chronograph: Chronograph):
    triple = await chronograph.add_triple("A", "  Works  ON  ", "B")
    assert triple.predicate == "works_on"
