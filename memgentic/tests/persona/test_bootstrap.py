"""Tests for the LLM-driven persona bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.persona import bootstrap
from memgentic.persona.schema import Persona
from memgentic.storage.metadata import MetadataStore


class _FakeLLM:
    """Minimal drop-in for :class:`~memgentic.processing.llm.LLMClient`."""

    def __init__(self, response: str, available: bool = True):
        self._response = response
        self.available = available
        self.generate = AsyncMock(side_effect=self._gen)

    async def _gen(self, prompt: str) -> str:
        return self._response


@pytest.fixture
def tmp_settings(tmp_path: Path) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        embedding_dimensions=768,
    )


@pytest.fixture
async def seeded_store(tmp_path: Path):
    store = MetadataStore(tmp_path / "mem.db")
    await store.initialize()
    for i in range(5):
        await store.save_memory(
            Memory(
                content=f"Decision {i}: chose Qdrant for vectors",
                content_type=ContentType.DECISION,
                source=SourceMetadata(
                    platform=Platform.CLAUDE_CODE,
                    capture_method=CaptureMethod.MCP_TOOL,
                ),
                topics=["architecture"],
            )
        )
    yield store
    await store.close()


async def test_bootstrap_returns_persona_on_valid_llm_output(tmp_settings, seeded_store):
    payload = {
        "version": 1,
        "identity": {"name": "Atlas", "role": "test assistant", "tone": "calm"},
        "people": [],
        "projects": [],
        "preferences": {"remember": ["decisions"], "avoid": []},
    }
    llm = _FakeLLM(json.dumps(payload))
    persona = await bootstrap(
        source="recent",
        limit=5,
        store=seeded_store,
        llm_client=llm,
        settings_override=tmp_settings,
    )
    assert isinstance(persona, Persona)
    assert persona.identity.name == "Atlas"
    # Bootstrap always forces generated_by to "bootstrap"
    assert persona.metadata.generated_by == "bootstrap"


async def test_bootstrap_handles_code_fenced_json(tmp_settings, seeded_store):
    payload = {"identity": {"name": "Atlas"}}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    llm = _FakeLLM(fenced)
    persona = await bootstrap(store=seeded_store, llm_client=llm, settings_override=tmp_settings)
    assert persona is not None
    assert persona.identity.name == "Atlas"


async def test_bootstrap_returns_none_when_llm_unavailable(tmp_settings, seeded_store):
    llm = _FakeLLM("", available=False)
    persona = await bootstrap(store=seeded_store, llm_client=llm, settings_override=tmp_settings)
    assert persona is None


async def test_bootstrap_returns_none_on_empty_llm_response(tmp_settings, seeded_store):
    llm = _FakeLLM("")
    persona = await bootstrap(store=seeded_store, llm_client=llm, settings_override=tmp_settings)
    assert persona is None


async def test_bootstrap_returns_none_on_non_json_output(tmp_settings, seeded_store):
    llm = _FakeLLM("Here is a persona: it's warm and helpful.")
    persona = await bootstrap(store=seeded_store, llm_client=llm, settings_override=tmp_settings)
    assert persona is None


async def test_bootstrap_returns_none_on_invalid_shape(tmp_settings, seeded_store):
    # missing required identity.name
    llm = _FakeLLM(json.dumps({"identity": {}}))
    persona = await bootstrap(store=seeded_store, llm_client=llm, settings_override=tmp_settings)
    assert persona is None


async def test_bootstrap_skills_mode_runs(tmp_settings, seeded_store):
    payload = {"identity": {"name": "Atlas"}}
    llm = _FakeLLM(json.dumps(payload))
    persona = await bootstrap(
        source="skills",
        store=seeded_store,
        llm_client=llm,
        settings_override=tmp_settings,
    )
    assert persona is not None
    assert persona.identity.name == "Atlas"
