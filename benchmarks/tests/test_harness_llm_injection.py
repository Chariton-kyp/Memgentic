"""The harness can inject a distiller LLM client into the ingest pipeline.

Without this, ``BenchmarkHarness`` hardcodes ``llm_client=None`` so distillation
falls back to the heuristic — which would unfairly floor the distilled recall
surface in the A/B measurement (T8).
"""

from __future__ import annotations

import pytest

import benchmarks.lib.harness as hmod
from benchmarks.lib.harness import BenchmarkHarness


def _require_stack() -> None:
    try:
        import memgentic.storage.metadata  # noqa: F401
        import memgentic.storage.vectors  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"Memgentic stack not importable: {exc}")


async def test_no_llm_model_leaves_client_none() -> None:
    _require_stack()
    harness = BenchmarkHarness(profile="enriched", backend="sqlite-vec")
    await harness.setup()
    try:
        assert harness._pipeline._llm_client is None  # type: ignore[attr-defined]
    finally:
        await harness.teardown()


async def test_llm_model_injects_built_client(monkeypatch) -> None:
    _require_stack()
    sentinel = object()
    captured: dict = {}

    def _fake_build(settings, raw_model, phase_label):
        captured["model"] = raw_model
        captured["phase"] = phase_label
        return sentinel

    monkeypatch.setattr(hmod, "_build_phase_llm", _fake_build)

    harness = BenchmarkHarness(
        profile="enriched", backend="sqlite-vec", llm_model="claude-sonnet-4-6"
    )
    await harness.setup()
    try:
        assert captured["model"] == "claude-sonnet-4-6"
        assert harness._pipeline._llm_client is sentinel  # type: ignore[attr-defined]
    finally:
        await harness.teardown()
