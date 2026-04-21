"""Shared benchmark harness, corpus loaders, and scorers.

See :doc:`/benchmarks/BENCHMARKS` for the public methodology and
reproducibility contract.
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
