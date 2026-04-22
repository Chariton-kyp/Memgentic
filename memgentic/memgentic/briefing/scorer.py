"""Hybrid scorer + MMR selector for the Horizon tier (T1).

The scoring formula combines five signals::

    score = w_importance * importance
          + w_recency    * exp(-age_days / tau)
          + w_pinned     * pinned_boost
          + w_cluster    * cluster_centrality
          + w_skill_link * links_to_active_skill

``cluster_centrality`` is optional — if no embeddings are available
for the candidate set (cold start, no vector cache hit), we fall back
to the importance+recency subset of the formula. ``skill_link`` is
also optional: with no usage signal on skills yet, we treat it as
zero for all memories but keep the weight configurable so the signal
can be added later without a migration.

Top-K selection uses **MMR (λ=0.5)** over the scored candidates.
Embeddings are loaded lazily in a single batch call so we never pay
an LLM round-trip per memory; if embeddings aren't available, MMR
degrades gracefully to score-ordered selection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memgentic.models import Memory

# Default scoring weights — tuned to match the Recall Tiers design:
# importance and recency dominate, pinned memories get a meaningful
# boost, and cluster / skill link are optional tie-breakers.
DEFAULT_WEIGHTS: dict[str, float] = {
    "importance": 0.30,
    "recency": 0.25,
    "pinned": 0.25,
    "cluster": 0.10,
    "skill_link": 0.10,
}

# Recency decay half-constant (days) — the ``tau`` in ``exp(-age/tau)``.
# 30 days keeps week-old memories strong and quarter-old ones faint.
DEFAULT_RECENCY_TAU_DAYS = 30.0

# MMR diversity constant — plan §2: "λ=0.5".
DEFAULT_MMR_LAMBDA = 0.5


@dataclass(frozen=True)
class ScorerWeights:
    """Typed weight bundle.

    Constructed from user config or the built-in defaults. All weights
    are finite non-negative floats — the validators enforce this so
    downstream math never sees NaN or negatives.
    """

    importance: float = DEFAULT_WEIGHTS["importance"]
    recency: float = DEFAULT_WEIGHTS["recency"]
    pinned: float = DEFAULT_WEIGHTS["pinned"]
    cluster: float = DEFAULT_WEIGHTS["cluster"]
    skill_link: float = DEFAULT_WEIGHTS["skill_link"]
    tau_days: float = DEFAULT_RECENCY_TAU_DAYS

    def __post_init__(self) -> None:
        for name in ("importance", "recency", "pinned", "cluster", "skill_link"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"weight {name!r} must be finite and >= 0; got {value!r}")
        if not math.isfinite(self.tau_days) or self.tau_days <= 0:
            raise ValueError(f"tau_days must be positive and finite; got {self.tau_days!r}")

    def as_dict(self) -> dict[str, float]:
        """Serialise as a plain mapping (useful for the REST weights endpoint)."""
        return {
            "importance": self.importance,
            "recency": self.recency,
            "pinned": self.pinned,
            "cluster": self.cluster,
            "skill_link": self.skill_link,
            "tau_days": self.tau_days,
        }


def default_weights() -> ScorerWeights:
    """Return a fresh :class:`ScorerWeights` with plan defaults."""
    return ScorerWeights()


def load_weights(
    overrides: dict[str, float] | None = None,
    *,
    config_path: Path | None = None,
) -> ScorerWeights:
    """Resolve scorer weights, with precedence ``overrides > config > defaults``.

    ``config_path`` accepts an optional YAML file containing a
    ``briefing.weights`` mapping; if the file or section is missing,
    we silently fall through to the defaults (this keeps first-run
    Memgentic working without any config).
    """
    resolved: dict[str, float] = {
        "importance": DEFAULT_WEIGHTS["importance"],
        "recency": DEFAULT_WEIGHTS["recency"],
        "pinned": DEFAULT_WEIGHTS["pinned"],
        "cluster": DEFAULT_WEIGHTS["cluster"],
        "skill_link": DEFAULT_WEIGHTS["skill_link"],
        "tau_days": DEFAULT_RECENCY_TAU_DAYS,
    }

    if config_path is not None and config_path.exists():
        try:
            import yaml

            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            section = (parsed.get("briefing") or {}).get("weights") or {}
            for key, value in section.items():
                if key in resolved and isinstance(value, (int, float)):
                    resolved[key] = float(value)
        except Exception:
            # Config is advisory — never let a bad YAML break the briefing.
            pass

    if overrides:
        for key, value in overrides.items():
            if key in resolved:
                try:
                    resolved[key] = float(value)
                except (TypeError, ValueError):
                    continue

    return ScorerWeights(**resolved)


def _recency_score(created_at: datetime, now: datetime, tau_days: float) -> float:
    """Exponential decay on age. Always in ``[0, 1]``."""
    if created_at.tzinfo is None:
        # The metadata store writes ISO with timezone, but be robust.
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return math.exp(-age_days / tau_days)


def _pinned_score(memory: Memory) -> float:
    return 1.0 if memory.is_pinned else 0.0


def _cluster_score(
    memory_id: str,
    embedding: list[float] | None,
    centroid: list[float] | None,
) -> float:
    """Cosine similarity to the cluster centroid, clipped to ``[0, 1]``.

    When either vector is missing we return 0 — a missing cluster
    signal should neither boost nor penalise a memory.
    """
    if not embedding or not centroid or len(embedding) != len(centroid):
        return 0.0
    num = 0.0
    a_sq = 0.0
    b_sq = 0.0
    for a, b in zip(embedding, centroid, strict=False):
        num += a * b
        a_sq += a * a
        b_sq += b * b
    if a_sq == 0 or b_sq == 0:
        return 0.0
    cos = num / math.sqrt(a_sq * b_sq)
    # Map cosine (range ``[-1, 1]`` in theory, but ~``[0, 1]`` for our
    # embeddings) into a pure score.
    return max(0.0, min(1.0, cos))


def _skill_link_score(
    memory: Memory,
    active_skills: list[str] | None,
) -> float:
    """Return 1.0 if any active-skill token appears in the memory's topics/entities.

    Without a per-skill usage counter on the current schema we can't
    weight by popularity, so we fall back to a boolean match. The
    scorer knob stays configurable — when usage tracking ships the
    signal strengthens without a schema migration.
    """
    if not active_skills:
        return 0.0
    needles = {s.lower() for s in active_skills if s}
    haystack = {t.lower() for t in memory.topics} | {e.lower() for e in memory.entities}
    return 1.0 if haystack & needles else 0.0


@dataclass
class ScoredMemory:
    """A memory with its final score and (optionally) its embedding.

    ``embedding`` is kept alongside so MMR can reuse it without a
    second lookup.
    """

    memory: Memory
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    embedding: list[float] | None = None


def score_memories(
    memories: list[Memory],
    *,
    weights: ScorerWeights | None = None,
    now: datetime | None = None,
    active_skills: list[str] | None = None,
    embeddings: dict[str, list[float]] | None = None,
    centroid: list[float] | None = None,
) -> list[ScoredMemory]:
    """Score every memory in the candidate set.

    The ``embeddings`` dict is keyed by memory ID; any memory missing
    an embedding simply scores 0 on the cluster term. Callers should
    fetch embeddings in a single batch before calling this function —
    we never invoke the embedder ourselves (keeps the core scorer
    synchronous and testable without mocks).
    """
    w = weights or default_weights()
    now = now or datetime.now(UTC)
    embed_map = embeddings or {}

    results: list[ScoredMemory] = []
    for memory in memories:
        importance = float(memory.importance_score or 0.0)
        recency = _recency_score(memory.created_at, now, w.tau_days)
        pinned = _pinned_score(memory)
        cluster = _cluster_score(memory.id, embed_map.get(memory.id), centroid)
        skill_link = _skill_link_score(memory, active_skills)

        score = (
            w.importance * importance
            + w.recency * recency
            + w.pinned * pinned
            + w.cluster * cluster
            + w.skill_link * skill_link
        )

        results.append(
            ScoredMemory(
                memory=memory,
                score=score,
                breakdown={
                    "importance": importance,
                    "recency": recency,
                    "pinned": pinned,
                    "cluster": cluster,
                    "skill_link": skill_link,
                },
                embedding=embed_map.get(memory.id),
            )
        )
    return results


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for the MMR diversity term."""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = 0.0
    a_sq = 0.0
    b_sq = 0.0
    for x, y in zip(a, b, strict=False):
        num += x * y
        a_sq += x * x
        b_sq += y * y
    if a_sq == 0 or b_sq == 0:
        return 0.0
    return num / math.sqrt(a_sq * b_sq)


def select_with_mmr(
    candidates: list[ScoredMemory],
    *,
    k: int,
    lambda_: float = DEFAULT_MMR_LAMBDA,
    preserve_pinned: bool = True,
) -> list[ScoredMemory]:
    """Greedy MMR selection with pinned-first preservation.

    When ``preserve_pinned`` is True, every pinned memory is kept
    regardless of budget — plan §12 makes this explicit ("pins are
    user intent"). Non-pinned candidates then fill the remaining slots
    using the standard MMR formula::

        mmr = λ·relevance - (1-λ)·max_sim(already_selected)

    If embeddings are missing, the diversity term collapses to 0 and
    selection falls back to score order. That's an acceptable
    degradation — the plan calls it out in §12 as the cold-start
    behaviour.
    """
    if k <= 0 or not candidates:
        return []

    ordered = sorted(candidates, key=lambda c: c.score, reverse=True)

    if not preserve_pinned:
        return _mmr_select(ordered, k=k, lambda_=lambda_)

    pinned = [c for c in ordered if c.memory.is_pinned]
    non_pinned = [c for c in ordered if not c.memory.is_pinned]

    # Pinned always pass through; they just don't get extra slots.
    keep = list(pinned)
    remaining = max(0, k - len(keep))
    if remaining > 0 and non_pinned:
        additions = _mmr_select(
            non_pinned,
            k=remaining,
            lambda_=lambda_,
            already_selected=list(keep),
        )
        keep.extend(additions)

    # Re-sort final selection by score for deterministic presentation.
    keep.sort(key=lambda c: c.score, reverse=True)
    return keep


def _mmr_select(
    candidates: list[ScoredMemory],
    *,
    k: int,
    lambda_: float,
    already_selected: list[ScoredMemory] | None = None,
) -> list[ScoredMemory]:
    """Inner MMR loop — shared between pinned-aware and plain paths."""
    selected: list[ScoredMemory] = list(already_selected or [])
    pool = list(candidates)
    target = k

    while pool and len(selected) - len(already_selected or []) < target:
        best_idx = 0
        best_mmr = -math.inf
        for idx, cand in enumerate(pool):
            diversity = 0.0
            if cand.embedding:
                for chosen in selected:
                    if chosen.embedding is None:
                        continue
                    sim = _cosine(cand.embedding, chosen.embedding)
                    if sim > diversity:
                        diversity = sim
            mmr = lambda_ * cand.score - (1.0 - lambda_) * diversity
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx
        selected.append(pool.pop(best_idx))

    # Strip the ``already_selected`` prefix so callers only see the new picks.
    return selected[len(already_selected or []) :]


def centroid_of(vectors: list[list[float]]) -> list[float] | None:
    """Compute the mean vector of a list of embeddings, or ``None`` if empty."""
    if not vectors:
        return None
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        return None
    out = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            out[i] += v[i]
    return [x / len(vectors) for x in out]


# Convenience alias used by a couple of tests / consumers.
def weights_from_dict(data: dict[str, Any]) -> ScorerWeights:
    """Build a :class:`ScorerWeights` from a plain dict.

    Unknown keys are ignored; missing keys fall back to defaults.
    """
    merged: dict[str, float] = {
        "importance": DEFAULT_WEIGHTS["importance"],
        "recency": DEFAULT_WEIGHTS["recency"],
        "pinned": DEFAULT_WEIGHTS["pinned"],
        "cluster": DEFAULT_WEIGHTS["cluster"],
        "skill_link": DEFAULT_WEIGHTS["skill_link"],
        "tau_days": DEFAULT_RECENCY_TAU_DAYS,
    }
    for key, value in (data or {}).items():
        if key in merged:
            try:
                merged[key] = float(value)
            except (TypeError, ValueError):
                continue
    return ScorerWeights(**merged)


__all__ = [
    "DEFAULT_MMR_LAMBDA",
    "DEFAULT_RECENCY_TAU_DAYS",
    "DEFAULT_WEIGHTS",
    "ScoredMemory",
    "ScorerWeights",
    "centroid_of",
    "default_weights",
    "load_weights",
    "score_memories",
    "select_with_mmr",
    "weights_from_dict",
]
