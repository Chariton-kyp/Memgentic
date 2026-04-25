# Memgentic Published Benchmarks

This document is the canonical place for Memgentic's retrieval benchmark
numbers. It is intentionally empty of results today — Phase 1 of the
benchmark rollout ships only the harness and runner skeletons, so there
is no data to publish yet. Numbers will land after the Capture Profiles
work (plan 07) merges and the full Phase 2 runs complete.

## Methodology (summary)

| Item | Value |
|---|---|
| Metric | Retrieval recall only. No end-to-end QA scoring. |
| Embedder | Qwen3-Embedding-0.6B (768d MRL-truncated), served via Ollama |
| Vector DB | sqlite-vec (default) |
| Random seed | `42` — used for any sampling / shuffling inside the harness |
| Ranking | Top-k from the vector store; no reranking in baseline runs |

Each benchmark is run three times: once per capture profile (`raw`,
`enriched`, `dual`) so the community can see the cost-vs-recall
trade-off directly. Capture Profiles is plan 07 in the maintainer
strategy; when it merges, the harness's `profile` argument will wire it
in end-to-end without runner changes.

## Reproducibility contract

Every published results file records the following fields so any
reader can regenerate the numbers or flag drift:

* **Memgentic version** — commit SHA of `main` when the run was taken
* **Embedder** — model name plus SHA-256 checksum of the Ollama blob
* **Capture profile** — one of `raw`, `enriched`, `dual`
* **Dataset version** — upstream commit SHA pinned in `datasets/README.md`
* **Hardware** — CPU model, GPU (if any), RAM
* **Wall-clock time** — ingest + evaluate, reported separately

The Docker image at [`docker/Dockerfile`](docker/Dockerfile) installs
Memgentic from a pinned commit and the embedding model from a pinned
Ollama tag. Re-running the benchmark with the same image on comparable
hardware should produce numbers within ±0.5 percentage points.

The rationale behind each of these requirements (pinned image,
pinned model, seed, required report fields) is that benchmark
numbers are only useful if a third party can reproduce them on
comparable hardware and get the same answer.

## Results

### LongMemEval R@5 — by capture profile

| Profile | R@5 | Subset | LLM in pipeline | Date | Commit | Result file |
|---|---|---|---|---|---|---|
| raw      | **0.6000 (30/50)** | first 50q of `longmemeval_s_cleaned` | None (heuristic-only fallback fired throughout — Plan 12 PR-C will fix this) | 2026-04-22 | `c0f796d8` (feat/benchmarks-harness) | [`results_longmemeval_raw_20260422_baseline.jsonl`](results/results_longmemeval_raw_20260422_baseline.jsonl) + [`.meta.json`](results/results_longmemeval_raw_20260422_baseline.meta.json) |
| enriched | _TBD — needs Plan 12 Phase 0 PR-C (LLM-wiring fix in benchmarks/lib/harness.py)_ | — | Qwen3.5-4B (planned) | — | — | — |
| dual     | _TBD — same gate as enriched_ | — | Qwen3.5-4B (planned) | — | — | — |

**Status note (2026-04-22)**: The `raw` row is the first Memgentic baseline number committed to this repo. It establishes the `R@5 = 60%` starting point against which Plan 12 Phase 0 PRs B/C/D/E will report attribution. The full 500-question run is pending (~3.5h estimated wall-clock); the 50-question subset is the working dev split.

### LoCoMo R@10 — session-top-10

| Variant | R@10 | Date | Commit |
|---|---|---|---|
| baseline | _TBD_ | — | — |
| hybrid v5 | _TBD_ | — | — |

### ConvoMem — avg recall across 5 categories

| Variant | avg recall | Date | Commit |
|---|---|---|---|
| baseline | _TBD_ | — | — |

### MemBench R@5

| Variant | R@5 | Date | Commit |
|---|---|---|---|
| baseline | _TBD_ | — | — |

### Cross-Tool Transfer (Memgentic-original)

| Variant | precision@5 | Date | Commit |
|---|---|---|---|
| baseline | _TBD — Memgentic-original benchmark_ | — | — |

## Comparing to MemPalace

MemPalace publishes its own retrieval benchmarks for a comparable
single-tool configuration. When Phase 2 lands we will link to
MemPalace's `BENCHMARKS.md` (with commit SHA and date) next to each of
our numbers so readers can compare like-for-like. We will not print a
"beat them by X" headline when results sit within noise — the table
above lets readers draw their own conclusions.
