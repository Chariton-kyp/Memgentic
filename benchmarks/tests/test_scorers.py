"""Unit tests for the pure retrieval-metric helpers.

These tests are intentionally assertion-dense: the scorers feed every
published benchmark number, so a silent formula regression would flow
straight into the marketing collateral.
"""

from __future__ import annotations

import pytest

from benchmarks.lib.scorers import (
    aggregate_chunks_to_sessions,
    mean_reciprocal_rank,
    precision_at_k,
    rank_of_gold_session_aggregated,
    recall_at_k,
    recall_at_k_session_aggregated,
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


# ---------------------------------------------------------------------------
# Plan 12 PR-B: session-level aggregation tests
# ---------------------------------------------------------------------------


class TestAggregateChunksToSessions:
    def test_no_duplicates_passthrough(self) -> None:
        # Already distinct sessions: same order, same scores
        chunks = [("s-a", 0.9), ("s-b", 0.7), ("s-c", 0.5)]
        assert aggregate_chunks_to_sessions(chunks) == [
            ("s-a", 0.9),
            ("s-b", 0.7),
            ("s-c", 0.5),
        ]

    def test_dedupes_keeping_max_score(self) -> None:
        # s-a appears at ranks 1, 3, 5 with scores 0.9, 0.6, 0.4 → keep 0.9
        chunks = [
            ("s-a", 0.9),
            ("s-b", 0.7),
            ("s-a", 0.6),
            ("s-c", 0.5),
            ("s-a", 0.4),
        ]
        result = aggregate_chunks_to_sessions(chunks)
        assert result == [("s-a", 0.9), ("s-b", 0.7), ("s-c", 0.5)]

    def test_dedupes_when_later_chunk_has_higher_score(self) -> None:
        # s-a at rank 1 score 0.5, then s-a at rank 3 score 0.9 → keep 0.9
        # but order: s-a moves to top because score wins
        chunks = [("s-a", 0.5), ("s-b", 0.7), ("s-a", 0.9)]
        result = aggregate_chunks_to_sessions(chunks)
        assert result == [("s-a", 0.9), ("s-b", 0.7)]

    def test_drops_none_session_ids(self) -> None:
        chunks = [("s-a", 0.9), (None, 0.8), ("s-b", 0.7)]
        result = aggregate_chunks_to_sessions(chunks)
        assert result == [("s-a", 0.9), ("s-b", 0.7)]

    def test_tiebreaker_on_first_seen_index(self) -> None:
        # Two sessions tied at 0.5 → s-a (first) ranks ahead of s-b
        chunks = [("s-a", 0.5), ("s-b", 0.5)]
        result = aggregate_chunks_to_sessions(chunks)
        assert result == [("s-a", 0.5), ("s-b", 0.5)]

    def test_empty_input(self) -> None:
        assert aggregate_chunks_to_sessions([]) == []


class TestRecallAtKSessionAggregated:
    def test_chunk_duplicates_no_longer_block_recall(self) -> None:
        # Pre-fix bug: top-5 chunks = [s-a, s-a, s-a, s-b, s-c], gold = s-d
        # → recall_at_k = False, but s-d might be at chunk rank 6.
        # Post-fix: scoring runs on distinct sessions, not chunks.
        chunks = [
            ("s-a", 0.9),
            ("s-a", 0.85),
            ("s-a", 0.8),
            ("s-b", 0.7),
            ("s-c", 0.6),
            ("s-d", 0.55),
        ]
        # Distinct sessions ranked: s-a, s-b, s-c, s-d → s-d at rank 4 → in top-5
        assert recall_at_k_session_aggregated(chunks, {"s-d"}, k=5) is True

    def test_gold_in_chunk_top_5_but_not_session_top_5(self) -> None:
        # 6 distinct sessions in chunks; gold is the 7th distinct session
        chunks = [(f"s-{i}", 1.0 - i * 0.1) for i in range(6)]
        chunks.append(("s-gold", 0.001))
        # Distinct sessions ranked top-5 = s-0 ... s-4; gold (s-gold) at rank 7
        assert recall_at_k_session_aggregated(chunks, {"s-gold"}, k=5) is False

    def test_gold_appears_via_a_late_chunk_with_high_score(self) -> None:
        # s-gold's best chunk is at rank 8 but with score 0.95 — should rank ahead
        chunks = [
            ("s-a", 0.5),
            ("s-b", 0.45),
            ("s-c", 0.4),
            ("s-d", 0.35),
            ("s-e", 0.3),
            ("s-f", 0.25),
            ("s-g", 0.2),
            ("s-gold", 0.95),
        ]
        assert recall_at_k_session_aggregated(chunks, {"s-gold"}, k=5) is True

    def test_empty_chunks(self) -> None:
        assert recall_at_k_session_aggregated([], {"s-a"}, k=5) is False

    def test_empty_gold(self) -> None:
        assert recall_at_k_session_aggregated([("s-a", 0.9)], set(), k=5) is False


class TestRankOfGoldSessionAggregated:
    def test_gold_first(self) -> None:
        chunks = [("s-gold", 0.9), ("s-a", 0.5)]
        assert rank_of_gold_session_aggregated(chunks, {"s-gold"}) == 1

    def test_gold_after_dedup(self) -> None:
        # s-a appears 3 times; s-gold once at rank 4 → after dedup, s-gold = rank 2
        chunks = [
            ("s-a", 0.9),
            ("s-a", 0.85),
            ("s-a", 0.8),
            ("s-gold", 0.7),
            ("s-b", 0.6),
        ]
        assert rank_of_gold_session_aggregated(chunks, {"s-gold"}) == 2

    def test_gold_missing(self) -> None:
        chunks = [("s-a", 0.9), ("s-b", 0.5)]
        assert rank_of_gold_session_aggregated(chunks, {"s-gold"}) is None

    def test_empty_gold(self) -> None:
        chunks = [("s-a", 0.9)]
        assert rank_of_gold_session_aggregated(chunks, set()) is None
