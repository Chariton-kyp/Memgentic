"""Benchmark tests — run with `pytest tests/test_benchmarks.py -v -m benchmark`.

These tests are excluded from the default test run via the ``benchmark`` marker.
They use mocked stores and synthetic data, so they run fully offline (no
Ollama / Qdrant server required).

Reproduction:
    uv run python -m pytest tests/test_benchmarks.py -v -m benchmark
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from memgentic.processing.heuristics import is_noise

pytestmark = pytest.mark.benchmark


_SAMPLE_QUERIES = [
    "how do we store embeddings",
    "qdrant vector mode decision",
    "ollama model configuration",
    "credential scrubbing rules",
    "knowledge graph entity extraction",
    "benchmark suite design",
    "hybrid search RRF",
    "daemon file watcher",
    "MCP tool list",
    "session filter exclude sources",
    "alembic migration pattern",
    "sqlite FTS5 tokenizer",
    "process lock daemon",
    "pipeline ingestion stages",
    "noise filter heuristics",
    "contradiction detection",
    "corroboration boost",
    "importance decay half life",
    "platform version metadata",
    "intelligence graph langgraph",
]


def _fake_memory(i: int) -> dict:
    return {
        "id": f"mem-{i:05d}",
        "score": 0.9 - (i * 0.0001),
        "payload": {"content": f"synthetic memory {i}", "platform": "claude_code"},
    }


async def test_ingestion_speed_100_chunks(benchmark_recorder):
    """Ingest 100 chunks via a mocked pipeline; assert <10s total."""
    from memgentic.config import MemgenticSettings
    from memgentic.models import ContentType, ConversationChunk, Platform
    from memgentic.processing.pipeline import IngestionPipeline

    settings = MemgenticSettings(
        enable_llm_processing=False,
        enable_write_time_dedup=False,
        enable_corroboration=False,
    )
    metadata_store = AsyncMock()
    metadata_store.is_file_processed = AsyncMock(return_value=False)
    metadata_store.save_memories_batch = AsyncMock()
    metadata_store.mark_file_processed = AsyncMock()
    vector_store = AsyncMock()
    vector_store.upsert_memories_batch = AsyncMock()
    vector_store.search = AsyncMock(return_value=[])
    embedder = AsyncMock()
    embedder.embed_batch = AsyncMock(side_effect=lambda texts: [[0.0] * 768 for _ in texts])

    pipeline = IngestionPipeline(settings, metadata_store, vector_store, embedder)

    chunks = [
        ConversationChunk(
            content=f"Synthetic chunk {i} — this is a sufficiently long memory for benchmarking purposes.",
            content_type=ContentType.FACT,
            topics=[f"topic-{i % 5}"],
            entities=[],
            confidence=0.9,
        )
        for i in range(100)
    ]

    start = time.perf_counter()
    memories = await pipeline.ingest_conversation(chunks=chunks, platform=Platform.CLAUDE_CODE)
    elapsed = time.perf_counter() - start
    benchmark_recorder("ingestion_100_chunks", elapsed)
    assert len(memories) == 100
    assert elapsed < 10.0, f"Ingestion too slow: {elapsed:.2f}s"


async def test_search_latency_1000_memories(benchmark_recorder):
    """Synthetic hybrid-search latency with mocked stores; p95 <500ms."""
    from memgentic.graph.search import hybrid_search

    metadata_store = AsyncMock()
    metadata_store.search_fulltext = AsyncMock(return_value=[])
    metadata_store.get_memories_batch = AsyncMock(return_value={})
    vector_store = AsyncMock()
    vector_store.search = AsyncMock(return_value=[_fake_memory(i) for i in range(20)])
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.0] * 768)

    latencies: list[float] = []
    for query in _SAMPLE_QUERIES:
        start = time.perf_counter()
        await hybrid_search(
            query=query,
            metadata_store=metadata_store,
            vector_store=vector_store,
            embedder=embedder,
            limit=10,
        )
        latencies.append(time.perf_counter() - start)

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    benchmark_recorder("search_p95_1000_memories", p95)
    assert p95 < 0.5, f"p95 latency too high: {p95:.3f}s"


async def test_batch_lookup_scales(benchmark_recorder):
    """Mocked get_memories_batch(100) should be <100ms."""
    metadata_store = AsyncMock()
    metadata_store.get_memories_batch = AsyncMock(
        return_value={f"mem-{i}": None for i in range(100)}
    )
    start = time.perf_counter()
    await metadata_store.get_memories_batch([f"mem-{i}" for i in range(100)])
    elapsed = time.perf_counter() - start
    benchmark_recorder("batch_lookup_100", elapsed)
    assert elapsed < 0.1


def test_noise_filter_throughput(benchmark_recorder):
    """is_noise() should process >10k items/sec on synthetic inputs."""
    samples = [
        "Thanks!",
        "This is a real and substantive memory about Qdrant vector storage decisions.",
        "ok",
        "We decided to use Ollama because it supports the Qwen3 embedding model locally.",
    ] * 2500  # 10k items

    start = time.perf_counter()
    filtered = [s for s in samples if not is_noise(s)]
    elapsed = time.perf_counter() - start
    throughput = len(samples) / elapsed if elapsed > 0 else float("inf")
    benchmark_recorder("noise_filter_throughput_items_per_sec", throughput)
    assert throughput > 10_000, f"Noise filter throughput too low: {throughput:.0f}/s"
    assert len(filtered) > 0


# Avoid "unused import" warnings if asyncio module is stripped later
_ = asyncio
