"""Compare two LongMemEval JSONL result files side-by-side.

Use cases:
- A/B between baseline and a retrieval change ("did weighted RRF help?")
- Confirm a refactor didn't regress recall ("R@5 still 0.74?")
- Per-category breakdown so a model that wins overall but loses on a
  critical bucket gets flagged.

Each input JSONL must follow the runner's schema: one record per
question with at minimum ``question_id``, ``recall_at_k``,
``rank_of_gold``, and ``category``.

Usage::

    python -m benchmarks.runners.compare_runs old.jsonl new.jsonl
    python -m benchmarks.runners.compare_runs old.jsonl new.jsonl --json delta.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunStats:
    label: str
    n: int
    recall_at_k: float
    mrr: float
    by_category: dict[str, dict[str, float]]
    per_question: dict[str, dict]


def _load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _summarize(records: list[dict], label: str) -> RunStats:
    n = len(records)
    recall_count = sum(1 for r in records if r.get("recall_at_k"))
    # MRR over questions where gold appears anywhere; questions without
    # gold contribute 0 (matches LongMemEval's MRR convention).
    mrr_total = 0.0
    for r in records:
        rank = r.get("rank_of_gold")
        if rank is not None and rank > 0:
            mrr_total += 1.0 / rank

    # Per-category aggregates
    by_cat_records: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        cat = r.get("category", "unknown")
        by_cat_records[cat].append(r)

    by_category = {
        cat: {
            "n": len(rs),
            "recall_at_k": (sum(1 for r in rs if r.get("recall_at_k")) / len(rs))
            if rs
            else 0.0,
            "mrr": (
                sum(1.0 / r["rank_of_gold"] for r in rs if r.get("rank_of_gold")) / len(rs)
            )
            if rs
            else 0.0,
        }
        for cat, rs in by_cat_records.items()
    }

    per_question = {r["question_id"]: r for r in records if "question_id" in r}

    return RunStats(
        label=label,
        n=n,
        recall_at_k=recall_count / n if n else 0.0,
        mrr=mrr_total / n if n else 0.0,
        by_category=by_category,
        per_question=per_question,
    )


def _print_summary(old: RunStats, new: RunStats) -> None:
    print()
    header = f"{'metric':<25} {'old':>10} {'new':>10} {'delta':>10}"
    print(header)
    print("-" * len(header))

    def pp(metric: str, o: float, n: float, fmt: str = "{:.4f}") -> None:
        delta = n - o
        sign = "+" if delta >= 0 else ""
        print(
            f"{metric:<25} {fmt.format(o):>10} {fmt.format(n):>10} "
            f"{sign}{fmt.format(delta):>9}"
        )

    pp("R@k", old.recall_at_k, new.recall_at_k)
    pp("MRR", old.mrr, new.mrr)
    print(f"{'n questions':<25} {old.n:>10} {new.n:>10}")
    print()


def _print_per_category(old: RunStats, new: RunStats) -> None:
    cats = sorted(set(old.by_category) | set(new.by_category))
    print(f"{'category':<28} {'n':>4} {'old R@k':>8} {'new R@k':>8} {'d R@k':>8}  "
          f"{'old MRR':>8} {'new MRR':>8} {'d MRR':>8}")
    print("-" * 96)
    for cat in cats:
        o = old.by_category.get(cat, {"n": 0, "recall_at_k": 0.0, "mrr": 0.0})
        nc = new.by_category.get(cat, {"n": 0, "recall_at_k": 0.0, "mrr": 0.0})
        n_count = max(o.get("n", 0), nc.get("n", 0))
        d_recall = nc["recall_at_k"] - o["recall_at_k"]
        d_mrr = nc["mrr"] - o["mrr"]
        print(
            f"{cat:<28} {n_count:>4} "
            f"{o['recall_at_k']:>8.4f} {nc['recall_at_k']:>8.4f} {d_recall:>+8.4f}  "
            f"{o['mrr']:>8.4f} {nc['mrr']:>8.4f} {d_mrr:>+8.4f}"
        )
    print()


def _print_movers(old: RunStats, new: RunStats, n: int = 10) -> None:
    """Top-n questions that flipped recall (false->true) and (true->false)."""
    fixed: list[str] = []
    broken: list[str] = []
    common = set(old.per_question) & set(new.per_question)
    for qid in common:
        o = old.per_question[qid]
        nq = new.per_question[qid]
        if not o.get("recall_at_k") and nq.get("recall_at_k"):
            fixed.append(qid)
        elif o.get("recall_at_k") and not nq.get("recall_at_k"):
            broken.append(qid)

    print(f"Fixed (false->true): {len(fixed)} questions")
    for qid in fixed[:n]:
        q = new.per_question[qid]
        print(f"  {qid}  rank {q.get('rank_of_gold')}  {q.get('question', '')[:70]}")
    print()
    print(f"Broken (true->false): {len(broken)} questions")
    for qid in broken[:n]:
        q = new.per_question[qid]
        print(f"  {qid}  rank {q.get('rank_of_gold')}  {q.get('question', '')[:70]}")
    print()


def _print_rank_distribution(old: RunStats, new: RunStats) -> None:
    """Median / p10 / p90 of rank-of-gold across questions where gold appears."""
    def stats(records_iter) -> tuple[float, float, float] | None:
        ranks = [r["rank_of_gold"] for r in records_iter if r.get("rank_of_gold")]
        if not ranks:
            return None
        med = statistics.median(ranks)
        if len(ranks) >= 10:
            qs = statistics.quantiles(ranks, n=10)
            return (qs[0], med, qs[8])
        return (min(ranks), med, max(ranks))

    o = stats(old.per_question.values())
    n = stats(new.per_question.values())
    print("Rank-of-gold distribution (lower = better):")
    print(f"  old: p10={o[0] if o else '-'}  median={o[1] if o else '-'}  p90={o[2] if o else '-'}")
    print(f"  new: p10={n[0] if n else '-'}  median={n[1] if n else '-'}  p90={n[2] if n else '-'}")
    print()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two LongMemEval JSONL runs and print delta tables.",
    )
    parser.add_argument("old", type=Path, help="Baseline JSONL")
    parser.add_argument("new", type=Path, help="New JSONL to compare against baseline")
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the per-category + per-question delta to JSON for tracking.",
    )
    parser.add_argument(
        "--movers",
        type=int,
        default=10,
        help="Number of fixed/broken questions to list (default 10).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.old.exists():
        print(f"error: {args.old} does not exist", file=sys.stderr)
        return 2
    if not args.new.exists():
        print(f"error: {args.new} does not exist", file=sys.stderr)
        return 2

    old_records = _load_jsonl(args.old)
    new_records = _load_jsonl(args.new)
    old = _summarize(old_records, label=str(args.old.name))
    new = _summarize(new_records, label=str(args.new.name))

    print(f"old: {args.old}")
    print(f"new: {args.new}")
    _print_summary(old, new)
    _print_rank_distribution(old, new)
    _print_per_category(old, new)
    _print_movers(old, new, n=args.movers)

    if args.json:
        payload = {
            "old_path": str(args.old),
            "new_path": str(args.new),
            "old_recall_at_k": old.recall_at_k,
            "new_recall_at_k": new.recall_at_k,
            "delta_recall_at_k": new.recall_at_k - old.recall_at_k,
            "old_mrr": old.mrr,
            "new_mrr": new.mrr,
            "delta_mrr": new.mrr - old.mrr,
            "by_category_old": old.by_category,
            "by_category_new": new.by_category,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"delta written -> {args.json}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
