"""Memgentic Recall Tiers — progressive context loader (T0–T4).

Replaces the ad-hoc ``memgentic_briefing`` time-window dump with a
structured five-tier stack that caps wake-up cost at 600–900 tokens
and lets agents pull deeper context on demand.

Tier overview:

- **T0 Persona** — ~100 tokens from ``~/.memgentic/persona.yaml``.
- **T1 Horizon** — top-N memories ranked by a hybrid importance ×
  recency × pinned × cluster × skill-link score; MMR de-duplicated.
- **T2 Orbit** — memories filtered by collection / topic.
- **T3 Deep Recall** — full hybrid semantic + FTS5 search.
- **T4 Atlas** — knowledge-graph traversal around an entity.

The default :class:`RecallStack.briefing` call returns T0 + T1 only;
explicit tier calls go through :meth:`RecallStack.tier_recall`. Token
budgets auto-scale to the detected model context (see
:mod:`memgentic.briefing.token_budget`).

Public API:

- :class:`RecallStack` — bundles the five tier classes.
- :func:`get_briefing` — ergonomic wrapper that builds a stack,
  renders T0+T1, and returns the assembled text.
"""

from __future__ import annotations

from memgentic.briefing.formatters import (
    format_atlas_tier,
    format_deep_recall_tier,
    format_horizon_tier,
    format_orbit_tier,
    format_persona_tier,
)
from memgentic.briefing.scorer import (
    ScorerWeights,
    default_weights,
    load_weights,
    score_memories,
    select_with_mmr,
)
from memgentic.briefing.tiers import (
    AtlasTier,
    BriefingContext,
    DeepRecallTier,
    HorizonTier,
    OrbitTier,
    PersonaTier,
    RecallStack,
    TierOutput,
    get_briefing,
)
from memgentic.briefing.token_budget import (
    BudgetResolution,
    detect_model_context,
    estimate_tokens,
    resolve_budget,
)

__all__ = [
    "AtlasTier",
    "BriefingContext",
    "BudgetResolution",
    "DeepRecallTier",
    "HorizonTier",
    "OrbitTier",
    "PersonaTier",
    "RecallStack",
    "ScorerWeights",
    "TierOutput",
    "default_weights",
    "detect_model_context",
    "estimate_tokens",
    "format_atlas_tier",
    "format_deep_recall_tier",
    "format_horizon_tier",
    "format_orbit_tier",
    "format_persona_tier",
    "get_briefing",
    "load_weights",
    "resolve_budget",
    "score_memories",
    "select_with_mmr",
]
