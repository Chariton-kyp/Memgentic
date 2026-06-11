"""Tests for the auto-dream LangGraph pipeline (orient/gather/consolidate/index)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    DreamPatchAction,
    DreamRun,
    DreamStatus,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.processing.dream import (
    PatchSet,
    ProposedPatch,
    SignalReport,
    consolidate_node,
    gather_signal_node,
    index_node,
    orient_node,
    run_dream,
)
from memgentic.storage.metadata import MetadataStore


def _make_memory(
    mid: str,
    content: str = "test content",
    project: str = "test-project",
    topics: list[str] | None = None,
    platform: Platform = Platform.CLAUDE_CODE,
    confidence: float = 0.9,
) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.AUTO_DAEMON,
            session_id=f"sess-{mid}",
        ),
        project=project,
        topics=topics or [],
        confidence=confidence,
    )


@pytest.fixture()
def settings(tmp_path):
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        collection_name="test_dream",
        embedding_dimensions=768,
        anthropic_api_key=None,
        dream_default_session_limit=5,
    )


@pytest.fixture()
def mock_llm_with_signal_report():
    """LLM client returning canned SignalReport with token usage."""
    llm = MagicMock()
    llm.available = True
    llm.generate_structured_with_usage = AsyncMock(
        return_value=(
            SignalReport(
                corrections=["use sqlite-vec, not qdrant"],
                preference_changes=["prefer Greek docstrings"],
                recurring_patterns=["forgets to run migrations"],
                decisions_with_dates=[],
            ),
            {"input_tokens": 1500, "output_tokens": 200},
        )
    )
    return llm


@pytest.fixture()
def mock_llm_unavailable():
    llm = MagicMock()
    llm.available = False
    llm.generate_structured_with_usage = AsyncMock(
        return_value=(None, {"input_tokens": 0, "output_tokens": 0})
    )
    return llm


@pytest.fixture()
def mock_llm_with_patches():
    """LLM client returning a single MERGE patch on every Consolidate call."""
    llm = MagicMock()
    llm.available = True

    async def _gen(prompt, schema):
        if schema is PatchSet:
            return (
                PatchSet(
                    patches=[
                        ProposedPatch(
                            action=DreamPatchAction.MERGE,
                            target_memory_ids=["m-1", "m-2"],
                            evidence="duplicate decisions about Qdrant",
                        )
                    ]
                ),
                {"input_tokens": 2500, "output_tokens": 300},
            )
        return SignalReport(), {"input_tokens": 800, "output_tokens": 100}

    llm.generate_structured_with_usage = AsyncMock(side_effect=_gen)
    return llm


class TestOrientNode:
    """Phase 1 — Orient is deterministic and runs without an LLM."""

    async def test_inventories_active_memories(self, metadata_store: MetadataStore, settings):
        await metadata_store.save_memory(
            _make_memory("m-1", topics=["python"], project="test-project")
        )
        await metadata_store.save_memory(
            _make_memory("m-2", topics=["python"], project="test-project")
        )
        await metadata_store.save_memory(
            _make_memory("m-3", topics=["go"], project="other-project")
        )

        state = {
            "project": "test-project",
            "user_id": "",
            "limit_sessions": 5,
            "metadata_store": metadata_store,
            "settings": settings,
        }
        out = await orient_node(state)  # type: ignore[arg-type]

        assert out["inventory"]["n_memories"] == 2
        ids = set(out["inventory"]["memory_ids"])
        assert ids == {"m-1", "m-2"}
        assert "claude_code" in out["inventory"]["source_breakdown"]
        # Handoffs should be a list (possibly empty for these synthetic memories)
        assert isinstance(out["handoffs"], list)


class TestGatherSignalNode:
    """Phase 2 — Gather Signal calls the LLM and returns SignalReport."""

    async def test_with_mocked_llm(self, mock_llm_with_signal_report):
        state = {
            "signal_llm": mock_llm_with_signal_report,
            "handoffs": [
                {
                    "platform": "claude_code",
                    "session_id": "s1",
                    "session_title": "test",
                    "memories": [_make_memory("m-1")],
                }
            ],
            "project": "test-project",
        }
        out = await gather_signal_node(state)  # type: ignore[arg-type]
        report = out["signal_report"]
        assert "corrections" in report
        assert any("sqlite-vec" in c for c in report["corrections"])
        mock_llm_with_signal_report.generate_structured_with_usage.assert_awaited_once()
        # Token usage is plumbed through state
        assert out["usage_input_tokens"] == 1500
        assert out["usage_output_tokens"] == 200

    async def test_falls_back_when_llm_unavailable(self, mock_llm_unavailable):
        state = {
            "signal_llm": mock_llm_unavailable,
            "handoffs": [],
            "project": "x",
        }
        out = await gather_signal_node(state)  # type: ignore[arg-type]
        # Empty SignalReport — no LLM call
        assert out["signal_report"]["corrections"] == []
        mock_llm_unavailable.generate_structured_with_usage.assert_not_awaited()
        assert out["usage_input_tokens"] == 0
        assert out["usage_output_tokens"] == 0


class TestConsolidateNode:
    """Phase 3 — Consolidate proposes patches via LLM, drops hallucinated IDs."""

    async def test_proposes_patches_for_clusters(
        self, metadata_store: MetadataStore, mock_llm_with_patches
    ):
        # Two memories sharing topic 'python' so they cluster together
        m1 = _make_memory("m-1", content="Use Qdrant for vectors", topics=["python"])
        m2 = _make_memory("m-2", content="Use Qdrant via local mode", topics=["python"])
        await metadata_store.save_memory(m1)
        await metadata_store.save_memory(m2)

        state = {
            "metadata_store": metadata_store,
            "consolidate_llm": mock_llm_with_patches,
            "project": "test-project",
            "user_id": "",
            "inventory": {
                "n_memories": 2,
                "source_breakdown": {"claude_code": 2},
                "content_type_breakdown": {"fact": 2},
                "memory_ids": ["m-1", "m-2"],
            },
            "signal_report": SignalReport().model_dump(),
            "instructions": "",
        }
        out = await consolidate_node(state)  # type: ignore[arg-type]
        assert len(out["patches"]) >= 1
        first = out["patches"][0]
        assert first["action"] == DreamPatchAction.MERGE.value
        assert first["target_memory_ids"] == ["m-1", "m-2"]

    async def test_drops_patches_referencing_unknown_ids(self, metadata_store: MetadataStore):
        # LLM hallucinates memory id "m-9" that doesn't exist — must be dropped
        async def _gen(prompt, schema):
            if schema is PatchSet:
                return (
                    PatchSet(
                        patches=[
                            ProposedPatch(
                                action=DreamPatchAction.MERGE,
                                target_memory_ids=["m-1", "m-9"],
                                evidence="bogus",
                            )
                        ]
                    ),
                    {"input_tokens": 0, "output_tokens": 0},
                )
            return SignalReport(), {"input_tokens": 0, "output_tokens": 0}

        llm = MagicMock()
        llm.available = True
        llm.generate_structured_with_usage = AsyncMock(side_effect=_gen)

        await metadata_store.save_memory(_make_memory("m-1", topics=["python"]))

        state = {
            "metadata_store": metadata_store,
            "consolidate_llm": llm,
            "project": "test-project",
            "user_id": "",
            "inventory": {
                "n_memories": 1,
                "source_breakdown": {},
                "content_type_breakdown": {},
                "memory_ids": ["m-1"],
            },
            "signal_report": SignalReport().model_dump(),
            "instructions": "",
        }
        out = await consolidate_node(state)  # type: ignore[arg-type]
        # The patch references m-9 which does not exist — must be dropped
        assert out["patches"] == []

    async def test_no_llm_no_patches(self, metadata_store: MetadataStore, mock_llm_unavailable):
        await metadata_store.save_memory(_make_memory("m-1"))
        state = {
            "metadata_store": metadata_store,
            "consolidate_llm": mock_llm_unavailable,
            "project": "test-project",
            "user_id": "",
            "inventory": {
                "n_memories": 1,
                "source_breakdown": {},
                "content_type_breakdown": {},
                "memory_ids": ["m-1"],
            },
            "signal_report": {},
            "instructions": "",
        }
        out = await consolidate_node(state)  # type: ignore[arg-type]
        assert out["patches"] == []


class TestIndexNode:
    """Phase 4 — Index persists DreamRun + DreamPatch rows; never touches memories."""

    async def test_persists_run_and_patches(self, metadata_store: MetadataStore):
        run = DreamRun(project="test-project", status=DreamStatus.RUNNING)
        await metadata_store.create_dream_run(run)

        state = {
            "metadata_store": metadata_store,
            "dream_run": run,
            "patches": [
                {
                    "action": DreamPatchAction.MERGE.value,
                    "target_memory_ids": ["m-1", "m-2"],
                    "evidence": "dup",
                }
            ],
            "inventory": {"n_memories": 2},
            "handoffs": [{"session_id": "s1"}],
        }
        out = await index_node(state)  # type: ignore[arg-type]

        # DreamRun is now COMPLETED with the right counts
        refreshed = await metadata_store.get_dream_run(run.id)
        assert refreshed is not None
        assert refreshed.status == DreamStatus.COMPLETED
        assert refreshed.input_memory_count == 2
        assert refreshed.input_session_ids == ["s1"]

        # The patch was persisted
        patches = await metadata_store.get_dream_patches(run.id)
        assert len(patches) == 1
        assert patches[0].action == DreamPatchAction.MERGE
        assert out["patches"][0]["target_memory_ids"] == ["m-1", "m-2"]


class TestRunDreamEndToEnd:
    """run_dream wires the whole pipeline; live memories are untouched."""

    async def test_full_pipeline_with_mocked_llm(
        self, metadata_store: MetadataStore, settings, mock_llm_with_patches
    ):
        await metadata_store.save_memory(
            _make_memory("m-1", topics=["python"], project="test-project")
        )
        await metadata_store.save_memory(
            _make_memory("m-2", topics=["python"], project="test-project")
        )

        run = await run_dream(
            project="test-project",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_llm=mock_llm_with_patches,
            consolidate_llm=mock_llm_with_patches,
            limit_sessions=5,
        )

        assert run.status == DreamStatus.COMPLETED
        assert run.input_memory_count == 2
        assert run.error is None

        patches = await metadata_store.get_dream_patches(run.id)
        assert len(patches) >= 1

        # Live memories unchanged — apply_dream is required to mutate them
        m1 = await metadata_store.get_memory("m-1")
        m2 = await metadata_store.get_memory("m-2")
        assert m1 is not None and m1.status.value == "active"
        assert m2 is not None and m2.status.value == "active"

    async def test_falls_back_when_llm_unavailable(
        self, metadata_store: MetadataStore, settings, mock_llm_unavailable
    ):
        await metadata_store.save_memory(_make_memory("m-1", project="test-project"))

        run = await run_dream(
            project="test-project",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_llm=mock_llm_unavailable,
            consolidate_llm=mock_llm_unavailable,
            limit_sessions=5,
        )

        assert run.status == DreamStatus.COMPLETED
        # No LLM means no proposed patches
        patches = await metadata_store.get_dream_patches(run.id)
        assert patches == []

    async def test_rejects_oversized_instructions(
        self, metadata_store: MetadataStore, settings, mock_llm_unavailable
    ):
        with pytest.raises(ValueError):
            await run_dream(
                project="x",
                metadata_store=metadata_store,
                embedder=MagicMock(),
                settings=settings,
                signal_llm=mock_llm_unavailable,
                consolidate_llm=mock_llm_unavailable,
                instructions="x" * 5000,
            )
