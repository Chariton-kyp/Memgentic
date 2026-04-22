"""Unit tests for the Recall Tiers scorer + MMR selector."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from memgentic.briefing.scorer import (
    DEFAULT_WEIGHTS,
    ScoredMemory,
    ScorerWeights,
    centroid_of,
    default_weights,
    load_weights,
    score_memories,
    select_with_mmr,
    weights_from_dict,
)
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)


def _mk(
    id: str,
    *,
    created_at: datetime | None = None,
    importance: float = 0.5,
    pinned: bool = False,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
    content: str = "content",
) -> Memory:
    return Memory(
        id=id,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.MCP_TOOL,
        ),
        topics=topics or [],
        entities=entities or [],
        created_at=created_at or datetime.now(UTC),
        importance_score=importance,
        is_pinned=pinned,
    )


class TestScorerWeights:
    def test_defaults_match_plan(self):
        w = default_weights()
        assert w.importance == pytest.approx(0.30)
        assert w.recency == pytest.approx(0.25)
        assert w.pinned == pytest.approx(0.25)
        assert w.cluster == pytest.approx(0.10)
        assert w.skill_link == pytest.approx(0.10)
        assert w.tau_days == pytest.approx(30.0)

    def test_rejects_negative_weights(self):
        with pytest.raises(ValueError):
            ScorerWeights(importance=-0.1)

    def test_rejects_nan_tau(self):
        with pytest.raises(ValueError):
            ScorerWeights(tau_days=float("nan"))

    def test_rejects_zero_tau(self):
        with pytest.raises(ValueError):
            ScorerWeights(tau_days=0.0)

    def test_as_dict_roundtrip(self):
        w = default_weights()
        d = w.as_dict()
        assert d["importance"] == DEFAULT_WEIGHTS["importance"]
        assert set(d.keys()) == {
            "importance",
            "recency",
            "pinned",
            "cluster",
            "skill_link",
            "tau_days",
        }

    def test_weights_from_dict_ignores_unknown_keys(self):
        w = weights_from_dict({"importance": 0.5, "garbage": 999})
        assert w.importance == pytest.approx(0.5)
        assert w.recency == pytest.approx(DEFAULT_WEIGHTS["recency"])

    def test_load_weights_overrides_precedence(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("briefing:\n  weights:\n    importance: 0.9\n", encoding="utf-8")
        w = load_weights({"recency": 0.05}, config_path=config)
        # Override wins, config wins over defaults for untouched keys
        assert w.importance == pytest.approx(0.9)
        assert w.recency == pytest.approx(0.05)


class TestRecencyDecay:
    def test_new_memory_scores_higher_than_old(self):
        now = datetime.now(UTC)
        fresh = _mk("fresh", created_at=now, importance=0.5)
        stale = _mk("stale", created_at=now - timedelta(days=90), importance=0.5)
        scored = score_memories([fresh, stale], now=now)
        by_id = {s.memory.id: s for s in scored}
        assert by_id["fresh"].score > by_id["stale"].score
        assert by_id["fresh"].breakdown["recency"] > by_id["stale"].breakdown["recency"]

    def test_recency_is_monotonic(self):
        now = datetime.now(UTC)
        a = _mk("a", created_at=now - timedelta(days=1))
        b = _mk("b", created_at=now - timedelta(days=10))
        c = _mk("c", created_at=now - timedelta(days=100))
        scored = score_memories([a, b, c], now=now)
        by_id = {s.memory.id: s for s in scored}
        assert by_id["a"].breakdown["recency"] > by_id["b"].breakdown["recency"]
        assert by_id["b"].breakdown["recency"] > by_id["c"].breakdown["recency"]

    def test_recency_clamps_future_dates(self):
        now = datetime.now(UTC)
        future = _mk("future", created_at=now + timedelta(days=5))
        scored = score_memories([future], now=now)
        # Future dates clamp to age=0 → recency should be exactly 1.
        assert scored[0].breakdown["recency"] == pytest.approx(1.0)


class TestPinBoost:
    def test_pinned_outranks_non_pinned_all_else_equal(self):
        now = datetime.now(UTC)
        pinned = _mk("p", pinned=True, importance=0.3, created_at=now)
        regular = _mk("r", pinned=False, importance=0.3, created_at=now)
        scored = score_memories([pinned, regular], now=now)
        by_id = {s.memory.id: s for s in scored}
        assert by_id["p"].score > by_id["r"].score


class TestSkillLink:
    def test_matching_topic_boosts_score(self):
        now = datetime.now(UTC)
        matches = _mk(
            "m", topics=["debugging"], importance=0.3, created_at=now
        )
        other = _mk("o", topics=["unrelated"], importance=0.3, created_at=now)
        scored = score_memories(
            [matches, other],
            now=now,
            active_skills=["debugging"],
        )
        by_id = {s.memory.id: s for s in scored}
        assert by_id["m"].score > by_id["o"].score
        assert by_id["m"].breakdown["skill_link"] == pytest.approx(1.0)
        assert by_id["o"].breakdown["skill_link"] == pytest.approx(0.0)

    def test_matching_entity_also_counts(self):
        now = datetime.now(UTC)
        entity_match = _mk(
            "e", entities=["FastAPI"], importance=0.3, created_at=now
        )
        scored = score_memories(
            [entity_match], now=now, active_skills=["fastapi"]
        )
        assert scored[0].breakdown["skill_link"] == pytest.approx(1.0)

    def test_no_active_skills_gives_zero(self):
        now = datetime.now(UTC)
        m = _mk("m", topics=["x"], created_at=now)
        scored = score_memories([m], now=now, active_skills=None)
        assert scored[0].breakdown["skill_link"] == pytest.approx(0.0)


class TestClusterScore:
    def test_cluster_degrades_to_zero_without_embeddings(self):
        now = datetime.now(UTC)
        m = _mk("m", created_at=now)
        scored = score_memories([m], now=now, embeddings={}, centroid=None)
        assert scored[0].breakdown["cluster"] == pytest.approx(0.0)

    def test_cluster_uses_cosine_similarity(self):
        now = datetime.now(UTC)
        m = _mk("m", created_at=now)
        # Vectors identical → cosine = 1
        scored = score_memories(
            [m],
            now=now,
            embeddings={"m": [1.0, 0.0, 0.0]},
            centroid=[1.0, 0.0, 0.0],
        )
        assert scored[0].breakdown["cluster"] == pytest.approx(1.0)

    def test_cluster_handles_mismatched_dimensions(self):
        now = datetime.now(UTC)
        m = _mk("m", created_at=now)
        scored = score_memories(
            [m],
            now=now,
            embeddings={"m": [1.0, 0.0]},
            centroid=[1.0, 0.0, 0.0],
        )
        assert scored[0].breakdown["cluster"] == pytest.approx(0.0)


class TestCentroidOf:
    def test_mean_of_orthogonal_vectors(self):
        c = centroid_of([[1.0, 0.0], [0.0, 1.0]])
        assert c == [0.5, 0.5]

    def test_empty_returns_none(self):
        assert centroid_of([]) is None

    def test_dim_mismatch_returns_none(self):
        assert centroid_of([[1.0], [1.0, 2.0]]) is None


class TestMMR:
    def test_empty_candidates_returns_empty(self):
        assert select_with_mmr([], k=5) == []

    def test_zero_k_returns_empty(self):
        sc = [
            ScoredMemory(memory=_mk("a"), score=1.0),
        ]
        assert select_with_mmr(sc, k=0) == []

    def test_respects_k(self):
        candidates = [
            ScoredMemory(memory=_mk(f"m{i}"), score=float(i)) for i in range(10)
        ]
        picked = select_with_mmr(candidates, k=3)
        assert len(picked) == 3
        # Top scores first after final re-sort
        assert [p.memory.id for p in picked] == ["m9", "m8", "m7"]

    def test_preserves_pinned_memories(self):
        # 3 pinned + 10 non-pinned, k=5 → all pinned + 2 non-pinned = 5
        pinned = [
            ScoredMemory(memory=_mk(f"p{i}", pinned=True), score=0.1)
            for i in range(3)
        ]
        non_pinned = [
            ScoredMemory(memory=_mk(f"n{i}"), score=float(i) + 0.5)
            for i in range(10)
        ]
        picked = select_with_mmr(pinned + non_pinned, k=5, preserve_pinned=True)
        assert len(picked) == 5
        pinned_ids = {p.memory.id for p in picked if p.memory.is_pinned}
        assert pinned_ids == {"p0", "p1", "p2"}

    def test_keeps_all_pinned_even_above_k(self):
        # 5 pinned, k=3 → all 5 pinned kept (pins are user intent, plan §12)
        pinned = [
            ScoredMemory(memory=_mk(f"p{i}", pinned=True), score=0.1)
            for i in range(5)
        ]
        picked = select_with_mmr(pinned, k=3, preserve_pinned=True)
        assert len(picked) == 5

    def test_diversifies_with_embeddings(self):
        # Two near-duplicate high scorers + one diverse lower scorer.
        # With λ=0.5, the diverse one should beat the second duplicate.
        a = ScoredMemory(memory=_mk("a"), score=1.0, embedding=[1.0, 0.0])
        b = ScoredMemory(memory=_mk("b"), score=0.99, embedding=[0.99, 0.01])
        c = ScoredMemory(memory=_mk("c"), score=0.8, embedding=[0.0, 1.0])
        picked = select_with_mmr([a, b, c], k=2, preserve_pinned=False)
        ids = {p.memory.id for p in picked}
        assert "a" in ids
        assert "c" in ids

    def test_missing_embeddings_falls_back_to_score_order(self):
        candidates = [
            ScoredMemory(memory=_mk(f"m{i}"), score=float(i)) for i in range(5)
        ]
        picked = select_with_mmr(candidates, k=3, preserve_pinned=False)
        assert [p.memory.id for p in picked] == ["m4", "m3", "m2"]


class TestScorerEdgeCases:
    def test_zero_importance_zero_recency_still_returns_finite(self):
        # Very old memory with zero importance shouldn't be NaN.
        very_old = _mk(
            "old",
            created_at=datetime.now(UTC) - timedelta(days=10_000),
            importance=0.0,
        )
        scored = score_memories([very_old])
        assert math.isfinite(scored[0].score)
        assert scored[0].score >= 0.0

    def test_empty_memory_list(self):
        assert score_memories([]) == []

    def test_breakdown_keys_stable(self):
        m = _mk("m")
        scored = score_memories([m])
        assert set(scored[0].breakdown.keys()) == {
            "importance",
            "recency",
            "pinned",
            "cluster",
            "skill_link",
        }
