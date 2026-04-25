"""Tests for :class:`benchmarks.lib.harness.BenchmarkHarness`.

These tests exercise the harness *shape* — lifecycle, profile
validation, JSONL writing, evaluate() contract — without requiring an
Ollama server or a real embedding model. A full end-to-end test with
real embeddings belongs in a nightly job, not PR CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from memgentic.models import ContentType, ConversationChunk, Platform

from benchmarks.lib.harness import (
    BenchmarkHarness,
    BenchmarkQuery,
    CorpusSession,
)


# ---------------------------------------------------------------------------
# Profile normalisation
# ---------------------------------------------------------------------------
class TestProfileNormalisation:
    def test_accepts_raw(self) -> None:
        assert BenchmarkHarness(profile="raw").profile == "raw"

    def test_accepts_enriched(self) -> None:
        assert BenchmarkHarness(profile="enriched").profile == "enriched"

    def test_accepts_dual(self) -> None:
        assert BenchmarkHarness(profile="dual").profile == "dual"

    def test_verbatim_alias_maps_to_raw(self) -> None:
        assert BenchmarkHarness(profile="verbatim").profile == "raw"

    def test_rejects_unknown_profile(self) -> None:
        with pytest.raises(ValueError, match="Unknown profile"):
            BenchmarkHarness(profile="nonsense")


# ---------------------------------------------------------------------------
# write_jsonl — pure file I/O, no Memgentic stack needed
# ---------------------------------------------------------------------------
class TestWriteJsonl:
    def test_writes_one_object_per_line(self, tmp_path: Path) -> None:
        records = [{"id": "q1", "recall": True}, {"id": "q2", "recall": False}]
        out = BenchmarkHarness.write_jsonl(records, tmp_path / "results.jsonl")
        lines = out.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"id": "q1", "recall": True}
        assert json.loads(lines[1]) == {"id": "q2", "recall": False}

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out = BenchmarkHarness.write_jsonl([{"x": 1}], tmp_path / "a" / "b" / "c.jsonl")
        assert out.exists()

    def test_handles_non_json_values_via_default_str(self, tmp_path: Path) -> None:
        import datetime as _dt

        rec = {"when": _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)}
        out = BenchmarkHarness.write_jsonl([rec], tmp_path / "dt.jsonl")
        parsed = json.loads(out.read_text().splitlines()[0])
        assert "2026-01-01" in parsed["when"]


# ---------------------------------------------------------------------------
# Lifecycle + isolation — exercise setup()/teardown() with real stores
# ---------------------------------------------------------------------------
pytestmark_lifecycle = pytest.mark.usefixtures("tmp_path")


def _require_stack() -> None:
    """Skip lifecycle tests if Memgentic's stack imports fail for any reason.

    The core library imports are exercised elsewhere; we skip rather
    than fail loudly here so optional deps (e.g., sqlite-vec wheels on
    exotic platforms) don't break the whole benchmark suite.
    """
    try:
        import memgentic.processing.embedder  # noqa: F401
        import memgentic.storage.metadata  # noqa: F401
        import memgentic.storage.vectors  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"Memgentic stack not importable: {exc}")


class TestLifecycle:
    async def test_setup_creates_temp_root(self, tmp_path: Path) -> None:
        _require_stack()
        harness = BenchmarkHarness(profile="raw", backend="sqlite-vec")
        await harness.setup()
        try:
            assert harness._tmp_root is not None  # type: ignore[attr-defined]
            assert harness._tmp_root.exists()  # type: ignore[attr-defined]
        finally:
            await harness.teardown()

    async def test_teardown_removes_temp_root(self, tmp_path: Path) -> None:
        _require_stack()
        harness = BenchmarkHarness(profile="raw", backend="sqlite-vec")
        await harness.setup()
        tmp_root = harness._tmp_root  # type: ignore[attr-defined]
        await harness.teardown()
        assert tmp_root is not None
        assert not tmp_root.exists(), "temp directory was not cleaned up"

    async def test_teardown_is_idempotent(self, tmp_path: Path) -> None:
        _require_stack()
        harness = BenchmarkHarness(profile="raw", backend="sqlite-vec")
        await harness.setup()
        await harness.teardown()
        # Second teardown must not raise.
        await harness.teardown()

    async def test_setup_twice_raises(self, tmp_path: Path) -> None:
        _require_stack()
        harness = BenchmarkHarness(profile="raw", backend="sqlite-vec")
        await harness.setup()
        try:
            with pytest.raises(RuntimeError, match="called twice"):
                await harness.setup()
        finally:
            await harness.teardown()

    async def test_search_before_setup_raises(self) -> None:
        _require_stack()
        harness = BenchmarkHarness(profile="raw", backend="sqlite-vec")
        with pytest.raises(RuntimeError, match="not initialised"):
            await harness.search("anything")

    async def test_ingest_before_setup_raises(self) -> None:
        _require_stack()
        harness = BenchmarkHarness(profile="raw", backend="sqlite-vec")
        session = CorpusSession(
            session_id="s1",
            chunks=[
                ConversationChunk(
                    content="hello", content_type=ContentType.FACT, topics=[], entities=[]
                )
            ],
            platform=Platform.UNKNOWN,
        )
        with pytest.raises(RuntimeError, match="not initialised"):
            await harness.ingest_session(session)


# ---------------------------------------------------------------------------
# evaluate() — uses an in-memory stub harness so we don't spin up the stack
# ---------------------------------------------------------------------------
class _StubHarness(BenchmarkHarness):
    """Overrides :meth:`search` so ``evaluate`` runs without a real vector store."""

    def __init__(self, canned_hits: dict[str, list[dict[str, Any]]]) -> None:
        super().__init__(profile="raw")
        self._canned = canned_hits

    async def setup(self) -> None:  # pragma: no cover — not needed for these tests
        raise AssertionError("setup() should not be called in evaluate() stub tests")

    async def teardown(self) -> None:  # pragma: no cover
        return None

    async def search(self, text: str, n_results: int = 5) -> list[dict[str, Any]]:
        return self._canned.get(text, [])[:n_results]


class TestEvaluate:
    async def test_evaluate_invokes_scorer_per_query(self) -> None:
        queries = [
            BenchmarkQuery(id="q1", text="what is A", gold={"s-a"}),
            BenchmarkQuery(id="q2", text="what is B", gold={"s-b"}),
        ]
        canned = {
            "what is A": [
                {"id": "m1", "score": 0.9, "payload": {"session_id": "s-a"}},
                {"id": "m2", "score": 0.8, "payload": {"session_id": "s-x"}},
            ],
            "what is B": [
                {"id": "m3", "score": 0.9, "payload": {"session_id": "s-x"}},
            ],
        }
        harness = _StubHarness(canned)

        def scorer(query: BenchmarkQuery, hits: list[dict[str, Any]]) -> dict[str, Any]:
            retrieved = [h["payload"]["session_id"] for h in hits]
            return {
                "retrieved_session_ids": retrieved,
                "recall_at_k": bool(set(retrieved) & query.gold),
            }

        records = await harness.evaluate(queries, scorer=scorer, k=5)

        assert len(records) == 2
        by_id = {r["question_id"]: r for r in records}
        assert by_id["q1"]["recall_at_k"] is True
        assert by_id["q2"]["recall_at_k"] is False
        assert by_id["q1"]["gold"] == ["s-a"]
        assert by_id["q1"]["question"] == "what is A"


# ---------------------------------------------------------------------------
# Plan 12 PR-C: LLM wiring flag
# ---------------------------------------------------------------------------
class TestEnableLLMFlag:
    def test_raw_profile_disables_llm_by_default(self) -> None:
        h = BenchmarkHarness(profile="raw")
        assert h.enable_llm is False

    def test_enriched_profile_enables_llm_by_default(self) -> None:
        h = BenchmarkHarness(profile="enriched")
        assert h.enable_llm is True

    def test_dual_profile_enables_llm_by_default(self) -> None:
        h = BenchmarkHarness(profile="dual")
        assert h.enable_llm is True

    def test_explicit_enable_overrides_raw_default(self) -> None:
        # Allow forcing LLM on for a raw-profile run (rare but useful for
        # ablation studies)
        h = BenchmarkHarness(profile="raw", enable_llm=True)
        assert h.enable_llm is True

    def test_explicit_disable_overrides_enriched_default(self) -> None:
        # Useful when comparing an enriched-profile run against an LLM-off
        # baseline on the same chunking strategy
        h = BenchmarkHarness(profile="enriched", enable_llm=False)
        assert h.enable_llm is False

    def test_verbatim_alias_keeps_llm_off(self) -> None:
        # verbatim → raw → LLM off
        h = BenchmarkHarness(profile="verbatim")
        assert h.enable_llm is False

    def test_llm_alias_enables_llm(self) -> None:
        # llm → enriched → LLM on
        h = BenchmarkHarness(profile="llm")
        assert h.enable_llm is True
