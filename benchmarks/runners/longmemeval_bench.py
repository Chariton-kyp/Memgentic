"""LongMemEval runner.

A thin shell over :class:`benchmarks.lib.harness.BenchmarkHarness`
plus :func:`benchmarks.lib.corpus_loader.load_longmemeval`; everything
reusable lives in those modules so the same pattern drives LoCoMo,
ConvoMem, MemBench and Cross-Tool Transfer in later PRs.

Usage::

    python -m benchmarks.runners.longmemeval_bench \\
        --dataset /path/to/longmemeval_s.json \\
        --profile raw \\
        --k 5

Phase 1 does NOT auto-download the dataset. When ``--dataset`` points at
a missing file the runner prints a clear error and exits ``2`` so CI
failures are easy to distinguish from a runtime exception.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

from benchmarks.lib.corpus_loader import CorpusLoaderError, load_longmemeval
from benchmarks.lib.harness import BenchmarkHarness


async def run(
    dataset_path: str | Path,
    profile: str = "raw",
    k: int = 5,
    output_dir: str | Path = "benchmarks/results",
    *,
    harness: BenchmarkHarness | None = None,
    retrieval_mode: str = "dense",
    dense_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> Path:
    """Run LongMemEval end-to-end and write the JSONL result file.

    Matches the LongMemEval pattern: build harness → ingest every
    haystack session → score every question → write JSONL → print the
    aggregate ``R@k`` number. Returns the path to the JSONL for the caller.

    Args:
        dataset_path: Path to the LongMemEval JSON file on disk.
        profile: Capture profile forwarded to the ingestion pipeline.
        k: Top-k cut-off for recall@k.
        output_dir: Root of the benchmark-results tree.
        harness: Optional pre-built harness (for tests). When omitted,
            the runner builds and tears down its own.
    """
    sessions, questions = load_longmemeval(dataset_path)

    if harness is None:
        owns_harness = True
        active = BenchmarkHarness(profile=profile, embedder="qwen3-0.6b", backend="sqlite-vec")
        await active.setup()
    else:
        owns_harness = False
        active = harness
    try:
        for session in sessions:
            await active.ingest_session(session)

        records: list[dict[str, Any]] = []
        for question in questions:
            if retrieval_mode == "hybrid":
                hits = await active.search_hybrid(
                    question.text,
                    n_results=k,
                    dense_weight=dense_weight,
                    bm25_weight=bm25_weight,
                )
            else:
                hits = await active.search(question.text, n_results=k)
            retrieved_session_ids = [(h.get("payload") or {}).get("session_id") for h in hits]
            retrieved_session_ids = [sid for sid in retrieved_session_ids if sid is not None]
            recall = any(sid in question.gold for sid in retrieved_session_ids)
            rank_of_gold = next(
                (i + 1 for i, sid in enumerate(retrieved_session_ids) if sid in question.gold),
                None,
            )
            records.append(
                {
                    "question_id": question.id,
                    "question": question.text,
                    "gold_session_ids": sorted(question.gold),
                    "retrieved_session_ids": retrieved_session_ids,
                    "rank_of_gold": rank_of_gold,
                    "recall_at_k": recall,
                    "category": question.category,
                }
            )

        # Phase 2 output layout: results/{dataset}/{profile}/{timestamp}.jsonl
        # so sweeps across profiles / reruns never clobber each other.
        timestamp = _dt.datetime.now(tz=_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(output_dir) / "longmemeval" / profile / f"{timestamp}.jsonl"
        active.write_jsonl(records, out_path)

        if records:
            recall_rate = sum(1 for r in records if r["recall_at_k"]) / len(records)
            print(f"R@{k} = {recall_rate:.4f}  (n={len(records)}, profile={profile})")
        else:
            print(f"R@{k} = n/a  (no questions in dataset, profile={profile})")

        return out_path
    finally:
        if owns_harness:
            await active.teardown()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "LongMemEval retrieval benchmark runner. Phase 1 skeleton — "
            "requires the dataset to already be on disk (see "
            "benchmarks/datasets/README.md)."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/datasets/longmemeval_s.json"),
        help="Path to the LongMemEval JSON file on disk.",
    )
    parser.add_argument(
        "--profile",
        default="raw",
        choices=["raw", "enriched", "dual"],
        help=(
            "Capture profile. Phase 1 records the label; "
            "Capture Profiles wiring lands with plan 07."
        ),
    )
    parser.add_argument("--k", type=int, default=5, help="Top-k for R@k.")
    parser.add_argument(
        "--retrieval-mode",
        default="dense",
        choices=["dense", "hybrid"],
        help=(
            "Retrieval mode: 'dense' uses vector search only (PR-A baseline); "
            "'hybrid' fuses dense + BM25/FTS5 via reciprocal rank fusion "
            "(Plan 12 PR-D). Default: dense."
        ),
    )
    parser.add_argument(
        "--dense-weight",
        type=float,
        default=1.0,
        help="RRF weight for the dense list when --retrieval-mode hybrid.",
    )
    parser.add_argument(
        "--bm25-weight",
        type=float,
        default=1.0,
        help="RRF weight for the BM25 list when --retrieval-mode hybrid.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/results"),
        help="Where to write the JSONL results file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.dataset.exists():
        print(
            f"error: LongMemEval dataset not found at {args.dataset}.\n"
            "Phase-1 runners do not auto-download datasets.\n"
            "Run benchmarks/datasets/download.sh or pass --dataset explicitly.",
            file=sys.stderr,
        )
        return 2

    try:
        asyncio.run(
            run(
                args.dataset,
                profile=args.profile,
                k=args.k,
                output_dir=args.output_dir,
                retrieval_mode=args.retrieval_mode,
                dense_weight=args.dense_weight,
                bm25_weight=args.bm25_weight,
            )
        )
    except CorpusLoaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
