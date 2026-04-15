"""Tests for memgentic.observability — verifies no-op fallback behavior."""

from __future__ import annotations

import memgentic.observability as obs


def _reset() -> None:
    obs._tracer = None
    obs._meter = None
    obs._counters.clear()
    obs._histograms.clear()


def test_init_observability_without_extras_is_noop():
    """init_observability() must not raise and leaves state unset when
    extras are not installed."""
    _reset()
    obs.init_observability()
    if not obs._HAS_OTEL:
        assert obs._tracer is None
        assert obs._meter is None


def test_trace_span_without_init_is_noop():
    """trace_span() used as a context manager should yield cleanly with no
    tracer initialized."""
    _reset()
    with obs.trace_span("x", attr=1):
        pass  # no raise


def test_record_counter_without_init_is_noop():
    """record_counter() is a safe no-op when the meter is not initialized."""
    _reset()
    obs.record_counter("test", 1, label="a")
    obs.record_histogram("test_hist", 0.5, label="a")


def test_init_with_enabled_false_is_noop():
    """Calling init_observability(enabled=False) must leave state unset even
    when extras are installed."""
    _reset()
    obs.init_observability(enabled=False)
    assert obs._tracer is None
    assert obs._meter is None


async def test_instrumentation_hot_paths_do_not_raise():
    """Instrumented hot paths (pipeline, search, embedder) must not crash
    when observability is in no-op mode."""
    _reset()

    # trace_span + record_* used in hot paths
    with obs.trace_span("pipeline.ingest", chunks=3, platform="claude_code"):
        obs.record_counter("memgentic.memories.ingested", value=3, platform="claude_code")
        obs.record_histogram("memgentic.pipeline.duration_seconds", 0.123, platform="claude_code")

    with obs.trace_span("search.hybrid", query_len=10):
        obs.record_histogram("memgentic.search.duration_seconds", 0.05)
        obs.record_counter("memgentic.search.results", value=5)

    with obs.trace_span("embedder.embed", provider="ollama"):
        obs.record_histogram("memgentic.embedder.duration_seconds", 0.2, provider="ollama")
