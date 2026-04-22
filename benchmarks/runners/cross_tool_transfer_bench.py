"""Cross-Tool Transfer runner (Memgentic-original benchmark).

Format v1 — verify against upstream on first real run. This is
Memgentic's own benchmark: capture conversations via multiple adapters
(Claude Code, ChatGPT, Gemini CLI, Aider, …) then ask a follow-up
question that references information from a *different* tool than the
asker. Scoring uses precision@k because each question may have
multiple legitimate gold memories.

Dataset format (one JSON object per line)::

    {"role": "turn",  "tool": "claude_code", "turn": 1,
     "content": "...",  "session_id": "s-001"}
    {"role": "query", "tool": "chatgpt",
     "content": "Remind me what we said about X",
     "ground_truth_memory_ids": ["s-001"]}

The loader accepts records without a ``role`` field too — records with
a non-empty ``ground_truth_memory_ids`` list are treated as queries,
otherwise as conversation turns. See
``benchmarks/datasets/cross_tool_transfer/README.md`` for the
authoritative schema and the tiny ``example.jsonl`` fixture.

Usage::

    python -m benchmarks.runners.cross_tool_transfer_bench \\
        --dataset benchmarks/datasets/cross_tool_transfer/example.jsonl \\
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

from benchmarks.lib.corpus_loader import CorpusLoaderError, load_cross_tool_transfer
from benchmarks.lib.harness import BenchmarkHarness
from benchmarks.lib.scorers import precision_at_k


async def run(
    dataset_path: str | Path,
    profile: str = "raw",
    k: int = 5,
    output_dir: str | Path = "benchmarks/results",
    *,
    harness: BenchmarkHarness | None = None,
) -> Path:
    """Run Cross-Tool Transfer end-to-end and write the JSONL result file."""
    sessions, questions = load_cross_tool_transfer(dataset_path)

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
            p_at_k = precision_at_k(retrieved_session_ids, question.gold, k=k)
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
                    "precision_at_k": p_at_k,
                    "source_tool": (question.metadata or {}).get("source_tool"),
                    "target_tool": (question.metadata or {}).get("target_tool"),
                    "category": question.category,
                }
            )

        timestamp = _dt.datetime.now(tz=_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(output_dir) / "cross_tool_transfer" / profile / f"{timestamp}.jsonl"
        active.write_jsonl(records, out_path)

        if records:
            mean_p = sum(r["precision_at_k"] for r in records) / len(records)
            print(f"p@{k} = {mean_p:.4f}  (n={len(records)}, profile={profile})")
        else:
            print(f"p@{k} = n/a  (no queries in dataset, profile={profile})")

        return out_path
    finally:
        if owns_harness:
            await active.teardown()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-Tool Transfer benchmark runner (Memgentic-original). "
            "Evaluates retrieval of memories captured in one tool when "
            "asked from a different tool's session."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/datasets/cross_tool_transfer/example.jsonl"),
        help=(
            "Path to the Cross-Tool Transfer JSONL file on disk. The tiny "
            "fixture at benchmarks/datasets/cross_tool_transfer/example.jsonl "
            "is committed; the full 100-conversation set is curated separately."
        ),
    )
    parser.add_argument(
        "--profile",
        default="raw",
        choices=["raw", "enriched", "dual"],
        help="Capture profile forwarded to the ingestion pipeline.",
    )
    parser.add_argument("--k", type=int, default=5, help="Top-k cut-off for precision@k.")
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
            f"error: Cross-Tool Transfer dataset not found at {args.dataset}.\n"
            "See benchmarks/datasets/cross_tool_transfer/README.md for the "
            "schema, or run against example.jsonl for a smoke test.",
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
