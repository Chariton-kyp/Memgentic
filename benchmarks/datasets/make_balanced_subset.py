"""Build a small balanced subset of LongMemEval for fast retrieval-change A/B.

The shipped 50q subset is 100% ``single-session-user`` — a single category
that exercises only the easy path (one session contains the answer
verbatim). It can't distinguish retrieval changes that target the harder
multi-session, temporal-reasoning, or knowledge-update categories.

This script samples N questions per category from ``longmemeval_s.json``
with a fixed seed so the subset is reproducible. Default 10 per category
gives 60 questions across 6 categories — small enough that a full bench
run completes in 25-30 minutes, balanced enough that RRF / reranker /
chunking changes show measurable per-category deltas.

Usage::

    python -m benchmarks.datasets.make_balanced_subset \\
        --in benchmarks/datasets/longmemeval_s.json \\
        --out benchmarks/datasets/longmemeval_s_balanced_60.json \\
        --per-category 10
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


DEFAULT_SEED = 42  # matches benchmarks/BENCHMARKS.md §Reproducibility


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample a category-balanced subset of LongMemEval.",
    )
    parser.add_argument(
        "--in",
        dest="in_path",
        type=Path,
        default=Path("benchmarks/datasets/longmemeval_s.json"),
        help="Path to the full LongMemEval JSON file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output JSON path for the balanced subset.",
    )
    parser.add_argument(
        "--per-category",
        type=int,
        default=10,
        help="Questions to sample per question_type bucket (default 10).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed (default {DEFAULT_SEED}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rng = random.Random(args.seed)

    full = json.loads(args.in_path.read_text(encoding="utf-8"))
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for q in full:
        by_cat[q["question_type"]].append(q)

    sampled: list[dict] = []
    summary: dict[str, int] = {}
    for cat, items in sorted(by_cat.items()):
        n = min(args.per_category, len(items))
        picks = rng.sample(items, n)
        sampled.extend(picks)
        summary[cat] = n
        print(f"  {cat:<32} sampled {n} of {len(items)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sampled, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"wrote {len(sampled)} questions -> {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
