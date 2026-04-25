"""Hybrid retrieval — fusion of multiple ranked candidate lists.

Plan 12 §7 PR-D: combine dense vector retrieval with BM25/FTS5 (and any
future signal — graph PPR, cluster bonus, etc.) into a single ranked
list. Reciprocal Rank Fusion (RRF) is the default because it is
parameter-stable across heterogeneous score scales: vector cosine,
sqlite FTS5 ``rank`` (ascending = better), and PageRank values are
not comparable as raw scores. RRF normalises by rank position only.

References
----------
- Cormack, Clarke & Buettcher (2009): "Reciprocal Rank Fusion outperforms
  Condorcet and individual Rank Learning Methods." SIGIR. The k=60
  constant in the formula is the canonical default.

This module is intentionally I/O-free. Callers (the harness, MCP tools,
or future cascade orchestrator) are responsible for actually running
each retrieval strategy and feeding the results in.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeVar

T = TypeVar("T")

DEFAULT_RRF_K = 60
"""Smoothing constant from Cormack et al. 2009. Larger values flatten
contributions of high-ranked items relative to low-ranked items.
60 is the canonical default and gives stable results across most
heterogeneous-score-scale fusion tasks."""


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[T]],
    k: int = DEFAULT_RRF_K,
    weights: Sequence[float] | None = None,
) -> list[tuple[T, float]]:
    """Fuse N ranked candidate lists via Reciprocal Rank Fusion.

    For each item ``x`` in any input list, the RRF score is::

        score(x) = sum over lists of (weight_i / (k + rank_i(x)))

    where ``rank_i(x)`` is the 1-indexed position of ``x`` in the i-th
    list (or contributes zero if ``x`` is absent from that list).

    Args:
        ranked_lists: One ranked sequence per retrieval strategy. Each
            sequence is best-first (rank 1 = top). Items must be hashable
            (memory IDs, session IDs, tuples — anything ``set``-friendly).
        k: RRF smoothing constant. Default 60 per Cormack et al.
        weights: Optional per-list weight. Defaults to uniform 1.0 across
            all lists. Use weights to bias one strategy (e.g. dense > BM25).
            ``len(weights)`` must equal ``len(ranked_lists)`` when given.

    Returns:
        ``[(item, fused_score), ...]`` sorted by fused_score descending.
        Order across ties follows first-seen position across input lists.

    Raises:
        ValueError: when ``weights`` length does not match
            ``ranked_lists`` or when ``k <= 0``.
    """
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k}")
    if weights is not None and len(weights) != len(ranked_lists):
        raise ValueError(
            f"weights length ({len(weights)}) must equal "
            f"ranked_lists length ({len(ranked_lists)})"
        )

    effective_weights: Sequence[float] = (
        weights if weights is not None else [1.0] * len(ranked_lists)
    )

    fused: dict[T, float] = {}
    first_seen: dict[T, tuple[int, int]] = {}  # (list_index, rank) for stable tiebreaking
    for list_idx, ranked in enumerate(ranked_lists):
        weight = effective_weights[list_idx]
        if weight == 0.0:
            continue
        for rank, item in enumerate(ranked, start=1):
            contribution = weight / (k + rank)
            fused[item] = fused.get(item, 0.0) + contribution
            if item not in first_seen:
                first_seen[item] = (list_idx, rank)

    return sorted(
        fused.items(),
        key=lambda kv: (-kv[1], first_seen[kv[0]][0], first_seen[kv[0]][1]),
    )


def weighted_score_fusion(
    scored_lists: Sequence[Sequence[tuple[T, float]]],
    weights: Sequence[float] | None = None,
    *,
    normalize: bool = True,
) -> list[tuple[T, float]]:
    """Fuse N ranked candidate lists via weighted sum of normalized scores.

    Use this when the input scores ARE comparable across strategies (e.g.
    you've calibrated dense and BM25 to a common scale). For raw cosine
    + FTS5 rank fusion, prefer :func:`reciprocal_rank_fusion`.

    Args:
        scored_lists: One ``(item, score)`` sequence per strategy,
            best-first.
        weights: Optional per-list weight. Defaults to uniform 1.0.
        normalize: When True (default) each list is min-max normalised to
            [0, 1] before weighting so scale differences don't dominate.

    Returns:
        ``[(item, fused_score), ...]`` sorted descending.
    """
    if weights is not None and len(weights) != len(scored_lists):
        raise ValueError(
            f"weights length ({len(weights)}) must equal "
            f"scored_lists length ({len(scored_lists)})"
        )

    effective_weights: Sequence[float] = (
        weights if weights is not None else [1.0] * len(scored_lists)
    )

    fused: dict[T, float] = {}
    first_seen: dict[T, tuple[int, int]] = {}
    for list_idx, scored in enumerate(scored_lists):
        weight = effective_weights[list_idx]
        if weight == 0.0 or not scored:
            continue
        if normalize:
            scores = [s for _, s in scored]
            lo, hi = min(scores), max(scores)
            scale = hi - lo if hi > lo else 1.0
        else:
            lo, scale = 0.0, 1.0
        for rank, (item, raw_score) in enumerate(scored, start=1):
            normed = (raw_score - lo) / scale if normalize else raw_score
            fused[item] = fused.get(item, 0.0) + weight * normed
            if item not in first_seen:
                first_seen[item] = (list_idx, rank)

    return sorted(
        fused.items(),
        key=lambda kv: (-kv[1], first_seen[kv[0]][0], first_seen[kv[0]][1]),
    )


def _coerce_to_id_list(
    items: Iterable[T] | Iterable[tuple[T, float]],
) -> list[T]:
    """Accept either ``[id, ...]`` or ``[(id, score), ...]`` and return ``[id, ...]``.

    Convenience for callers that have raw search results in either shape.
    """
    out: list[T] = []
    for entry in items:
        if isinstance(entry, tuple) and len(entry) == 2:
            out.append(entry[0])  # type: ignore[arg-type]
        else:
            out.append(entry)  # type: ignore[arg-type]
    return out
