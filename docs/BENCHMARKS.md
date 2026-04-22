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

---

# Retrieval Benchmarks

The numbers above measure **ingestion / search latency** — throughput and
wall-clock under load. A separate suite under [`benchmarks/`](../benchmarks/)
measures **retrieval quality** against published academic datasets
(LongMemEval, LoCoMo, ConvoMem, MemBench) plus a Memgentic-original
**Cross-Tool Transfer** dataset. See
[`benchmarks/README.md`](../benchmarks/README.md) for the methodology and
[`benchmarks/BENCHMARKS.md`](../benchmarks/BENCHMARKS.md) for the published
numbers table.

## Reproducibility

Every retrieval benchmark is runnable end-to-end from a clean clone. The
runners do **not** auto-download datasets — licensing varies and the files
are large — so the first step is always to fetch them.

### 1. Install Memgentic + dev dependencies

```bash
uv sync
```

### 2. Start Ollama with the pinned embedding model

```bash
make pull-models            # pulls Qwen3-Embedding-0.6B into Ollama
ollama serve &              # background
```

### 3. Download the datasets you want to run

```bash
bash benchmarks/datasets/download.sh
```

This fetches LongMemEval, LoCoMo, ConvoMem, and MemBench into
`benchmarks/datasets/`. The script is idempotent — files already on disk
are skipped. The Cross-Tool Transfer dataset lives under version control at
`benchmarks/datasets/cross_tool_transfer/example.jsonl` (the 100-row full
dataset lands in a later PR; the 5-row fixture is enough to smoke-test the
pipeline).

### 4. Run each benchmark once per capture profile

```bash
# LongMemEval — 500 questions, ~15–30 min on M2 Pro
for profile in raw enriched dual; do
    python -m benchmarks.runners.longmemeval_bench --profile "$profile"
done

# LoCoMo
for profile in raw enriched dual; do
    python -m benchmarks.runners.locomo_bench --profile "$profile" --k 10
done

# ConvoMem
for profile in raw enriched dual; do
    python -m benchmarks.runners.convomem_bench --profile "$profile"
done

# MemBench — largest; expect hours on CPU-only hardware
for profile in raw enriched dual; do
    python -m benchmarks.runners.membench_bench --profile "$profile"
done

# Cross-Tool Transfer — Memgentic-original
for profile in raw enriched dual; do
    python -m benchmarks.runners.cross_tool_transfer_bench --profile "$profile"
done
```

Each command writes a timestamped JSONL to
`benchmarks/results/{dataset}/{profile}/{timestamp}.jsonl` and prints the
headline metric (R@k or p@k) on stdout.

### 5. Compare to targets

| Benchmark | Metric | Target | Source |
|---|---|---|---|
| LongMemEval (raw) | R@5 | ≥ 96.6% | MemPalace published baseline |
| LoCoMo | R@10 | ≥ 85% | hybrid v5 in the LoCoMo paper |
| ConvoMem | avg recall | ≥ 90% | ConvoMem paper (92.9% their best) |
| Cross-Tool Transfer | precision@5 | ≥ 70% | Memgentic-original — first public number |

If a number falls short, publish it honestly — the project policy is to
print real results rather than cherry-pick the best run. Rerun with a
different profile or hardware and note the delta.

## Results

_pending actual runs_ — the table below is populated only after local
benchmark sessions complete. See
[`benchmarks/BENCHMARKS.md`](../benchmarks/BENCHMARKS.md) for the canonical
results table and per-profile breakdown.

| Benchmark | Profile | Metric | Value | Date | Commit |
|---|---|---|---|---|---|
| LongMemEval | raw      | R@5        | _TBD_ | — | — |
| LongMemEval | enriched | R@5        | _TBD_ | — | — |
| LongMemEval | dual     | R@5        | _TBD_ | — | — |
| LoCoMo      | raw      | R@10       | _TBD_ | — | — |
| ConvoMem    | raw      | avg recall | _TBD_ | — | — |
| MemBench    | raw      | R@5        | _TBD_ | — | — |
| Cross-Tool  | raw      | p@5        | _TBD_ | — | — |
