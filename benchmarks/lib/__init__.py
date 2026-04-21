"""Shared benchmark harness, corpus loaders, and scorers.

See ``memgentic-strategy/11-PLAN-BENCHMARKS.md`` for the full methodology
(maintainer-only notes; not included in the public repo).
"""

from benchmarks.lib.harness import BenchmarkHarness
from benchmarks.lib.scorers import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    "BenchmarkHarness",
    "mean_reciprocal_rank",
    "precision_at_k",
    "recall_at_k",
]
