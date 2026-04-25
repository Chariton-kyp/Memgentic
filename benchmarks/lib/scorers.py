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


# ---------------------------------------------------------------------------
# Plan 12 Phase 0 PR-B — session-level aggregation
# ---------------------------------------------------------------------------
#
# Memgentic's vector store retrieves at memory-chunk granularity. A single
# session usually splits into 5-20 chunks, so chunk-level top-5 results
# routinely contain only 1-3 distinct sessions — the rest of the slots are
# duplicates. Benchmarks like LongMemEval score at session granularity
# (gold = "which session contains the answer"), so chunk-level top-k can
# rank gold at chunk #6 (after 3 duplicates of session A and 2 decoys) and
# the question is scored as a miss even though the gold session was clearly
# in the candidate pool.
#
# The fix is a scoring change, not an architecture change: over-fetch
# chunks at the runner level (e.g. ``n_results = k * over_fetch_factor``),
# then aggregate by session_id keeping the best (max) chunk score per
# session, and score against the top-k *distinct* sessions. This change
# exists in scorers.py — not in the production retrieval path — because
# the product still returns chunks (which is what users want for "what
# did I say about X"). Only the benchmark scorer collapses to session
# level, matching the benchmark's gold granularity.


def aggregate_chunks_to_sessions(
    chunk_hits: Sequence[tuple[Any, float]],
) -> list[tuple[Any, float]]:
    """Collapse chunk-level retrieval to a session-level ranked list.

    Takes an ordered (best-first) sequence of ``(session_id, score)``
    chunk hits and returns the same kind of list with each ``session_id``
    appearing at most once and ranked by its best (max) chunk score.

    ``session_id`` may be ``None`` for chunks whose payload was missing
    the field; those rows are dropped silently.

    The function is order-stable: ties on score keep the first-seen
    (i.e. better-ranked) session ahead of later duplicates.
    """
    best_per_session: dict[Any, float] = {}
    first_seen_index: dict[Any, int] = {}
    for idx, (session_id, score) in enumerate(chunk_hits):
        if session_id is None:
            continue
        if session_id not in best_per_session or score > best_per_session[session_id]:
            best_per_session[session_id] = score
        if session_id not in first_seen_index:
            first_seen_index[session_id] = idx
    return sorted(
        best_per_session.items(),
        key=lambda kv: (-kv[1], first_seen_index[kv[0]]),
    )


def recall_at_k_session_aggregated(
    chunk_hits: Sequence[tuple[Any, float]],
    gold: Iterable[Any],
    k: int,
) -> bool:
    """Session-aggregated R@k — does any gold session appear in the top-``k``
    *distinct* sessions after collapsing chunk duplicates?
    """
    distinct_sessions = aggregate_chunks_to_sessions(chunk_hits)
    return recall_at_k([sid for sid, _ in distinct_sessions], gold, k)


def rank_of_gold_session_aggregated(
    chunk_hits: Sequence[tuple[Any, float]],
    gold: Iterable[Any],
) -> int | None:
    """1-indexed rank of the first gold session in the deduplicated session
    list, or ``None`` if no gold session is present.
    """
    gold_set = _gold_set(gold)
    if not gold_set:
        return None
    distinct_sessions = aggregate_chunks_to_sessions(chunk_hits)
    for idx, (session_id, _) in enumerate(distinct_sessions, start=1):
        if session_id in gold_set:
            return idx
    return None
