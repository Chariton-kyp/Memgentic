"""Retrieval metrics for benchmark runners.

All functions are pure — they take ranked hits and a gold set, and return
a scalar. No I/O, no dataset knowledge. Runner-specific parsing happens
in ``benchmarks/runners/`` and is fed here.

Conventions
-----------
* ``hits`` is an ordered sequence (best-first) of identifiers. Each identifier
  can be anything hashable — a session_id, a memory_id, a tuple — as long as
  it matches the ``gold`` set.
* ``gold`` is the set (or iterable) of identifiers considered correct.
* ``k`` truncates ``hits`` to the top-k before scoring. When ``k`` is larger
  than ``len(hits)`` we score against whatever is available (no padding).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def _truncate(hits: Sequence[Any], k: int) -> Sequence[Any]:
    if k <= 0:
        raise ValueError(f"k must be >= 1, got {k}")
    return hits[:k]


def _gold_set(gold: Iterable[Any]) -> set[Any]:
    return set(gold) if not isinstance(gold, set) else gold


def recall_at_k(hits: Sequence[Any], gold: Iterable[Any], k: int) -> bool:
    """Binary recall@k — did the top-``k`` hits contain *any* gold item?

    LongMemEval-style recall: there is typically a single gold session per
    question and we care whether it landed in the top-k. Returns ``True``
    when the intersection of top-k hits with ``gold`` is non-empty.
    """
    gold_set = _gold_set(gold)
    if not gold_set:
        return False
    top = _truncate(hits, k)
    return any(h in gold_set for h in top)


def mean_reciprocal_rank(ranked_hits: Sequence[Any], gold: Iterable[Any]) -> float:
    """MRR for a single query — reciprocal of the 1-indexed rank of the
    first gold hit, or 0.0 if no gold item is in the ranking.

    To compute MRR across a query set, average the per-query values at the
    caller. This function intentionally scores one query so it composes with
    any aggregation strategy.
    """
    gold_set = _gold_set(gold)
    if not gold_set:
        return 0.0
    for idx, hit in enumerate(ranked_hits, start=1):
        if hit in gold_set:
            return 1.0 / idx
    return 0.0


def precision_at_k(hits: Sequence[Any], gold: Iterable[Any], k: int) -> float:
    """Precision@k — fraction of the top-``k`` hits that are gold.

    When ``len(hits) < k`` we still divide by ``k`` (the standard IR
    convention) so short result lists are penalised, not hidden.
    """
    gold_set = _gold_set(gold)
    if not gold_set:
        return 0.0
    top = _truncate(hits, k)
    relevant = sum(1 for h in top if h in gold_set)
    return relevant / k
