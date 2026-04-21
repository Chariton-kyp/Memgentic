"""Unit tests for the Chronograph LLM triple extractor."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from memgentic.graph.extractor import (
    ExtractedTriples,
    ProposedTriple,
    extract_triples,
    store_proposed,
)
from memgentic.graph.temporal import Chronograph
from memgentic.models import Memory, Platform, SourceMetadata


class _StubLLM:
    """Fake LLM client that returns a canned structured response."""

    available = True

    def __init__(self, payload: dict | None = None, raw_text: str | None = None) -> None:
        self._payload = payload
        self._raw_text = raw_text
        self.structured_calls = 0
        self.generate_calls = 0

    async def generate_structured(self, prompt: str, schema):
        self.structured_calls += 1
        if self._payload is None:
            return None
        return schema.model_validate(self._payload)

    async def generate(self, prompt: str) -> str:
        self.generate_calls += 1
        return self._raw_text or ""


class _UnavailableLLM:
    available = False


def _make_memory(content: str = "Kai joined Orion on 2025-06-01") -> Memory:
    source = SourceMetadata(platform=Platform.CLAUDE_CODE)
    return Memory(content=content, source=source)


@pytest.fixture()
async def chronograph(tmp_path: Path):
    cg = Chronograph(tmp_path / "cg.sqlite")
    await cg.initialize()
    yield cg
    await cg.close()


async def test_extract_returns_empty_when_llm_unavailable(chronograph: Chronograph):
    memory = _make_memory()
    triples = await extract_triples(memory, _UnavailableLLM(), chronograph)
    assert triples == []


async def test_extract_parses_structured_output(chronograph: Chronograph):
    llm = _StubLLM(
        payload={
            "triples": [
                {
                    "subject": "Kai",
                    "predicate": "Works On",
                    "object": "Orion",
                    "valid_from": "2025-06-01",
                    "confidence": 0.9,
                },
                {
                    "subject": "Kai",
                    "predicate": "prefers",
                    "object": "Python",
                    "confidence": 0.8,
                },
            ]
        }
    )
    memory = _make_memory()
    triples = await extract_triples(memory, llm, chronograph)
    assert len(triples) == 2
    first, second = triples
    assert first.subject == "Kai"
    assert first.predicate == "works_on"  # normalised
    assert first.object == "Orion"
    assert first.valid_from == date(2025, 6, 1)
    assert first.confidence == pytest.approx(0.9)
    assert first.source_memory_id == memory.id
    assert second.valid_from is None


async def test_extract_falls_back_to_raw_text(chronograph: Chronograph):
    raw = """```json
    {"triples": [{"subject":"A","predicate":"likes","object":"B"}]}
    ```"""
    llm = _StubLLM(payload=None, raw_text=raw)
    memory = _make_memory()
    triples = await extract_triples(memory, llm, chronograph)
    assert len(triples) == 1
    assert triples[0].subject == "A"
    assert triples[0].predicate == "likes"
    assert triples[0].object == "B"


async def test_extract_rejects_malformed_json(chronograph: Chronograph):
    llm = _StubLLM(payload=None, raw_text="not even close to json")
    memory = _make_memory()
    triples = await extract_triples(memory, llm, chronograph)
    assert triples == []


async def test_extract_skips_incomplete_rows(chronograph: Chronograph):
    llm = _StubLLM(
        payload={
            "triples": [
                {"subject": "", "predicate": "knows", "object": "Anna"},
                {"subject": "Kai", "predicate": "", "object": "Orion"},
                {"subject": "Kai", "predicate": "knows", "object": ""},
                {"subject": "Kai", "predicate": "knows", "object": "Anna"},
            ]
        }
    )
    memory = _make_memory()
    triples = await extract_triples(memory, llm, chronograph)
    assert len(triples) == 1


async def test_extract_clamps_confidence(chronograph: Chronograph):
    llm = _StubLLM(
        payload={
            "triples": [
                {"subject": "A", "predicate": "p", "object": "B", "confidence": 2.5},
                {"subject": "C", "predicate": "p", "object": "D", "confidence": -0.5},
            ]
        }
    )
    memory = _make_memory()
    triples = await extract_triples(memory, llm, chronograph)
    assert triples[0].confidence == 1.0
    assert triples[1].confidence == 0.0


async def test_store_proposed_persists_and_returns_ids(chronograph: Chronograph):
    proposed = [
        ProposedTriple(
            subject="Kai",
            predicate="works_on",
            object="Orion",
            valid_from=date(2025, 6, 1),
            confidence=0.9,
            source_memory_id="mem-1",
        )
    ]
    ids = await store_proposed(proposed, chronograph)
    assert len(ids) == 1
    proposed_list = await chronograph.list_proposed()
    assert len(proposed_list) == 1
    assert proposed_list[0].id == ids[0]
    assert proposed_list[0].status == "proposed"


async def test_extracted_triples_schema_is_empty_by_default():
    et = ExtractedTriples()
    assert et.triples == []
