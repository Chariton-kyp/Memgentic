"""Unit tests for individual tier classes using lightweight stubs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from memgentic.briefing.tiers import (
    AtlasTier,
    BriefingContext,
    DeepRecallTier,
    HorizonTier,
    OrbitTier,
    PersonaTier,
    RecallStack,
)
from memgentic.models import (
    CaptureMethod,
    Collection,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)


# --- Stubs --------------------------------------------------------------


class FakeMetadataStore:
    def __init__(
        self,
        *,
        recent: list[Memory] | None = None,
        pinned: list[Memory] | None = None,
        collections: list[Collection] | None = None,
        collection_members: dict[str, list[Memory]] | None = None,
        skills: list | None = None,
    ):
        self._recent = recent or []
        self._pinned = pinned or []
        self._collections = collections or []
        self._collection_members = collection_members or {}
        self._skills = skills or []

    async def get_memories_by_filter(
        self,
        session_config=None,
        content_type=None,
        limit: int = 50,
        offset: int = 0,
        user_id: str = "",
    ) -> list[Memory]:
        return list(self._recent[:limit])

    async def get_pinned_memories(
        self, user_id: str = "", limit: int = 50
    ) -> list[Memory]:
        return list(self._pinned[:limit])

    async def get_collections(self, user_id: str = ""):
        return list(self._collections)

    async def get_collection_memories(
        self, collection_id: str, limit: int = 50, offset: int = 0
    ) -> list[Memory]:
        return list(self._collection_members.get(collection_id, [])[:limit])

    async def get_skills(self, user_id: str = ""):
        return list(self._skills)


class FakeVectorStore:
    def __init__(self, embeddings: dict[str, list[float]] | None = None):
        self._embeddings = embeddings or {}

    async def get_embeddings(self, ids: list[str]) -> dict[str, list[float]]:
        return {i: self._embeddings[i] for i in ids if i in self._embeddings}


class FakeGraph:
    def __init__(self, node_count: int = 0, neighbors: dict | None = None):
        self.node_count = node_count
        self._neighbors = neighbors or {}

    async def query_neighbors(self, entity: str, depth: int = 2):
        data = self._neighbors.get(entity)
        if data is None:
            return {"entity": entity, "neighbors": [], "not_found": True}
        return {"entity": entity, "neighbors": data}


def _mk(
    id: str,
    *,
    content: str = "content",
    pinned: bool = False,
    importance: float = 0.5,
    created_at: datetime | None = None,
    topics: list[str] | None = None,
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
        is_pinned=pinned,
        importance_score=importance,
        created_at=created_at or datetime.now(UTC),
    )


# --- Tests: PersonaTier -------------------------------------------------


class TestPersonaTier:
    async def test_renders_default_when_file_missing(
        self, tmp_path, monkeypatch
    ):
        # Point the persona loader at a non-existent file.
        monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(tmp_path / "no.yaml"))
        tier = PersonaTier()
        ctx = BriefingContext()
        out = await tier.render(ctx)
        assert out.tier == "T0"
        assert "Persona" in out.text
        # Missing-file hint appears
        assert "persona init" in out.text
        assert out.meta["missing"] is True

    async def test_uses_existing_persona_file(self, tmp_path, monkeypatch):
        persona_path = tmp_path / "persona.yaml"
        persona_path.write_text(
            "version: 1\nidentity:\n  name: Atlas\n  role: Helper\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(persona_path))
        tier = PersonaTier()
        out = await tier.render(BriefingContext())
        assert "Atlas" in out.text
        assert out.meta["missing"] is False


# --- Tests: HorizonTier -------------------------------------------------


class TestHorizonTier:
    async def test_empty_store_shows_placeholder(self, monkeypatch):
        tier = HorizonTier()
        ctx = BriefingContext(metadata_store=FakeMetadataStore())
        out = await tier.render(ctx)
        assert "No memories yet" in out.text
        assert out.memories_count == 0

    async def test_returns_top_memories(self):
        recent = [
            _mk(f"m{i}", importance=i / 10.0, created_at=datetime.now(UTC))
            for i in range(5)
        ]
        tier = HorizonTier()
        ctx = BriefingContext(metadata_store=FakeMetadataStore(recent=recent))
        out = await tier.render(ctx)
        assert out.memories_count > 0
        assert out.tokens > 0

    async def test_pinned_memories_always_included(self):
        now = datetime.now(UTC)
        pinned = [_mk("p1", pinned=True, created_at=now - timedelta(days=365))]
        recent = [_mk(f"r{i}", importance=0.9, created_at=now) for i in range(5)]
        tier = HorizonTier()
        ctx = BriefingContext(
            metadata_store=FakeMetadataStore(recent=recent, pinned=pinned)
        )
        out = await tier.render(ctx)
        # Even an ancient pinned memory survives.
        assert "p1" in out.text or "pinned" in out.text

    async def test_respects_budget(self):
        # 30 memories but budget caps at e.g. 15 for 128k context.
        recent = [
            _mk(f"m{i}", importance=0.5, created_at=datetime.now(UTC))
            for i in range(30)
        ]
        tier = HorizonTier()
        ctx = BriefingContext(
            metadata_store=FakeMetadataStore(recent=recent),
            model_context=128_000,
        )
        out = await tier.render(ctx)
        assert out.memories_count <= 15

    async def test_handles_store_exception_gracefully(self):
        class BadStore:
            async def get_pinned_memories(self, *a, **kw):
                raise RuntimeError("boom")

            async def get_memories_by_filter(self, *a, **kw):
                raise RuntimeError("also boom")

        tier = HorizonTier()
        out = await tier.render(BriefingContext(metadata_store=BadStore()))
        # Should not raise; should render the empty-state message.
        assert "T1" in out.text


# --- Tests: OrbitTier ---------------------------------------------------


class TestOrbitTier:
    async def test_filters_by_collection_name(self):
        c = Collection(id="c1", name="auth")
        mem_in = [_mk("in-auth", topics=["auth"])]
        store = FakeMetadataStore(
            collections=[c],
            collection_members={"c1": mem_in},
        )
        tier = OrbitTier()
        ctx = BriefingContext(metadata_store=store, collection="auth")
        out = await tier.render(ctx)
        assert "in-auth" in out.text or "content" in out.text

    async def test_filters_by_topic_only(self):
        now = datetime.now(UTC)
        pool = [
            _mk("a", topics=["python"], created_at=now),
            _mk("b", topics=["rust"], created_at=now),
            _mk("c", topics=["python"], created_at=now),
        ]
        store = FakeMetadataStore(recent=pool)
        tier = OrbitTier()
        out = await tier.render(
            BriefingContext(metadata_store=store, topic="python")
        )
        assert "[topic:python]" in out.text
        assert out.memories_count == 2

    async def test_unknown_collection_empty(self):
        store = FakeMetadataStore()
        tier = OrbitTier()
        out = await tier.render(
            BriefingContext(metadata_store=store, collection="missing")
        )
        assert "No memories match" in out.text


# --- Tests: DeepRecallTier ----------------------------------------------


class TestDeepRecallTier:
    async def test_empty_query_returns_hint(self):
        tier = DeepRecallTier()
        out = await tier.render(BriefingContext(query=""))
        assert "Provide a query" in out.text

    async def test_uses_injected_search_fn(self):
        async def fake_search(*, query: str, **kw):
            return [
                {
                    "id": "x",
                    "score": 0.9,
                    "payload": {
                        "content": f"found for {query}",
                        "platform": "claude_code",
                        "created_at": "2026-03-01T00:00:00+00:00",
                    },
                }
            ]

        tier = DeepRecallTier()
        ctx = BriefingContext(
            query="graphql",
            hybrid_search_fn=fake_search,
            metadata_store=object(),
            vector_store=object(),
            embedder=object(),
        )
        out = await tier.render(ctx)
        assert "found for graphql" in out.text
        assert out.memories_count == 1


# --- Tests: AtlasTier ---------------------------------------------------


class TestAtlasTier:
    async def test_empty_graph_stub(self):
        tier = AtlasTier()
        out = await tier.render(BriefingContext(graph=FakeGraph(node_count=0)))
        assert "Knowledge graph not yet populated" in out.text
        assert out.meta["graph_empty"] is True

    async def test_no_entity_when_populated(self):
        tier = AtlasTier()
        ctx = BriefingContext(graph=FakeGraph(node_count=5))
        out = await tier.render(ctx)
        assert "Provide an entity" in out.text

    async def test_renders_neighbours(self):
        graph = FakeGraph(
            node_count=5,
            neighbors={
                "Kai": [
                    {"name": "OAuth", "type": "topic", "count": 3, "depth": 1},
                ]
            },
        )
        tier = AtlasTier()
        out = await tier.render(
            BriefingContext(graph=graph, entity="Kai")
        )
        assert "OAuth" in out.text
        assert out.memories_count == 1

    async def test_unknown_entity_empty_neighbours(self):
        graph = FakeGraph(node_count=5, neighbors={})
        tier = AtlasTier()
        out = await tier.render(
            BriefingContext(graph=graph, entity="Ghost")
        )
        assert "Entity not found" in out.text


# --- Tests: RecallStack -------------------------------------------------


class TestRecallStack:
    async def test_briefing_combines_t0_and_t1(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(tmp_path / "p.yaml"))
        store = FakeMetadataStore(recent=[_mk("m1")])
        stack = RecallStack()
        text = await stack.briefing(BriefingContext(metadata_store=store))
        assert "## T0 — Persona" in text
        assert "## T1 — Horizon" in text

    async def test_tier_recall_returns_output(self):
        stack = RecallStack()
        out = await stack.tier_recall(
            "T4", BriefingContext(graph=FakeGraph(node_count=0))
        )
        assert out.tier == "T4"
        assert "Knowledge graph" in out.text

    async def test_unknown_tier_raises(self):
        stack = RecallStack()
        with pytest.raises(ValueError):
            await stack.tier_recall("T9", BriefingContext())

    async def test_status_schema(self):
        stack = RecallStack()
        status = stack.status()
        assert "tiers" in status
        assert set(status["tiers"].keys()) == {"T0", "T1", "T2", "T3", "T4"}
        assert "budgets" in status

    async def test_status_tracks_last_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMGENTIC_PERSONA_PATH", str(tmp_path / "p.yaml"))
        stack = RecallStack()
        await stack.briefing(
            BriefingContext(metadata_store=FakeMetadataStore())
        )
        status = stack.status()
        assert status["last_run"]["mode"] == "briefing"
        assert status["last_run"]["tokens"] >= 0
