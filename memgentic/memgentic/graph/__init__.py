"""Knowledge graph package.

Exposes two complementary layers that coexist:

- :mod:`memgentic.graph.knowledge` — the legacy NetworkX co-occurrence
  graph (kept for backwards compatibility with existing hybrid search).
- :mod:`memgentic.graph.temporal` — the new bitemporal triple store
  (:class:`Chronograph`), with LLM extraction and user validation.

External callers — including the Recall Tiers Atlas layer — should use
:func:`get_chronograph`, :class:`Triple`, and :class:`Entity`.
"""

from memgentic.graph.temporal import (
    Chronograph,
    Entity,
    Triple,
    get_chronograph,
    reset_chronograph_cache,
)

__all__ = [
    "Chronograph",
    "Entity",
    "Triple",
    "get_chronograph",
    "reset_chronograph_cache",
]
