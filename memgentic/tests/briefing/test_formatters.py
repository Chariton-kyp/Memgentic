"""Snapshot / stable-output tests for the tier formatters."""

from __future__ import annotations

from datetime import UTC, datetime

from memgentic.briefing.formatters import (
    assemble,
    count_tokens,
    format_atlas_tier,
    format_deep_recall_tier,
    format_horizon_tier,
    format_orbit_tier,
    format_persona_tier,
)
from memgentic.briefing.scorer import ScoredMemory
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)


def _mk(
    id: str = "m",
    content: str = "decided Clerk over Auth0 (pricing)",
    pinned: bool = False,
    created_at: datetime | None = None,
) -> Memory:
    return Memory(
        id=id,
        content=content,
        content_type=ContentType.DECISION,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.MCP_TOOL,
        ),
        created_at=created_at or datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
        is_pinned=pinned,
    )


class TestPersonaFormatter:
    def test_header_and_body(self):
        out = format_persona_tier(rendered="# Persona — Atlas\nRole: Helper")
        assert "## T0 — Persona" in out
        assert "Atlas" in out
        assert "_Hint" not in out  # no hint when loader happy

    def test_fallback_hint_rendered(self):
        out = format_persona_tier(
            rendered="# Persona — Assistant",
            fallback_hint="run `memgentic persona init` to customise",
        )
        assert "_Hint:" in out
        assert "persona init" in out


class TestHorizonFormatter:
    def test_empty_shows_onboarding_hint(self):
        out = format_horizon_tier(scored=[])
        assert "## T1 — Horizon" in out
        assert "No memories yet" in out
        assert "import-existing" in out

    def test_renders_memory_bullets(self):
        m = _mk()
        out = format_horizon_tier(scored=[ScoredMemory(memory=m, score=0.77)])
        assert "## T1 — Horizon" in out
        assert "decided Clerk" in out
        assert "2026-02-01" in out
        assert "[score 0.77]" in out

    def test_collection_header(self):
        m = _mk()
        out = format_horizon_tier(
            scored=[ScoredMemory(memory=m, score=0.5)],
            collection_name="auth",
        )
        assert "[collection:auth]" in out

    def test_pinned_marker(self):
        m = _mk(pinned=True)
        out = format_horizon_tier(scored=[ScoredMemory(memory=m, score=0.5)])
        assert "pinned" in out

    def test_skills_block_renders(self):
        m = _mk()
        out = format_horizon_tier(
            scored=[ScoredMemory(memory=m, score=0.5)],
            active_skills=[
                {"name": "debugging/pr-review", "usage": 34},
                {"name": "writing"},
            ],
        )
        assert "[skills:top]" in out
        assert "debugging/pr-review (used 34x)" in out
        # No usage counter → no (used Nx) suffix
        assert "writing" in out
        assert "writing (used" not in out

    def test_empty_skills_block_omitted(self):
        m = _mk()
        out = format_horizon_tier(scored=[ScoredMemory(memory=m, score=0.5)])
        assert "[skills:top]" not in out


class TestOrbitFormatter:
    def test_empty_message(self):
        out = format_orbit_tier(memories=[], collection_name="auth")
        assert "## T2 — Orbit" in out
        assert "No memories match" in out

    def test_with_collection_and_topic(self):
        out = format_orbit_tier(
            memories=[_mk()],
            collection_name="app",
            topic="auth",
        )
        assert "[collection:app,topic:auth]" in out
        assert "decided Clerk" in out


class TestDeepRecallFormatter:
    def test_empty_query_message(self):
        out = format_deep_recall_tier(results=[], query="graphql")
        assert "## T3 — Deep Recall" in out
        assert "No matches for: graphql" in out

    def test_renders_hybrid_search_shape(self):
        results = [
            {
                "id": "m1",
                "score": 0.85,
                "payload": {
                    "content": "GraphQL decision",
                    "platform": "claude_code",
                    "created_at": "2026-02-02T10:00:00+00:00",
                },
            }
        ]
        out = format_deep_recall_tier(results=results, query="graphql")
        assert "GraphQL decision" in out
        assert "claude_code" in out
        assert "2026-02-02" in out


class TestAtlasFormatter:
    def test_empty_graph_placeholder(self):
        out = format_atlas_tier(entity=None, neighbors=None, graph_empty=True)
        assert "## T4 — Atlas" in out
        assert "Knowledge graph not yet populated" in out
        assert "memgentic graph backfill" in out

    def test_missing_entity_hint(self):
        out = format_atlas_tier(entity=None, neighbors=None, graph_empty=False)
        assert "Provide an entity" in out

    def test_entity_not_found(self):
        out = format_atlas_tier(entity="Kai", neighbors=[], graph_empty=False)
        assert "Entity not found" in out

    def test_renders_neighbours(self):
        neighbours = [
            {"name": "OAuth", "type": "topic", "count": 5, "depth": 1},
            {"name": "Clerk", "type": "entity", "count": 3, "depth": 2},
        ]
        out = format_atlas_tier(
            entity="Kai", neighbors=neighbours, graph_empty=False
        )
        assert "OAuth (topic, hops=1, seen 5x)" in out
        assert "Clerk (entity, hops=2, seen 3x)" in out


class TestAssemble:
    def test_joins_with_blank_lines(self):
        out = assemble(["A", "B", "C"])
        assert out == "A\n\nB\n\nC"

    def test_skips_empty_blocks(self):
        out = assemble(["A", "", "   ", "B"])
        assert out == "A\n\nB"

    def test_count_tokens_available(self):
        assert count_tokens("hello world") > 0


class TestStableOutput:
    """Snapshot-style tests — the exact shape agents see."""

    def test_default_briefing_snapshot(self):
        """Lock the default T0+T1 shape so future tweaks surface in review."""
        persona_text = format_persona_tier(rendered="# Persona — Atlas\nRole: Helper")
        horizon_text = format_horizon_tier(scored=[])

        full = assemble([persona_text, horizon_text])
        # Golden fragments we expect to stay stable.
        assert full.startswith("## T0 — Persona")
        assert "## T1 — Horizon" in full
        assert full.count("\n\n## ") == 1  # tier separator
