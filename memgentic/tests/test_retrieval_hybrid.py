"""Tests for memgentic.retrieval.hybrid (Plan 12 PR-D)."""

from __future__ import annotations

import pytest

from memgentic.retrieval.hybrid import (
    DEFAULT_RRF_K,
    reciprocal_rank_fusion,
    weighted_score_fusion,
)


class TestReciprocalRankFusion:
    def test_single_list_passthrough(self) -> None:
        result = reciprocal_rank_fusion([["a", "b", "c"]])
        assert [item for item, _ in result] == ["a", "b", "c"]

    def test_two_lists_agree_on_top(self) -> None:
        # Both rank "a" first → "a" wins
        result = reciprocal_rank_fusion([["a", "b", "c"], ["a", "x", "y"]])
        assert result[0][0] == "a"

    def test_two_lists_disagree_one_wins_at_higher_rank(self) -> None:
        # "a" at rank 1 in one list, missing from the other.
        # "b" at rank 2 in both. Sum → "b" 1/(60+2) + 1/(60+2) = 2/62
        # "a" → 1/(60+1) = 1/61
        # 2/62 ≈ 0.0323 > 1/61 ≈ 0.0164 → "b" wins
        result = reciprocal_rank_fusion([["a", "b", "c"], ["x", "b", "y"]])
        assert result[0][0] == "b"

    def test_score_formula(self) -> None:
        # Single list, single item at rank 1 → score = 1/(60+1) = 1/61
        result = reciprocal_rank_fusion([["a"]])
        assert result == [("a", pytest.approx(1.0 / 61))]

    def test_default_k_is_60(self) -> None:
        assert DEFAULT_RRF_K == 60

    def test_k_overrides_default(self) -> None:
        # k=10 → 1/(10+1) = 1/11
        result = reciprocal_rank_fusion([["a"]], k=10)
        assert result == [("a", pytest.approx(1.0 / 11))]

    def test_k_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([["a"]], k=0)
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([["a"]], k=-1)

    def test_weights_must_match_list_count(self) -> None:
        with pytest.raises(ValueError):
            reciprocal_rank_fusion([["a"], ["b"]], weights=[1.0])

    def test_zero_weight_skips_list(self) -> None:
        # Setting list 1's weight to 0 → only list 0 contributes.
        # "a" at rank 1 in list 0 → 1/61. "x" doesn't appear (skipped).
        result = reciprocal_rank_fusion(
            [["a", "b"], ["x", "y"]],
            weights=[1.0, 0.0],
        )
        assert [item for item, _ in result] == ["a", "b"]

    def test_weighted_bias_toward_dense(self) -> None:
        # Dense (list 0) at weight 2.0, BM25 (list 1) at 1.0
        # Both rank "a" first (2.0 + 1.0 = 3.0 / 61), but BM25 also has "x" at 1.
        # "a" rrf = 2.0/61 + 1.0/61
        # "x" rrf = 0 + 1.0/61
        # → "a" wins
        result = reciprocal_rank_fusion(
            [["a"], ["a", "x"]],
            weights=[2.0, 1.0],
        )
        assert result[0][0] == "a"
        assert result[1][0] == "x"

    def test_empty_lists(self) -> None:
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[]]) == []

    def test_first_seen_tiebreaker(self) -> None:
        # Two items appear only in list 0, both at the only rank — but
        # the API never produces this; rank is positional. So construct
        # a tie by giving them identical contributions across two lists.
        # "a" in list 0 rank 1 + list 1 rank 2: 1/61 + 1/62
        # "b" in list 0 rank 2 + list 1 rank 1: 1/62 + 1/61 (same!)
        # → tied scores. First-seen winner = "a" (list 0, rank 1)
        result = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
        assert result[0][0] == "a"


class TestWeightedScoreFusion:
    def test_single_list_passthrough_normalised(self) -> None:
        # Single list with raw scores [0.9, 0.5, 0.1]; normalized to [1, 0.5, 0]
        # Weighted by 1.0 → fused == normalized
        result = weighted_score_fusion([[("a", 0.9), ("b", 0.5), ("c", 0.1)]])
        assert result[0] == ("a", pytest.approx(1.0))
        assert result[1] == ("b", pytest.approx(0.5))
        assert result[2] == ("c", pytest.approx(0.0))

    def test_two_lists_combined(self) -> None:
        # List 0: a=1.0, b=0.5 (normalized: a=1, b=0)
        # List 1: a=0.4, b=0.8 (normalized: a=0, b=1)
        # Sum: a=1, b=1 → tied. First-seen wins → a
        result = weighted_score_fusion(
            [[("a", 1.0), ("b", 0.5)], [("b", 0.8), ("a", 0.4)]]
        )
        # Both sum to 1.0 → tied
        assert {item for item, _ in result[:2]} == {"a", "b"}

    def test_empty_input(self) -> None:
        assert weighted_score_fusion([]) == []
        assert weighted_score_fusion([[]]) == []

    def test_weights_must_match(self) -> None:
        with pytest.raises(ValueError):
            weighted_score_fusion([[("a", 1.0)]], weights=[1.0, 2.0])

    def test_normalize_off_uses_raw_scores(self) -> None:
        # Without normalization, larger raw scores dominate
        result = weighted_score_fusion(
            [[("a", 100.0), ("b", 1.0)]],
            normalize=False,
        )
        assert result[0] == ("a", pytest.approx(100.0))
        assert result[1] == ("b", pytest.approx(1.0))
