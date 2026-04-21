"""Unit tests for the pure retrieval-metric helpers.

These tests are intentionally assertion-dense: the scorers feed every
published benchmark number, so a silent formula regression would flow
straight into the marketing collateral.
"""

from __future__ import annotations

import pytest

from benchmarks.lib.scorers import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
)


class TestRecallAtK:
    def test_hit_in_top_k(self) -> None:
        assert recall_at_k(["a", "b", "c"], {"b"}, k=3) is True

    def test_hit_exactly_at_k(self) -> None:
        assert recall_at_k(["a", "b", "c"], {"c"}, k=3) is True

    def test_hit_outside_top_k(self) -> None:
        assert recall_at_k(["a", "b", "c", "gold"], {"gold"}, k=3) is False

    def test_empty_hits(self) -> None:
        assert recall_at_k([], {"gold"}, k=5) is False

    def test_empty_gold(self) -> None:
        assert recall_at_k(["a", "b"], set(), k=5) is False

    def test_k_larger_than_hits_still_scores_available(self) -> None:
        assert recall_at_k(["a", "b"], {"a"}, k=10) is True

    def test_k_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            recall_at_k(["a"], {"a"}, k=0)

    def test_gold_may_be_iterable(self) -> None:
        # Lists, tuples, and generators should all work.
        assert recall_at_k(["a", "b"], ["b"], k=2) is True
        assert recall_at_k(["a", "b"], (x for x in {"b"}), k=2) is True


class TestMeanReciprocalRank:
    def test_gold_first(self) -> None:
        assert mean_reciprocal_rank(["gold", "b"], {"gold"}) == pytest.approx(1.0)

    def test_gold_second(self) -> None:
        assert mean_reciprocal_rank(["a", "gold", "c"], {"gold"}) == pytest.approx(0.5)

    def test_gold_fifth(self) -> None:
        assert mean_reciprocal_rank(["a", "b", "c", "d", "gold"], {"gold"}) == pytest.approx(0.2)

    def test_gold_missing(self) -> None:
        assert mean_reciprocal_rank(["a", "b"], {"gold"}) == 0.0

    def test_multiple_gold_takes_first_match(self) -> None:
        # The first gold item in the ranking wins, not the best ranked gold overall.
        assert mean_reciprocal_rank(["x", "g1", "g2"], {"g1", "g2"}) == pytest.approx(0.5)

    def test_empty_gold(self) -> None:
        assert mean_reciprocal_rank(["a", "b"], set()) == 0.0

    def test_empty_hits(self) -> None:
        assert mean_reciprocal_rank([], {"gold"}) == 0.0


class TestPrecisionAtK:
    def test_all_relevant(self) -> None:
        assert precision_at_k(["a", "b"], {"a", "b"}, k=2) == pytest.approx(1.0)

    def test_none_relevant(self) -> None:
        assert precision_at_k(["x", "y"], {"a"}, k=2) == pytest.approx(0.0)

    def test_partial(self) -> None:
        # 2 of 4 hits are gold → 0.5
        assert precision_at_k(["a", "x", "b", "y"], {"a", "b"}, k=4) == pytest.approx(0.5)

    def test_truncates_to_k(self) -> None:
        # Only look at top-2 → just "a" is gold → 0.5
        assert precision_at_k(["a", "x", "b"], {"a", "b"}, k=2) == pytest.approx(0.5)

    def test_short_hit_list_still_divides_by_k(self) -> None:
        # 1 relevant out of 1 retrieved, but k=5 → 1/5, not 1/1.
        # This is the standard IR convention documented in the scorer.
        assert precision_at_k(["a"], {"a"}, k=5) == pytest.approx(0.2)

    def test_empty_gold(self) -> None:
        assert precision_at_k(["a", "b"], set(), k=2) == 0.0

    def test_k_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            precision_at_k(["a"], {"a"}, k=0)
