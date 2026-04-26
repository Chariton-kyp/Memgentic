"""Apply :class:`QueryFeatures`-derived boosts to a list of scored candidates.

Take a ranked candidate pool (output of dense / hybrid / rerank
retrieval) and re-score each entry by combining the original retrieval
score with multiplicative boosts derived from the query features:

- **Quoted phrase exact match** in candidate content → 1.6x boost
  (configurable). Matches the user's most explicit signal.
- **Proper-noun mention** in candidate content → 1.4x per unique name
  (capped). Names carry strong identity signal that 600M-parameter
  sentence embeddings smear out.
- **Temporal proximity** between candidate ``created_at`` and the
  query's referenced time window → smooth boost peaking at the target
  date (Gaussian-style decay over 30 days). Implicit anchors like
  "yesterday" use a tighter window than "last year".

Pure function, no I/O. Callers (bench runner / hybrid_search) feed in
the candidates + a :class:`QueryFeatures` and get the re-sorted list
back. When ``QueryFeatures`` is empty (no extracted signals) the input
order is preserved.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections.abc import Sequence
from typing import Any

from memgentic.processing.query_features import QueryFeatures

# Default multipliers — tuned starting from sibling-project values
# ([0.6, 1.4, 1.6] for keyword/name/quoted) but conservative on the
# proper-noun side to avoid runaway scores when a query mentions many
# names. The exact numbers are call-site overridable for A/B tuning.
DEFAULT_QUOTED_BOOST = 1.6
DEFAULT_PROPER_NOUN_BOOST = 1.4
DEFAULT_PROPER_NOUN_CAP = 2.0  # max compound boost from many proper nouns
DEFAULT_TEMPORAL_PEAK = 1.5
DEFAULT_TEMPORAL_SIGMA_DAYS = 30.0  # Gaussian sigma around target date


def _temporal_score(
    candidate_created_at: _dt.datetime | None,
    target_days_back: float,
    *,
    now: _dt.datetime,
    peak: float = DEFAULT_TEMPORAL_PEAK,
    sigma_days: float = DEFAULT_TEMPORAL_SIGMA_DAYS,
) -> float:
    """Multiplicative temporal-proximity boost.

    Gaussian centred on ``now - target_days_back``: candidates landing
    near the target date get up to ``peak``; candidates many sigma away
    contribute 1.0 (no penalty, just no boost).

    Returns 1.0 when the candidate has no ``created_at`` so the absence
    of timestamp metadata never penalises a result.
    """
    if candidate_created_at is None:
        return 1.0
    candidate_days_back = (now - candidate_created_at).total_seconds() / 86400.0
    distance = abs(candidate_days_back - target_days_back)
    bell = math.exp(-((distance / max(sigma_days, 1e-6)) ** 2))
    return 1.0 + (peak - 1.0) * bell


def _parse_created_at(payload: dict[str, Any]) -> _dt.datetime | None:
    """Robust ISO-8601 parse from payload dict; returns None on miss/error."""
    raw = payload.get("created_at") if isinstance(payload, dict) else None
    if not raw:
        return None
    if isinstance(raw, _dt.datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=_dt.UTC)
    try:
        # Accept both "2026-04-26T08:00:00+00:00" and "...Z" suffix.
        text = raw.replace("Z", "+00:00") if isinstance(raw, str) else str(raw)
        parsed = _dt.datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.UTC)
    except (TypeError, ValueError):
        return None


def apply_feature_boosts(
    candidates: Sequence[dict[str, Any]],
    features: QueryFeatures,
    *,
    now: _dt.datetime | None = None,
    quoted_boost: float = DEFAULT_QUOTED_BOOST,
    proper_noun_boost: float = DEFAULT_PROPER_NOUN_BOOST,
    proper_noun_cap: float = DEFAULT_PROPER_NOUN_CAP,
    temporal_peak: float = DEFAULT_TEMPORAL_PEAK,
    temporal_sigma_days: float = DEFAULT_TEMPORAL_SIGMA_DAYS,
) -> list[dict[str, Any]]:
    """Return a re-ranked copy of ``candidates`` with feature boosts applied.

    The original ``score`` field on each candidate is preserved as
    ``raw_score``; the new fused score lives on ``score`` so downstream
    code (bench dedup, MCP responses) keeps working unchanged.

    When ``features`` is empty (no extractor fired) the function still
    returns a copy of the input list — same order, same scores. Callers
    should still set the new fields so JSON output is uniform across
    queries.
    """
    if not candidates:
        return []

    now = now or _dt.datetime.now(tz=_dt.UTC)
    quoted_lower = [q.lower() for q in features.quoted_phrases]
    nouns_lower = [n.lower() for n in features.proper_nouns]
    temporal = features.temporal_reference_days

    boosted: list[dict[str, Any]] = []
    for cand in candidates:
        payload = cand.get("payload") or {}
        content = (payload.get("content") or "")
        content_lower = content.lower() if isinstance(content, str) else ""

        multiplier = 1.0

        # Quoted phrase: any exact substring match → boost once.
        if quoted_lower and any(q in content_lower for q in quoted_lower):
            multiplier *= quoted_boost

        # Proper noun: each distinct name found multiplies, capped to avoid
        # runaway when a query enumerates many names.
        if nouns_lower:
            hits = sum(1 for n in nouns_lower if n in content_lower)
            if hits:
                noun_mult = min(proper_noun_boost ** hits, proper_noun_cap)
                multiplier *= noun_mult

        # Temporal proximity to the target window.
        if temporal is not None:
            created_at = _parse_created_at(payload)
            multiplier *= _temporal_score(
                created_at,
                temporal,
                now=now,
                peak=temporal_peak,
                sigma_days=temporal_sigma_days,
            )

        new_cand = dict(cand)
        raw = float(cand.get("score") or 0.0)
        new_cand["raw_score"] = raw
        new_cand["score"] = raw * multiplier
        new_cand["boost_multiplier"] = round(multiplier, 4)
        boosted.append(new_cand)

    boosted.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return boosted
