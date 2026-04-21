"""Unit tests for the Chronograph bitemporal triple store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from memgentic.graph import Entity, Triple, get_chronograph
from memgentic.graph.temporal import (
    Chronograph,
    _normalize_entity_id,
    _triple_hash,
    reset_chronograph_cache,
)


@pytest.fixture()
async def chronograph(tmp_path: Path) -> Chronograph:
    cg = Chronograph(tmp_path / "cg.sqlite")
    await cg.initialize()
    yield cg
    await cg.close()


async def test_migration_is_idempotent(tmp_path: Path):
    path = tmp_path / "cg.sqlite"
    first = Chronograph(path)
    await first.initialize()
    await first.close()
    # Opening again should not apply a second migration or raise
    second = Chronograph(path)
    await second.initialize()
    stats = await second.stats()
    await second.close()
    assert stats["triples"] == 0


async def test_add_entity_roundtrip(chronograph: Chronograph):
    entity = await chronograph.add_entity("Kai", type="person", aliases=["K."])
    assert isinstance(entity, Entity)
    assert entity.id == "kai"
    assert entity.name == "Kai"
    assert "K." in entity.aliases

    # Re-adding with new metadata merges, doesn't duplicate
    again = await chronograph.add_entity("Kai", aliases=["Kai Wu"], properties={"role": "lead"})
    assert again.id == "kai"
    assert set(again.aliases) >= {"K.", "Kai Wu"}
    assert again.properties.get("role") == "lead"


async def test_add_triple_normalizes_predicate(chronograph: Chronograph):
    triple = await chronograph.add_triple("Kai", "Works On", "Orion", status="accepted")
    assert isinstance(triple, Triple)
    assert triple.predicate == "works_on"
    assert triple.status == "accepted"


async def test_query_entity_respects_validity_window(chronograph: Chronograph):
    await chronograph.add_triple(
        "Kai",
        "works_on",
        "Orion",
        valid_from=date(2025, 6, 1),
        status="accepted",
    )
    # Fact known as-of 2025-12-01 (within window)
    hits = await chronograph.query_entity("Kai", as_of=date(2025, 12, 1))
    assert len(hits) == 1

    # Fact not yet valid at 2020-01-01
    past = await chronograph.query_entity("Kai", as_of=date(2020, 1, 1))
    assert past == []


async def test_query_entity_filters_status(chronograph: Chronograph):
    await chronograph.add_triple("Kai", "owns", "Idea", status="proposed")
    assert await chronograph.query_entity("Kai") == []  # default: accepted
    proposed = await chronograph.query_entity("Kai", status="proposed")
    assert len(proposed) == 1
    any_status = await chronograph.query_entity("Kai", status="any")
    assert len(any_status) == 1


async def test_invalidate_closes_validity_window(chronograph: Chronograph):
    await chronograph.add_triple(
        "Kai",
        "works_on",
        "Orion",
        valid_from=date(2025, 6, 1),
        status="accepted",
    )
    await chronograph.invalidate("Kai", "works_on", "Orion", ended=date(2026, 3, 1))

    # Inside window (before invalidation date) still returns the triple
    during = await chronograph.query_entity("Kai", as_of=date(2025, 12, 1))
    assert len(during) == 1

    # After invalidation the fact is no longer valid
    after = await chronograph.query_entity("Kai", as_of=date(2026, 4, 1))
    assert after == []


async def test_accept_reject_cycle(chronograph: Chronograph):
    triple = await chronograph.add_triple("Kai", "prefers", "python", status="proposed")
    assert triple.status == "proposed"

    accepted = await chronograph.accept(triple.id, user_id="user-1")
    assert accepted.status == "accepted"
    assert accepted.confidence == 1.0
    assert accepted.accepted_by == "user-1"

    # Accepting again is idempotent
    again = await chronograph.accept(triple.id)
    assert again.status == "accepted"

    rejected = await chronograph.reject(triple.id)
    assert rejected.status == "rejected"


async def test_edit_non_identity_fields(chronograph: Chronograph):
    triple = await chronograph.add_triple("Kai", "prefers", "python", status="proposed")
    updated = await chronograph.edit(triple.id, confidence=0.9)
    assert updated.id == triple.id
    assert updated.confidence == pytest.approx(0.9)


async def test_edit_identity_changes_id(chronograph: Chronograph):
    triple = await chronograph.add_triple("Kai", "works_on", "Orion", status="proposed")
    edited = await chronograph.edit(triple.id, predicate="led")
    assert edited.id != triple.id
    assert edited.predicate == "led"
    # old id is gone
    assert await chronograph.get_triple(triple.id) is None


async def test_timeline_returns_chronological_order(chronograph: Chronograph):
    await chronograph.add_triple(
        "Kai", "works_on", "Orion", valid_from=date(2024, 1, 1), status="accepted"
    )
    await chronograph.add_triple(
        "Kai", "works_on", "Helios", valid_from=date(2026, 1, 1), status="accepted"
    )
    timeline = await chronograph.timeline(entity="Kai")
    assert [t.object for t in timeline] == ["orion", "helios"]


async def test_list_proposed_queue_only(chronograph: Chronograph):
    await chronograph.add_triple("A", "x", "B", status="proposed")
    await chronograph.add_triple("A", "y", "B", status="accepted")
    proposed = await chronograph.list_proposed()
    assert len(proposed) == 1
    assert proposed[0].status == "proposed"


async def test_stats_counts_by_status(chronograph: Chronograph):
    await chronograph.add_triple("A", "x", "B", status="proposed")
    await chronograph.add_triple("A", "y", "C", status="accepted")
    stats = await chronograph.stats()
    assert stats["entities"] == 3  # a, b, c
    assert stats["triples"] == 2
    assert stats["proposed"] == 1
    assert stats["accepted"] == 1


async def test_triple_hash_is_stable():
    h1 = _triple_hash("kai", "works_on", "orion", date(2025, 6, 1))
    h2 = _triple_hash("kai", "works_on", "orion", date(2025, 6, 1))
    assert h1 == h2
    assert h1 != _triple_hash("kai", "works_on", "orion", None)


async def test_normalize_entity_id_is_lowercased():
    assert _normalize_entity_id("  Kai ") == "kai"
    assert _normalize_entity_id("Orion Project") == "orion project"


async def test_get_chronograph_is_cached(tmp_path: Path):
    reset_chronograph_cache()
    a = await get_chronograph(tmp_path / "cg.sqlite")
    b = await get_chronograph(tmp_path / "cg.sqlite")
    assert a is b
    reset_chronograph_cache()
