"""End-to-end Chronograph flow — propose, accept, query."""

from __future__ import annotations

from pathlib import Path

import pytest

from memgentic.graph.extractor import extract_triples, store_proposed
from memgentic.graph.temporal import Chronograph
from memgentic.models import Memory, Platform, SourceMetadata


class _StubLLM:
    available = True

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def generate_structured(self, prompt: str, schema):
        return schema.model_validate(self._payload)

    async def generate(self, prompt: str) -> str:
        return ""


@pytest.fixture()
async def chronograph(tmp_path: Path):
    cg = Chronograph(tmp_path / "cg.sqlite")
    await cg.initialize()
    yield cg
    await cg.close()


def _make_memory(idx: int) -> Memory:
    source = SourceMetadata(platform=Platform.CLAUDE_CODE)
    return Memory(
        id=f"mem-{idx:03d}",
        content=f"Memory #{idx} — Kai works on Orion since 2025-06-01.",
        source=source,
    )


async def test_ingest_propose_accept_query(chronograph: Chronograph):
    llm = _StubLLM(
        {
            "triples": [
                {
                    "subject": "Kai",
                    "predicate": "works_on",
                    "object": "Orion",
                    "valid_from": "2025-06-01",
                    "confidence": 0.9,
                }
            ]
        }
    )

    memories = [_make_memory(i) for i in range(10)]
    ids: list[str] = []
    for mem in memories:
        triples = await extract_triples(mem, llm, chronograph)
        stored = await store_proposed(triples, chronograph)
        ids.extend(stored)

    # All the memories propose the same fact -> deduped to one triple row
    proposed = await chronograph.list_proposed(limit=50)
    assert len(proposed) == 1

    # Before acceptance the fact does not surface in query results
    assert await chronograph.query_entity("Kai") == []

    # Accept it
    triple_id = proposed[0].id
    accepted = await chronograph.accept(triple_id, user_id="user-1")
    assert accepted.status == "accepted"

    # Query now returns the accepted fact
    hits = await chronograph.query_entity("Kai")
    assert len(hits) == 1
    assert hits[0].object == "orion"
    # Source memory id from the first store is preserved
    assert hits[0].source_memory_id in {m.id for m in memories}

    stats = await chronograph.stats()
    assert stats["accepted"] == 1
    assert stats["proposed"] == 0


async def test_contract_get_chronograph_is_importable(tmp_path: Path):
    """T4 Atlas contract: ``from memgentic.graph import get_chronograph`` works."""
    from memgentic.graph import Entity as PublicEntity
    from memgentic.graph import Triple as PublicTriple
    from memgentic.graph import get_chronograph, reset_chronograph_cache

    reset_chronograph_cache()
    cg = await get_chronograph(tmp_path / "cg.sqlite")
    assert isinstance(cg, type(cg))  # just exercise the symbol
    await cg.add_triple("Alice", "works_on", "Orion", status="accepted")
    triples = await cg.query_entity("Alice")
    assert len(triples) == 1
    assert isinstance(triples[0], PublicTriple)
    ent = await cg.get_entity("Alice")
    assert isinstance(ent, PublicEntity)
    reset_chronograph_cache()
