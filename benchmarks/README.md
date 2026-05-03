# Memgentic Benchmarks

Reproducible retrieval benchmarks for Memgentic. This directory ships
the harness, scorers, corpus loaders, and runner scripts for
LongMemEval, LoCoMo, ConvoMem, MemBench, and the Memgentic-only
Cross-Tool Transfer benchmark. Published numbers in
[`BENCHMARKS.md`](BENCHMARKS.md) are populated by running the suite
locally.

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

The runners never auto-download datasets. Fetch them once with
[`datasets/download.sh`](datasets/download.sh) (or pass `--dataset` to a
file you already have), then invoke any runner as a module:

```bash
python -m benchmarks.runners.longmemeval_bench          --profile raw --k 5
python -m benchmarks.runners.locomo_bench               --profile raw --k 10
python -m benchmarks.runners.convomem_bench             --profile raw --k 5
python -m benchmarks.runners.membench_bench             --profile raw --k 5
python -m benchmarks.runners.cross_tool_transfer_bench  --profile raw --k 5
```

Each runner writes a timestamped JSONL to
`benchmarks/results/{dataset}/{profile}/{timestamp}.jsonl` and prints the
headline metric on stdout. Without a dataset the runner exits with a
clear error (status code 2) so CI can distinguish "missing input" from
"runtime bug".

For the full reproducibility walk-through (Ollama setup, download,
profile sweep, target numbers) see
[`../docs/BENCHMARKS.md`](../docs/BENCHMARKS.md#reproducibility).

## Running in Docker

A pinned Docker image lives at [`docker/Dockerfile`](docker/Dockerfile).
It installs a pinned Memgentic commit, sets up Ollama and the
Qwen3-Embedding-0.6B model, and stages the dataset download script.
See [`BENCHMARKS.md`](BENCHMARKS.md) for the reproducibility contract.

## Directory layout

```
benchmarks/
├── README.md               ← you are here
├── BENCHMARKS.md           ← methodology + published numbers
├── datasets/
│   ├── README.md           ← upstream sources and download notes
│   ├── download.sh         ← URLs, not executed in CI
│   └── cross_tool_transfer/
│       ├── README.md       ← schema for the Memgentic-original dataset
│       └── example.jsonl   ← 5-row fixture for smoke tests
├── runners/
│   ├── longmemeval_bench.py
│   ├── locomo_bench.py
│   ├── convomem_bench.py
│   ├── membench_bench.py
│   └── cross_tool_transfer_bench.py
├── results/                ← populated by local runs (gitignored empty)
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
