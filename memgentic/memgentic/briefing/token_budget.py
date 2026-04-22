"""Adaptive token-budget resolver for the Recall Tiers stack.

The budget scales with the detected model context window: small
context → tight T1 cap; huge context (e.g. 1M-token Gemini) → larger
T1 cap but still bounded to avoid useless bloat.

No ``tiktoken`` dependency — we use the standard GPT-style
``len(text) // 4`` heuristic. It's good enough for a sanity check;
we never pay per-token and agents see the text regardless. If the
underlying model disagrees by a factor of 2, the wake-up is still
well under the context window.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

TierName = Literal["T0", "T1", "T2", "T3", "T4"]

# Hard cap so that even on 1M-context models we don't dump unbounded
# T1 content — plan §12: "cap at 25 memories to avoid useless bloat".
MAX_HORIZON_MEMORIES = 25

DEFAULT_MODEL_CONTEXT = 128_000
MODEL_CONTEXT_ENV_VAR = "MEMGENTIC_MODEL_CONTEXT"


@dataclass(frozen=True)
class BudgetResolution:
    """Resolved budget for a single tier call.

    ``tokens`` is the recommended prompt-text cap for the tier, and
    ``max_memories`` is the hard upper bound on memory rows included
    in T1 (ignored for T2–T4 where the limit is query-driven).
    """

    tier: TierName
    tokens: int
    max_memories: int
    model_context: int


# Per-tier tables. Horizon is the only one the plan tunes explicitly.
_HORIZON_TABLE: tuple[tuple[int, int, int], ...] = (
    # (context_upper_exclusive, token_cap, memory_cap)
    (32_000, 400, 8),
    (200_000, 800, 15),
    (10_000_000, 1500, MAX_HORIZON_MEMORIES),
)

_PERSONA_TOKENS = 120  # T0 is always tight — Persona.render_t0 aims for < 200.
_ORBIT_DEFAULT = 500
_DEEP_RECALL_DEFAULT = 1500  # Deep-recall is unlimited in practice; soft cap.
_ATLAS_DEFAULT = 800


def detect_model_context(override: int | None = None) -> int:
    """Return the model context window in tokens.

    Resolution order:

    1. Explicit ``override`` argument (used by CLI ``--model-context``).
    2. ``MEMGENTIC_MODEL_CONTEXT`` environment variable.
    3. Default :data:`DEFAULT_MODEL_CONTEXT` (128k — Claude, GPT-4, etc.).

    Non-positive values and unparseable env strings fall through to
    the default rather than raising.
    """
    if override is not None and override > 0:
        return int(override)
    raw = os.environ.get(MODEL_CONTEXT_ENV_VAR)
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return DEFAULT_MODEL_CONTEXT
        if value > 0:
            return value
    return DEFAULT_MODEL_CONTEXT


def _horizon_caps(model_context: int) -> tuple[int, int]:
    """Return ``(token_cap, memory_cap)`` for T1 given the context size."""
    for upper, tokens, memories in _HORIZON_TABLE:
        if model_context < upper:
            return tokens, memories
    # Fallthrough: very large contexts — keep the generous cap.
    return _HORIZON_TABLE[-1][1], _HORIZON_TABLE[-1][2]


def resolve_budget(
    tier: TierName,
    model_context: int | None = None,
    *,
    max_tokens: int | None = None,
) -> BudgetResolution:
    """Resolve the budget for ``tier`` given the current model context.

    ``max_tokens`` is a per-call override (e.g. MCP ``max_tokens``
    param) that clamps the computed value downward — never upward —
    so callers can tighten but not exceed the tier's own ceiling.
    """
    context = detect_model_context(model_context)

    if tier == "T0":
        tokens = _PERSONA_TOKENS
        memories = 0
    elif tier == "T1":
        tokens, memories = _horizon_caps(context)
    elif tier == "T2":
        tokens = _ORBIT_DEFAULT
        memories = 12
    elif tier == "T3":
        tokens = _DEEP_RECALL_DEFAULT
        memories = 20
    elif tier == "T4":
        tokens = _ATLAS_DEFAULT
        memories = 15
    else:  # pragma: no cover — Literal guard
        raise ValueError(f"Unknown tier: {tier}")

    if max_tokens is not None and max_tokens > 0:
        tokens = min(tokens, int(max_tokens))

    return BudgetResolution(
        tier=tier,
        tokens=tokens,
        max_memories=memories,
        model_context=context,
    )


def estimate_tokens(text: str) -> int:
    """Rough token count using the ``len(text) // 4`` heuristic.

    Accurate enough for the "did I blow the budget?" check we do in the
    tier formatters. We intentionally avoid pulling in ``tiktoken`` so
    the core package stays dependency-light; if the heuristic is off by
    2×, the wake-up still fits comfortably inside even a 32k window.
    """
    if not text:
        return 0
    # Round up for conservatism — a 10-char string is 3 tokens, not 2.
    return max(1, (len(text) + 3) // 4)


__all__ = [
    "DEFAULT_MODEL_CONTEXT",
    "MAX_HORIZON_MEMORIES",
    "MODEL_CONTEXT_ENV_VAR",
    "BudgetResolution",
    "TierName",
    "detect_model_context",
    "estimate_tokens",
    "resolve_budget",
]
