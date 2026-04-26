"""Tests for memgentic.retrieval.feature_boost.apply_feature_boosts."""

from __future__ import annotations

import datetime as _dt

import pytest

from memgentic.processing.query_features import QueryFeatures
from memgentic.retrieval.feature_boost import (
    DEFAULT_PROPER_NOUN_BOOST,
    DEFAULT_PROPER_NOUN_CAP,
    DEFAULT_QUOTED_BOOST,
    apply_feature_boosts,
)


_NOW = _dt.datetime(2026, 4, 26, 12, 0, 0, tzinfo=_dt.UTC)


def _cand(id_: str, score: float, content: str = "", created_at: str | None = None):
    payload = {"content": content}
    if created_at:
        payload["created_at"] = created_at
    return {"id": id_, "score": score, "payload": payload}


class TestQuotedBoost:
    def test_exact_substring_match_promotes(self):
        cands = [
            _cand("a", 0.5, "irrelevant content"),
            _cand("b", 0.4, "this contains the circuit breaker pattern explanation"),
        ]
        features = QueryFeatures(quoted_phrases=("circuit breaker pattern",))
        out = apply_feature_boosts(cands, features, now=_NOW)
        assert out[0]["id"] == "b"
        assert out[0]["score"] == pytest.approx(0.4 * DEFAULT_QUOTED_BOOST)
        assert out[0]["raw_score"] == 0.4
        assert out[0]["boost_multiplier"] == round(DEFAULT_QUOTED_BOOST, 4)

    def test_case_insensitive(self):
        cands = [
            _cand("a", 0.3, "CIRCUIT Breaker pattern explained"),
        ]
        features = QueryFeatures(quoted_phrases=("circuit breaker pattern",))
        out = apply_feature_boosts(cands, features, now=_NOW)
        assert out[0]["score"] == pytest.approx(0.3 * DEFAULT_QUOTED_BOOST)


class TestProperNounBoost:
    def test_single_name_match(self):
        cands = [
            _cand("a", 0.3, "report from analyst"),
            _cand("b", 0.3, "Maria sent the report"),
        ]
        features = QueryFeatures(proper_nouns=("Maria",))
        out = apply_feature_boosts(cands, features, now=_NOW)
        assert out[0]["id"] == "b"
        assert out[0]["score"] == pytest.approx(0.3 * DEFAULT_PROPER_NOUN_BOOST)

    def test_multiple_names_compound_to_cap(self):
        # 1.4 ^ 3 = 2.744, capped at DEFAULT_PROPER_NOUN_CAP (2.0).
        cands = [_cand("a", 0.5, "Alice and Bob and Carol meeting")]
        features = QueryFeatures(proper_nouns=("Alice", "Bob", "Carol"))
        out = apply_feature_boosts(cands, features, now=_NOW)
        assert out[0]["score"] == pytest.approx(0.5 * DEFAULT_PROPER_NOUN_CAP)

    def test_no_match_no_boost(self):
        cands = [_cand("a", 0.3, "report from analyst")]
        features = QueryFeatures(proper_nouns=("Maria",))
        out = apply_feature_boosts(cands, features, now=_NOW)
        assert out[0]["score"] == 0.3
        assert out[0]["boost_multiplier"] == 1.0


class TestTemporalBoost:
    def test_candidate_at_target_date_gets_peak(self):
        # Target = 30 days back. Candidate created exactly 30 days back.
        target_date = _NOW - _dt.timedelta(days=30)
        cands = [_cand("a", 0.3, "anything", created_at=target_date.isoformat())]
        features = QueryFeatures(temporal_reference_days=30.0)
        out = apply_feature_boosts(cands, features, now=_NOW)
        # Distance = 0 → bell = 1.0 → multiplier = 1.0 + (1.5 - 1.0) * 1.0 = 1.5
        assert out[0]["score"] == pytest.approx(0.3 * 1.5)

    def test_far_candidate_gets_no_boost(self):
        # Target = 30 days back. Candidate created today (30 days off target).
        cands = [_cand("a", 0.3, "anything", created_at=_NOW.isoformat())]
        features = QueryFeatures(temporal_reference_days=30.0)
        out = apply_feature_boosts(cands, features, now=_NOW)
        # Distance = 30 days = 1 sigma → bell = e^-1 ≈ 0.368
        # multiplier ≈ 1.0 + 0.5 * 0.368 ≈ 1.184
        assert 0.30 < out[0]["score"] < 0.40

    def test_candidate_without_timestamp_neutral(self):
        cands = [_cand("a", 0.3, "anything")]  # no created_at
        features = QueryFeatures(temporal_reference_days=30.0)
        out = apply_feature_boosts(cands, features, now=_NOW)
        assert out[0]["score"] == 0.3  # unchanged


class TestCombined:
    def test_quoted_plus_proper_noun_compound(self):
        cands = [
            _cand("a", 0.3, "Maria mentioned the circuit breaker pattern"),
        ]
        features = QueryFeatures(
            quoted_phrases=("circuit breaker pattern",),
            proper_nouns=("Maria",),
        )
        out = apply_feature_boosts(cands, features, now=_NOW)
        expected = 0.3 * DEFAULT_QUOTED_BOOST * DEFAULT_PROPER_NOUN_BOOST
        assert out[0]["score"] == pytest.approx(expected)


class TestEmptyFeaturesAndCandidates:
    def test_no_features_preserves_order(self):
        cands = [_cand("a", 0.5), _cand("b", 0.3)]
        out = apply_feature_boosts(cands, QueryFeatures(), now=_NOW)
        assert [c["id"] for c in out] == ["a", "b"]
        # Even with no boost, raw_score / boost_multiplier are populated.
        assert out[0]["raw_score"] == 0.5
        assert out[0]["boost_multiplier"] == 1.0

    def test_empty_candidates_returns_empty(self):
        assert apply_feature_boosts([], QueryFeatures(quoted_phrases=("foo",))) == []
