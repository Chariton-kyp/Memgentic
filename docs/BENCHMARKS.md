# Memgentic Benchmarks

All benchmarks run on a Windows 11 / Intel-class machine with Qdrant in local
file mode and Ollama serving `qwen3-embedding:0.6b`. Numbers below are
placeholders and will be updated as the benchmark suite is executed.

Last updated: 2026-04-09 | Commit: TBD

## Ingestion

| Benchmark                        | Target       | Actual | Status |
| -------------------------------- | ------------ | ------ | ------ |
| 100 chunks ingestion             | <10s         | TBD    |        |
| Credential scrubbing throughput  | >50k chars/s | TBD    |        |
| Noise filter throughput          | >10k items/s | TBD    |        |

## Search

| Benchmark                               | Target | Actual | Status |
| --------------------------------------- | ------ | ------ | ------ |
| hybrid_search p50 over 1k memories      | <200ms | TBD    |        |
| hybrid_search p95 over 1k memories      | <500ms | TBD    |        |
| hybrid_search p50 over 10k memories     | <400ms | TBD    |        |
| FTS5 keyword search p50                 | <50ms  | TBD    |        |
| Semantic-only (Qdrant) search p50       | <150ms | TBD    |        |

## Storage

| Benchmark                       | Target | Actual | Status |
| ------------------------------- | ------ | ------ | ------ |
| get_memories_batch(100)         | <100ms | TBD    |        |
| save_memories_batch(100)        | <1s    | TBD    |        |

## Reproduction

Benchmarks live in `memgentic/tests/test_benchmarks.py` and are gated by the
`benchmark` pytest marker so they do not run by default.

```bash
cd memgentic
uv run python -m pytest tests/test_benchmarks.py -v -m benchmark
```

The tests use mocked stores and synthetic data, so they run fully offline —
no Ollama or Qdrant server required. Results are appended to a
session-scoped JSON file via the `benchmark_recorder` fixture and can be
copied into this document.
