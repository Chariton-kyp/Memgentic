"""MemBench runner.

Format v1 — verify against upstream on first real run. MemBench
(ACL 2025) ships ~8.5k questions as JSONL. Same shape as the other
runners: load → ingest → search → write JSONL under
``benchmarks/results/membench/{profile}/{timestamp}.jsonl``.

Full MemBench runs are long (hours) and are NOT expected to be run in
CI — this runner is shipped so maintainers can reproduce the published
numbers locally.

Usage::

    python -m benchmarks.runners.membench_bench \\
        --dataset benchmarks/datasets/membench.jsonl \\
        --profile raw \\
        --k 5
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

from benchmarks.lib.corpus_loader import CorpusLoaderError, load_membench
from benchmarks.lib.harness import BenchmarkHarness


async def run(
    dataset_path: str | Path,
    profile: str = "raw",
    k: int = 5,
    output_dir: str | Path = "benchmarks/results",
    *,
    harness: BenchmarkHarness | None = None,
) -> Path:
    """Run MemBench end-to-end and write the JSONL result file."""
    sessions, questions = load_membench(dataset_path)

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
            hits = await active.search(question.text, n_results=k)
            retrieved_session_ids = [
                sid
                for sid in ((h.get("payload") or {}).get("session_id") for h in hits)
                if sid is not None
            ]
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

        timestamp = _dt.datetime.now(tz=_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(output_dir) / "membench" / profile / f"{timestamp}.jsonl"
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
            "MemBench retrieval benchmark runner. Requires the dataset "
            "to already be on disk (see benchmarks/datasets/README.md)."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/datasets/membench.jsonl"),
        help="Path to the MemBench JSONL file on disk.",
    )
    parser.add_argument(
        "--profile",
        default="raw",
        choices=["raw", "enriched", "dual"],
        help="Capture profile forwarded to the ingestion pipeline.",
    )
    parser.add_argument("--k", type=int, default=5, help="Top-k for R@k.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/results"),
        help="Root of the benchmark-results tree.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.dataset.exists():
        print(
            f"error: MemBench dataset not found at {args.dataset}.\n"
            "Run benchmarks/datasets/download.sh or pass --dataset explicitly.",
            file=sys.stderr,
        )
        return 2
    try:
        asyncio.run(run(args.dataset, profile=args.profile, k=args.k, output_dir=args.output_dir))
    except CorpusLoaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
