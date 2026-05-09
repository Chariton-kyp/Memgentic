"""Tests for apply_dream / reject_dream + auto-apply non-destructive policy."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    DESTRUCTIVE_DREAM_ACTIONS,
    CaptureMethod,
    ContentType,
    DreamPatch,
    DreamPatchAction,
    DreamPatchStatus,
    DreamRun,
    DreamStatus,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)
from memgentic.processing.dream import apply_dream, reject_dream, run_dream
from memgentic.storage.metadata import MetadataStore


def _make_memory(mid: str, content: str = "x") -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.AUTO_DAEMON,
        ),
    )


@pytest.fixture()
def settings(tmp_path):
    # Force every dream-related env var off so the dev .env doesn't bleed
    # into the test process (e.g. a real ANTHROPIC_API_KEY would route the
    # fallback test through Anthropic and break it).
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        collection_name="test_dream_apply",
        embedding_dimensions=768,
        anthropic_api_key=None,
        dream_signal_model="",
        dream_consolidate_model="claude-sonnet-4-6",
    )


async def _seed_dream_with_patches(
    store: MetadataStore,
    actions: list[DreamPatchAction],
    targets_by_index: dict[int, list[str]] | None = None,
    metadata_by_index: dict[int, dict] | None = None,
    content_by_index: dict[int, str] | None = None,
) -> tuple[DreamRun, list[DreamPatch]]:
    run = DreamRun(project="test", status=DreamStatus.COMPLETED)
    await store.create_dream_run(run)
    patches = []
    for i, action in enumerate(actions):
        patches.append(
            DreamPatch(
                dream_id=run.id,
                action=action,
                target_memory_ids=(targets_by_index or {}).get(i, []),
                new_metadata=(metadata_by_index or {}).get(i),
                new_content=(content_by_index or {}).get(i),
                evidence="test",
            )
        )
    await store.create_dream_patches(patches)
    return run, patches


class TestApplyMerge:
    async def test_merge_marks_others_superseded(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_make_memory("canonical"))
        await metadata_store.save_memory(_make_memory("dup-1"))
        await metadata_store.save_memory(_make_memory("dup-2"))

        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.MERGE],
            targets_by_index={0: ["canonical", "dup-1", "dup-2"]},
        )

        report = await apply_dream(run.id, metadata_store=metadata_store)
        assert report.applied == 1
        assert sorted(report.superseded_memories) == ["dup-1", "dup-2"]

        canonical = await metadata_store.get_memory("canonical")
        dup1 = await metadata_store.get_memory("dup-1")
        assert canonical is not None
        assert dup1 is not None
        assert canonical.status == MemoryStatus.ACTIVE
        assert dup1.status == MemoryStatus.SUPERSEDED
        assert "dup-1" in canonical.supersedes
        assert "dup-2" in canonical.supersedes


class TestApplySupersede:
    """Regression: SUPERSEDE must pick the NEWEST memory as canonical,
    not blindly trust list order. The prompt promises 'newer fact wins'."""

    async def test_supersede_keeps_newest_regardless_of_list_order(
        self, metadata_store: MetadataStore
    ):
        from datetime import UTC, datetime, timedelta

        # Create three memories with explicit, distinct timestamps.
        old = _make_memory("old", content="we use Pinecone")
        old.created_at = datetime.now(UTC) - timedelta(days=30)
        mid = _make_memory("mid", content="we tried Weaviate")
        mid.created_at = datetime.now(UTC) - timedelta(days=10)
        new = _make_memory("new", content="we settled on Qdrant")
        new.created_at = datetime.now(UTC)
        for mem in (old, mid, new):
            await metadata_store.save_memory(mem)

        # LLM-typical ordering: oldest first, newest last (chronological listing).
        # Without the fix, ``targets[0] = "old"`` would be picked as canonical.
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.SUPERSEDE],
            targets_by_index={0: ["old", "mid", "new"]},
        )

        report = await apply_dream(run.id, metadata_store=metadata_store)
        assert report.applied == 1

        kept = await metadata_store.get_memory("new")
        old_after = await metadata_store.get_memory("old")
        mid_after = await metadata_store.get_memory("mid")
        assert kept is not None and old_after is not None and mid_after is not None
        # The NEWEST one survives, not targets[0]
        assert kept.status == MemoryStatus.ACTIVE
        assert old_after.status == MemoryStatus.SUPERSEDED
        assert mid_after.status == MemoryStatus.SUPERSEDED
        assert "old" in kept.supersedes
        assert "mid" in kept.supersedes

    async def test_merge_still_honours_first_id_as_canonical(self, metadata_store: MetadataStore):
        """MERGE keeps the LLM-stated canonical (targets[0]); only SUPERSEDE
        re-orders by created_at. This guards the deterministic merge path."""
        from datetime import UTC, datetime, timedelta

        canonical = _make_memory("canonical", content="canonical statement")
        canonical.created_at = datetime.now(UTC) - timedelta(days=5)
        newer = _make_memory("newer-dup", content="duplicate phrasing")
        newer.created_at = datetime.now(UTC)
        await metadata_store.save_memory(canonical)
        await metadata_store.save_memory(newer)

        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.MERGE],
            targets_by_index={0: ["canonical", "newer-dup"]},
        )
        await apply_dream(run.id, metadata_store=metadata_store)

        kept = await metadata_store.get_memory("canonical")
        discarded = await metadata_store.get_memory("newer-dup")
        assert kept is not None and discarded is not None
        assert kept.status == MemoryStatus.ACTIVE
        assert discarded.status == MemoryStatus.SUPERSEDED


class TestApplyArchiveStale:
    async def test_archive_stale_sets_status_archived(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_make_memory("dead-1"))
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.ARCHIVE_STALE],
            targets_by_index={0: ["dead-1"]},
        )
        await apply_dream(run.id, metadata_store=metadata_store)

        dead = await metadata_store.get_memory("dead-1")
        assert dead is not None
        assert dead.status == MemoryStatus.ARCHIVED


class TestApplyNormalizeDate:
    async def test_normalize_date_does_not_mutate_memory(self, metadata_store: MetadataStore):
        original = _make_memory("dated-1", content="yesterday we picked Qdrant")
        await metadata_store.save_memory(original)

        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.NORMALIZE_DATE],
            targets_by_index={0: ["dated-1"]},
            metadata_by_index={0: {"date": "2026-05-06"}},
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)

        assert report.applied == 1
        assert report.chronograph_triples == 1

        # The memory's content text was NOT rewritten — provenance preserved
        same = await metadata_store.get_memory("dated-1")
        assert same is not None
        assert same.content == "yesterday we picked Qdrant"


class TestApplyInsertInsight:
    async def test_insert_insight_creates_dream_sourced_memory(self, metadata_store: MetadataStore):
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.INSERT_INSIGHT],
            metadata_by_index={0: {"topics": ["python"], "entities": ["FastAPI"]}},
            content_by_index={0: "Project consistently chooses FastAPI over Flask"},
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)

        assert report.applied == 1
        assert len(report.inserted_memories) == 1

        new_id = report.inserted_memories[0]
        new_mem = await metadata_store.get_memory(new_id)
        assert new_mem is not None
        assert new_mem.source.platform == Platform.DREAM
        assert "python" in new_mem.topics
        assert "FastAPI" in new_mem.entities

    async def test_insert_insight_skips_when_no_content(self, metadata_store: MetadataStore):
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.INSERT_INSIGHT],
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)
        # Patch is marked applied but no memory was created (no new_content)
        assert report.inserted_memories == []

    async def test_insert_insight_does_not_supersede_citation_targets(
        self, metadata_store: MetadataStore
    ):
        """Regression: ``target_memory_ids`` on INSERT_INSIGHT are CITATIONS,
        not memories the insight replaces. The synthesized memory's
        ``supersedes`` must be empty unless ``new_metadata.supersedes`` is
        explicitly set. Treating citations as supersedes corrupts the lineage
        graph by marking corroborating evidence as invalidated."""
        # The citations remain ACTIVE — they back up the synthesized insight.
        await metadata_store.save_memory(_make_memory("cite-1", content="evidence A"))
        await metadata_store.save_memory(_make_memory("cite-2", content="evidence B"))

        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.INSERT_INSIGHT],
            targets_by_index={0: ["cite-1", "cite-2"]},
            metadata_by_index={0: {"topics": ["pattern"], "entities": []}},
            content_by_index={0: "Recurring pattern across cited evidence."},
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)
        assert len(report.inserted_memories) == 1

        new_id = report.inserted_memories[0]
        new_mem = await metadata_store.get_memory(new_id)
        assert new_mem is not None
        # CRITICAL: citation ids must NOT have been promoted to ``supersedes``
        assert new_mem.supersedes == []

        # And the cited memories themselves remain ACTIVE
        cite1 = await metadata_store.get_memory("cite-1")
        cite2 = await metadata_store.get_memory("cite-2")
        assert cite1 is not None and cite2 is not None
        assert cite1.status == MemoryStatus.ACTIVE
        assert cite2.status == MemoryStatus.ACTIVE

    async def test_insert_insight_honours_explicit_supersedes_metadata(
        self, metadata_store: MetadataStore
    ):
        """When the LLM explicitly sets ``new_metadata.supersedes``, that is
        respected — it's the only sanctioned path to populate the field."""
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.INSERT_INSIGHT],
            targets_by_index={0: ["cite-only"]},
            metadata_by_index={0: {"topics": ["x"], "supersedes": ["explicit-replacement-id"]}},
            content_by_index={0: "insight"},
        )
        report = await apply_dream(run.id, metadata_store=metadata_store)
        assert len(report.inserted_memories) == 1
        new_mem = await metadata_store.get_memory(report.inserted_memories[0])
        assert new_mem is not None
        assert new_mem.supersedes == ["explicit-replacement-id"]


class TestApplyUpdateField:
    async def test_update_field_rewrites_topics_only(self, metadata_store: MetadataStore):
        original = _make_memory("topical-1", content="content stays the same")
        original.topics = ["old"]
        await metadata_store.save_memory(original)

        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.UPDATE_FIELD],
            targets_by_index={0: ["topical-1"]},
            metadata_by_index={0: {"topics": ["new", "topics"]}},
        )
        await apply_dream(run.id, metadata_store=metadata_store)

        same = await metadata_store.get_memory("topical-1")
        assert same is not None
        # Content unchanged, topics rewritten
        assert same.content == "content stays the same"
        assert same.topics == ["new", "topics"]


class TestAutoApplyPolicy:
    async def test_auto_apply_skips_destructive_actions(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))

        actions = [
            DreamPatchAction.MERGE,
            DreamPatchAction.ARCHIVE_STALE,
            DreamPatchAction.NORMALIZE_DATE,
            DreamPatchAction.INSERT_INSIGHT,
        ]
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            actions,
            targets_by_index={0: ["a", "b"], 1: ["a"], 2: ["b"]},
            content_by_index={3: "synthesized insight"},
        )

        report = await apply_dream(run.id, metadata_store=metadata_store, only_non_destructive=True)

        # Only NORMALIZE_DATE + INSERT_INSIGHT applied → 2
        assert report.applied == 2
        assert report.skipped_destructive == 2

        # Live memories untouched on the destructive path
        a = await metadata_store.get_memory("a")
        assert a is not None
        assert a.status == MemoryStatus.ACTIVE  # not superseded by skipped MERGE
        assert "b" not in a.supersedes

        # Destructive patches remain PROPOSED for later explicit apply
        proposed = await metadata_store.get_dream_patches(run.id, status="proposed")
        proposed_actions = {p.action for p in proposed}
        assert DreamPatchAction.MERGE in proposed_actions
        assert DreamPatchAction.ARCHIVE_STALE in proposed_actions

    async def test_followup_explicit_apply_completes_destructive(
        self, metadata_store: MetadataStore
    ):
        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))
        run, _ = await _seed_dream_with_patches(
            metadata_store,
            [DreamPatchAction.MERGE, DreamPatchAction.NORMALIZE_DATE],
            targets_by_index={0: ["a", "b"], 1: ["a"]},
        )
        # First pass: only non-destructive
        first = await apply_dream(run.id, metadata_store=metadata_store, only_non_destructive=True)
        assert first.applied == 1
        assert first.skipped_destructive == 1

        # Second pass: destructive too
        second = await apply_dream(
            run.id, metadata_store=metadata_store, only_non_destructive=False
        )
        assert second.applied == 1  # the MERGE that was deferred
        a = await metadata_store.get_memory("a")
        b = await metadata_store.get_memory("b")
        assert a is not None and b is not None
        assert b.status == MemoryStatus.SUPERSEDED


class TestRejectAndIdempotency:
    async def test_reject_marks_proposed_as_rejected(self, metadata_store: MetadataStore):
        run, _ = await _seed_dream_with_patches(
            metadata_store, [DreamPatchAction.MERGE], targets_by_index={0: ["a", "b"]}
        )
        rejected = await reject_dream(run.id, metadata_store=metadata_store)
        assert rejected == 1

        patches = await metadata_store.get_dream_patches(run.id)
        assert all(p.status == DreamPatchStatus.REJECTED for p in patches)

    async def test_apply_after_reject_is_noop(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))
        run, _ = await _seed_dream_with_patches(
            metadata_store, [DreamPatchAction.MERGE], targets_by_index={0: ["a", "b"]}
        )
        await reject_dream(run.id, metadata_store=metadata_store)

        report = await apply_dream(run.id, metadata_store=metadata_store)
        assert report.applied == 0  # nothing in 'proposed' status
        b = await metadata_store.get_memory("b")
        assert b is not None
        assert b.status == MemoryStatus.ACTIVE  # untouched

    async def test_apply_idempotent_when_called_twice(self, metadata_store: MetadataStore):
        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))
        run, _ = await _seed_dream_with_patches(
            metadata_store, [DreamPatchAction.MERGE], targets_by_index={0: ["a", "b"]}
        )
        first = await apply_dream(run.id, metadata_store=metadata_store)
        assert first.applied == 1

        second = await apply_dream(run.id, metadata_store=metadata_store)
        assert second.applied == 0  # already applied → no proposed patches

    async def test_idempotent_reapply_preserves_applied_at(self, metadata_store: MetadataStore):
        """Regression: a re-apply that finds zero proposed patches must NOT
        wipe the ``applied_at`` timestamp set by the first successful apply."""
        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))
        run, _ = await _seed_dream_with_patches(
            metadata_store, [DreamPatchAction.MERGE], targets_by_index={0: ["a", "b"]}
        )

        await apply_dream(run.id, metadata_store=metadata_store)
        first_run = await metadata_store.get_dream_run(run.id)
        assert first_run is not None
        assert first_run.applied_at is not None
        original_ts = first_run.applied_at

        # Second call has no proposed patches; must leave applied_at intact.
        await apply_dream(run.id, metadata_store=metadata_store)
        second_run = await metadata_store.get_dream_run(run.id)
        assert second_run is not None
        assert second_run.applied_at == original_ts

    async def test_apply_unknown_dream_returns_error(self, metadata_store: MetadataStore):
        report = await apply_dream("does-not-exist", metadata_store=metadata_store)
        assert report.applied == 0
        assert any("not found" in e for e in report.errors)


class TestPhase3Fallback:
    """The Consolidate phase falls back to the default LLMClient when no Anthropic key."""

    async def test_create_consolidate_llm_returns_default_when_no_key(self, settings):
        from memgentic.processing.dream import create_consolidate_llm

        # No anthropic_api_key configured — must return a regular LLMClient
        # without crashing on the missing key.
        client = create_consolidate_llm(settings)
        # The returned client has a _provider_kind attribute set by LLMClient
        assert getattr(client, "_provider_kind", None) != "anthropic"


class TestModelRouting:
    """Phase-2 / Phase-3 LLM factories pick provider based on model name."""

    async def test_consolidate_picks_default_for_non_claude_model(self, settings):
        from memgentic.processing.dream import create_consolidate_llm

        settings.dream_consolidate_model = ""  # Forces default LLMClient
        client = create_consolidate_llm(settings)
        assert getattr(client, "_provider_kind", None) != "anthropic"

    async def test_signal_picks_default_for_empty_string(self, settings):
        from memgentic.processing.dream import create_signal_llm

        settings.dream_signal_model = ""  # Forces default LLMClient
        client = create_signal_llm(settings)
        assert getattr(client, "_provider_kind", None) != "anthropic"

    async def test_consolidate_attempts_anthropic_with_claude_model_and_key(
        self, settings, monkeypatch
    ):
        """When the model is claude-* AND the key is set, _build_anthropic_client
        is called. We monkey-patch it so we don't actually hit the network."""
        from memgentic.processing import dream as dream_module

        called = {}

        def _fake_build(s, model, *, phase_label):
            called["model"] = model
            called["phase_label"] = phase_label
            from memgentic.processing.llm import LLMClient

            client = LLMClient(s)
            client._provider_kind = "anthropic"
            return client

        monkeypatch.setattr(dream_module, "_build_anthropic_client", _fake_build)
        settings.anthropic_api_key = "sk-ant-test"
        settings.dream_consolidate_model = "claude-haiku-4-5"

        client = dream_module.create_consolidate_llm(settings)
        assert called["model"] == "claude-haiku-4-5"
        assert called["phase_label"] == "consolidate"
        assert getattr(client, "_provider_kind", None) == "anthropic"

    async def test_signal_routes_haiku_when_key_set(self, settings, monkeypatch):
        from memgentic.processing import dream as dream_module

        captured = {}

        def _fake_build(s, model, *, phase_label):
            captured["model"] = model
            captured["phase_label"] = phase_label
            from memgentic.processing.llm import LLMClient

            client = LLMClient(s)
            client._provider_kind = "anthropic"
            return client

        monkeypatch.setattr(dream_module, "_build_anthropic_client", _fake_build)
        settings.anthropic_api_key = "sk-ant-test"
        settings.dream_signal_model = "claude-haiku-4-5"

        dream_module.create_signal_llm(settings)
        assert captured["model"] == "claude-haiku-4-5"
        assert captured["phase_label"] == "signal"

    async def test_consolidate_routing_is_case_insensitive(self, settings, monkeypatch):
        """Regression: ``Claude-Sonnet-4-6`` (mixed case) must route to
        Anthropic, not silently fall back to the default LLMClient. Anthropic
        accepts mixed-case ids, so a copy/paste from docs / shell history
        shouldn't break routing."""
        from memgentic.processing import dream as dream_module

        captured = {}

        def _fake_build(s, model, *, phase_label):
            captured["model"] = model
            from memgentic.processing.llm import LLMClient

            client = LLMClient(s)
            client._provider_kind = "anthropic"
            return client

        monkeypatch.setattr(dream_module, "_build_anthropic_client", _fake_build)
        settings.anthropic_api_key = "sk-ant-test"

        # Each capitalisation variant must reach Anthropic
        for variant in ("Claude-Sonnet-4-6", "CLAUDE-OPUS-4-7", "Claude-Haiku-4-5"):
            captured.clear()
            settings.dream_consolidate_model = variant
            client = dream_module.create_consolidate_llm(settings)
            assert getattr(client, "_provider_kind", None) == "anthropic", (
                f"variant {variant!r} fell through to default LLMClient"
            )
            # The model name is forwarded as-is (case preserved); the
            # routing decision is the case-insensitive part.
            assert captured["model"] == variant


class TestDetectProvider:
    """The model-name -> provider classifier underpins all routing."""

    def test_anthropic_prefixes(self):
        from memgentic.processing.dream import _detect_provider

        assert _detect_provider("claude-haiku-4-5") == "anthropic"
        assert _detect_provider("Claude-Sonnet-4-6") == "anthropic"
        assert _detect_provider("anthropic/claude-haiku-4-5") == "anthropic"

    def test_gemini_prefixes(self):
        from memgentic.processing.dream import _detect_provider

        assert _detect_provider("gemini-3.1-flash-lite") == "gemini"
        assert _detect_provider("Gemini-2.5-pro") == "gemini"
        assert _detect_provider("models/gemini-3.1-pro") == "gemini"

    def test_openai_compat_prefixes(self):
        from memgentic.processing.dream import _detect_provider

        assert _detect_provider("gpt-4o-mini") == "openai_compat"
        assert _detect_provider("GPT-4o") == "openai_compat"
        assert _detect_provider("o1-mini") == "openai_compat"
        assert _detect_provider("openai/gpt-4o") == "openai_compat"

    def test_ollama_falls_through_for_unknown(self):
        from memgentic.processing.dream import _detect_provider

        # Anything else is treated as an Ollama tag — Ollama supports
        # tags with and without colons, and arbitrary HF refs.
        assert _detect_provider("qwen3.6:35b-a3b") == "ollama"
        assert _detect_provider("gemma4:e4b") == "ollama"
        assert _detect_provider("llama3.1") == "ollama"
        assert _detect_provider("hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_S") == "ollama"
        assert _detect_provider("phi4-reasoning:14b") == "ollama"

    def test_empty_string_yields_empty(self):
        from memgentic.processing.dream import _detect_provider

        assert _detect_provider("") == ""


class TestProviderFactories:
    """Each builder is gated by the relevant credential / availability."""

    async def test_anthropic_skipped_without_key(self, settings):
        from memgentic.processing.dream import _build_anthropic_client

        settings.anthropic_api_key = None
        assert _build_anthropic_client(settings, "claude-haiku-4-5", phase_label="signal") is None

    async def test_gemini_skipped_without_key(self, settings):
        from memgentic.processing.dream import _build_gemini_client

        settings.google_api_key = None
        assert _build_gemini_client(settings, "gemini-3.1-flash-lite", phase_label="signal") is None

    async def test_openai_compat_skipped_without_base_url(self, settings):
        from memgentic.processing.dream import _build_openai_compat_client

        settings.openai_compat_base_url = None
        assert _build_openai_compat_client(settings, "gpt-4o-mini", phase_label="signal") is None

    async def test_ollama_skipped_when_local_llm_disabled(self, settings):
        from memgentic.processing.dream import _build_ollama_client

        settings.enable_local_llm = False
        assert _build_ollama_client(settings, "gemma4:e4b", phase_label="signal") is None


class TestPerRunModelOverride:
    """``run_dream`` accepts per-run signal_model / consolidate_model that
    override settings without mutating them."""

    async def test_per_run_consolidate_override_routes_via_phase_llm(
        self, metadata_store: MetadataStore, settings, monkeypatch
    ):
        """When the caller passes ``consolidate_model=``, the dispatcher
        is invoked with that exact model string — not the settings value."""
        from memgentic.processing import dream as dream_module
        from memgentic.processing.dream import run_dream

        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))

        captured: dict = {"signal": None, "consolidate": None}

        def _fake_phase(s, raw_model, phase_label):
            captured[phase_label] = raw_model
            from unittest.mock import AsyncMock, MagicMock

            from memgentic.processing.dream import PatchSet, SignalReport

            llm = MagicMock()
            llm.available = True

            async def _gen(prompt, schema):
                if schema is SignalReport:
                    return SignalReport(), {"input_tokens": 0, "output_tokens": 0}
                return PatchSet(patches=[]), {"input_tokens": 0, "output_tokens": 0}

            llm.generate_structured_with_usage = AsyncMock(side_effect=_gen)
            return llm

        monkeypatch.setattr(dream_module, "_build_phase_llm", _fake_phase)

        run = await run_dream(
            project="",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_model="claude-haiku-4-5",
            consolidate_model="qwen3.6:35b-a3b",
        )
        assert captured["signal"] == "claude-haiku-4-5"
        assert captured["consolidate"] == "qwen3.6:35b-a3b"
        # Settings values are NOT mutated — override is per-run only
        assert settings.dream_signal_model != "claude-haiku-4-5"
        # And the persisted DreamRun.model reflects the override
        assert run.model == "qwen3.6:35b-a3b"

    async def test_per_run_override_falls_back_to_default_on_builder_failure(
        self, metadata_store: MetadataStore, settings, monkeypatch
    ):
        """If the override builder returns None (e.g. provider unavailable),
        run_dream falls back to a fresh default LLMClient — never crashes."""
        from memgentic.processing import dream as dream_module
        from memgentic.processing.dream import run_dream

        await metadata_store.save_memory(_make_memory("a"))

        # Builder always returns None — simulating "Anthropic key missing"
        monkeypatch.setattr(dream_module, "_build_phase_llm", lambda *a, **kw: None)

        run = await run_dream(
            project="",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_model="claude-haiku-4-5",
            consolidate_model="claude-sonnet-4-6",
        )
        # Did not crash; pipeline completed even though both overrides failed
        assert run.status == DreamStatus.COMPLETED


class TestTokenUsagePropagation:
    """The dream pipeline aggregates token usage from each LLM call into the
    persisted DreamRun row."""

    async def test_run_persists_aggregated_usage(self, metadata_store: MetadataStore, settings):
        """Verify token counts FLOW from gather → consolidate → index. The
        assertion is exact, not bounded, so a future refactor that resets
        ``total_in = 0`` in either node (instead of starting from
        ``state.get("usage_input_tokens", 0)``) trips the test instead of
        silently dropping the upstream phase's contribution."""
        from unittest.mock import AsyncMock, MagicMock

        from memgentic.processing.dream import (
            PatchSet,
            SignalReport,
            run_dream,
        )

        await metadata_store.save_memory(_make_memory("a"))
        await metadata_store.save_memory(_make_memory("b"))

        # Both seeded memories have empty topics -> two singleton clusters
        # -> two consolidate calls. Expected aggregate:
        #   input  = 1000 (signal) + 2 * 2000 (consolidate) = 5000
        #   output =  100 (signal) + 2 *  200 (consolidate) =  500
        async def _gen(prompt, schema):
            if schema is SignalReport:
                return (
                    SignalReport(),
                    {"input_tokens": 1000, "output_tokens": 100},
                )
            if schema is PatchSet:
                return (
                    PatchSet(patches=[]),
                    {"input_tokens": 2000, "output_tokens": 200},
                )
            return None, {"input_tokens": 0, "output_tokens": 0}

        llm = MagicMock()
        llm.available = True
        llm.generate_structured_with_usage = AsyncMock(side_effect=_gen)

        run = await run_dream(
            project="",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_llm=llm,
            consolidate_llm=llm,
        )
        # EXACT equality — proves both phases contributed AND were accumulated,
        # not overwritten. A regression that drops either phase's tokens fails
        # this assertion.
        assert run.usage_input_tokens == 5000, (
            f"expected signal(1000) + 2*consolidate(2000) = 5000, got {run.usage_input_tokens}"
        )
        assert run.usage_output_tokens == 500, (
            f"expected signal(100) + 2*consolidate(200) = 500, got {run.usage_output_tokens}"
        )

        # Persisted to DB, not just in-memory
        refreshed = await metadata_store.get_dream_run(run.id)
        assert refreshed is not None
        assert refreshed.usage_input_tokens == 5000
        assert refreshed.usage_output_tokens == 500


class TestDestructiveSet:
    """Sanity check on the destructive-action set used by the auto-apply policy."""

    def test_destructive_actions_are_exactly_three(self):
        assert (
            frozenset(
                {
                    DreamPatchAction.MERGE,
                    DreamPatchAction.SUPERSEDE,
                    DreamPatchAction.ARCHIVE_STALE,
                }
            )
            == DESTRUCTIVE_DREAM_ACTIONS
        )
        # Non-destructive actions are NOT in the set
        assert DreamPatchAction.NORMALIZE_DATE not in DESTRUCTIVE_DREAM_ACTIONS
        assert DreamPatchAction.INSERT_INSIGHT not in DESTRUCTIVE_DREAM_ACTIONS
        assert DreamPatchAction.UPDATE_FIELD not in DESTRUCTIVE_DREAM_ACTIONS


class TestRunDreamThenApply:
    """End-to-end: run_dream + apply_dream over a real metadata store."""

    async def test_run_then_auto_apply_keeps_destructive_proposed(
        self, metadata_store: MetadataStore, settings
    ):
        from memgentic.processing.dream import PatchSet, ProposedPatch, SignalReport

        for mid in ("a", "b"):
            await metadata_store.save_memory(_make_memory(mid))

        # Mock LLM that proposes a MERGE on (a, b) and an INSERT_INSIGHT.
        async def _gen(prompt, schema):
            if schema is PatchSet:
                return (
                    PatchSet(
                        patches=[
                            ProposedPatch(
                                action=DreamPatchAction.MERGE,
                                target_memory_ids=["a", "b"],
                                evidence="dup",
                            ),
                            ProposedPatch(
                                action=DreamPatchAction.INSERT_INSIGHT,
                                target_memory_ids=[],
                                new_content="new insight",
                                evidence="recurring",
                            ),
                        ]
                    ),
                    {"input_tokens": 0, "output_tokens": 0},
                )
            return SignalReport(), {"input_tokens": 0, "output_tokens": 0}

        from unittest.mock import AsyncMock as _AsyncMock

        llm = MagicMock()
        llm.available = True
        llm.generate_structured_with_usage = _AsyncMock(side_effect=_gen)

        run = await run_dream(
            project="",
            metadata_store=metadata_store,
            embedder=MagicMock(),
            settings=settings,
            signal_llm=llm,
            consolidate_llm=llm,
        )
        assert run.status == DreamStatus.COMPLETED

        report = await apply_dream(run.id, metadata_store=metadata_store, only_non_destructive=True)
        assert report.applied >= 1  # the INSERT_INSIGHT
        assert report.skipped_destructive >= 1  # the MERGE

        # MERGE patch is still proposed
        proposed_after = await metadata_store.get_dream_patches(run.id, status="proposed")
        assert any(p.action == DreamPatchAction.MERGE for p in proposed_after)
