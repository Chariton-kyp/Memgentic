# Memgentic Benchmarks

Reproducible retrieval benchmarks for Memgentic. This directory ships the
harness, scorers, corpus loaders, and a LongMemEval runner skeleton. The
full benchmark runs — and the numbers that appear in
[`BENCHMARKS.md`](BENCHMARKS.md) — land in a separate PR after the
Capture Profiles feature merges.

## Status

**Phase 1 (this repo, today):** harness + scorers + corpus loaders +
LongMemEval runner skeleton. No datasets are downloaded in CI, and no
results have been published yet.

**Phase 2 (Week 4):** full runs for LongMemEval, LoCoMo, ConvoMem,
MemBench, and the Memgentic-only Cross-Tool Transfer benchmark. Results
will be committed as JSONL under [`results/`](results/).

## Methodology

We measure **retrieval recall** — given a question, does the correct
source session land in the top-k memories returned by Memgentic's
semantic search? We do **not** measure end-to-end QA accuracy: the LLM
that turns retrieved context into an answer is orthogonal to the memory
layer and would muddy a comparison across tools.

Every run is scoped to a single **capture profile** (`raw`, `enriched`,
`dual`) so we can honestly report the trade-off between capture cost
(LLM calls at ingest time) and retrieval quality.

## Running locally

Phase 1 does not auto-download datasets. Once you have a LongMemEval
JSON file on disk:

```bash
python -m benchmarks.runners.longmemeval_bench \
    --dataset path/to/longmemeval_s.json \
    --profile raw \
    --k 5
```

Without a dataset the runner exits with a clear error (status code 2)
so CI distinguishes "missing input" from "runtime bug".

## Running in Docker

A pinned Docker image lives at [`docker/Dockerfile`](docker/Dockerfile).
It installs a pinned Memgentic commit, sets up Ollama and the
Qwen3-Embedding-0.6B model, and stages the dataset download script.
See [`BENCHMARKS.md`](BENCHMARKS.md) for the reproducibility contract.

## Directory layout

```
benchmarks/
├── README.md               ← you are here
├── BENCHMARKS.md           ← methodology + published numbers (phase 2)
├── datasets/
│   ├── README.md           ← upstream sources and download notes
│   └── download.sh         ← URLs, not executed in CI
├── runners/
│   └── longmemeval_bench.py
├── results/                ← populated by phase-2 runs
├── lib/
│   ├── harness.py          ← BenchmarkHarness (shared loop)
│   ├── corpus_loader.py    ← dataset → harness objects
│   └── scorers.py          ← R@k, MRR, precision@k
├── docker/
│   └── Dockerfile
└── tests/                  ← CI-friendly unit tests + tiny fixtures
```

## Tests

The CI suite runs unit tests against the harness, scorers, and corpus
loader. There are no full benchmark runs in CI — a full LongMemEval run
takes ≥30 minutes, which is incompatible with PR feedback latency. A
tiny 10-question fixture under [`tests/fixtures/`](tests/fixtures/) is
used only for regression detection.
