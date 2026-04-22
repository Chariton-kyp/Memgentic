"""Tier classes for the Recall Tiers stack.

Each tier is a small async class with a ``render(ctx)`` method that
returns a :class:`TierOutput`. The :class:`RecallStack` orchestrator
composes them; everything else (CLI, MCP tool, REST route) depends
only on :class:`RecallStack` so future tier additions don't ripple
out.

Design notes:

- We never call the embedder per-memory — T1 fetches embeddings in a
  single batch from the vector store and passes them into the scorer.
  If the fetch fails or returns an empty map, the scorer degrades
  gracefully (plan §12 cold-start behaviour).
- T4 reads the knowledge graph but stubs to a helpful placeholder
  when the graph has no nodes yet. Chronograph populates the graph;
  that feature is parallel work and this tier must not block on it.
- The ``BriefingContext`` is a plain dataclass instead of a Pydantic
  model because it carries live store handles, not user input. All
  user input goes through CLI / MCP / REST schemas upstream.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

from memgentic.briefing.formatters import (
    assemble,
    count_tokens,
    format_atlas_tier,
    format_deep_recall_tier,
    format_horizon_tier,
    format_orbit_tier,
    format_persona_tier,
)
from memgentic.briefing.scorer import (
    ScorerWeights,
    centroid_of,
    default_weights,
    score_memories,
    select_with_mmr,
)
from memgentic.briefing.token_budget import (
    MAX_HORIZON_MEMORIES,
    BudgetResolution,
    TierName,
    resolve_budget,
)
from memgentic.models import Memory, SessionConfig

logger = structlog.get_logger()

# A minimal supply of candidate memories we pull from the metadata store
# for T1. 10x the max horizon cap gives the scorer room to diversify
# without scanning the whole table.
_HORIZON_CANDIDATE_FACTOR = 10
_MIN_HORIZON_CANDIDATES = 80
_MAX_HORIZON_CANDIDATES = 300


class _MetadataStoreLike(Protocol):
    """Structural subset of :class:`memgentic.storage.metadata.MetadataStore`.

    We depend only on the methods the tiers actually call — tests can
    pass a tiny stub without standing up a real SQLite store.
    """

    async def get_memories_by_filter(
        self,
        session_config: SessionConfig | None = ...,
        content_type: Any = ...,
        limit: int = ...,
        offset: int = ...,
        user_id: str = ...,
    ) -> list[Memory]: ...

    async def get_pinned_memories(self, user_id: str = ..., limit: int = ...) -> list[Memory]: ...


@dataclass
class BriefingContext:
    """Everything a tier might need to render its block.

    Most fields are optional — T0 only needs ``persona_path``, T1
    needs stores + embedder, T3 needs a query, T4 needs a graph and
    an entity. The ``user_id`` plumbs through for future multi-user
    (Phase C); today it's typically the empty string.
    """

    metadata_store: Any | None = None
    vector_store: Any | None = None
    embedder: Any | None = None
    graph: Any | None = None
    session_config: SessionConfig | None = None

    # Per-call scoping
    collection: str | None = None
    collection_id: str | None = None
    topic: str | None = None
    query: str | None = None
    entity: str | None = None
    user_id: str = ""

    # Budget / scoring knobs
    model_context: int | None = None
    max_tokens: int | None = None
    weights: ScorerWeights | None = None
    active_skills: list[str] = field(default_factory=list)
    persona_path: Path | None = None

    # Graph-based search override for T3 (intelligence package)
    hybrid_search_fn: Any | None = None
    basic_search_fn: Any | None = None


@dataclass
class TierOutput:
    """The rendered block + accounting metadata for a single tier."""

    tier: TierName
    text: str
    tokens: int
    budget: BudgetResolution
    memories_count: int = 0
    duration_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class BaseTier(ABC):
    """Common scaffolding: name, budget resolution, timing."""

    name: TierName
    label: str

    @abstractmethod
    async def render(self, ctx: BriefingContext) -> TierOutput:
        """Render this tier's text block."""

    def _budget(self, ctx: BriefingContext) -> BudgetResolution:
        return resolve_budget(
            self.name,
            ctx.model_context,
            max_tokens=ctx.max_tokens,
        )

    async def _timed_render(self, ctx: BriefingContext) -> TierOutput:
        """Decorator-free timing helper for subclass ``render`` methods."""
        start = time.perf_counter()
        try:
            out = await self.render(ctx)
        finally:
            elapsed = (time.perf_counter() - start) * 1000
        out.duration_ms = round(elapsed, 2)
        return out


# --- T0 Persona ----------------------------------------------------------


class PersonaTier(BaseTier):
    """T0 — read the persona card and render it as compact text."""

    name: TierName = "T0"
    label: str = "Persona"

    async def render(self, ctx: BriefingContext) -> TierOutput:
        # Imported lazily so importing the briefing package doesn't pull in
        # the full persona package on every MCP server boot.
        from memgentic.persona import default_persona, load_or_default, render_t0
        from memgentic.persona.loader import PersonaMalformedError, get_persona_path

        budget = self._budget(ctx)
        persona_path = ctx.persona_path or get_persona_path()
        hint: str | None = None

        # Detect the missing-file case so we can surface the
        # ``memgentic persona init`` hint. ``load_or_default`` swallows
        # that signal, so we inspect the path directly. A malformed file
        # is a louder error but we still fall through to defaults.
        if not persona_path.exists():
            hint = "run `memgentic persona init` to customise your persona"
            persona = default_persona()
        else:
            try:
                persona = load_or_default(persona_path)
            except PersonaMalformedError as exc:
                logger.warning("briefing.persona.malformed", error=str(exc))
                hint = "persona file is malformed — run `memgentic persona validate`"
                persona = default_persona()

        rendered = render_t0(persona)
        text = format_persona_tier(rendered=rendered, fallback_hint=hint)

        return TierOutput(
            tier="T0",
            text=text,
            tokens=count_tokens(text),
            budget=budget,
            memories_count=0,
            meta={"persona_path": str(persona_path), "missing": hint is not None},
        )


# --- T1 Horizon ----------------------------------------------------------


class HorizonTier(BaseTier):
    """T1 — top memories by hybrid score with MMR de-duplication."""

    name: TierName = "T1"
    label: str = "Horizon"

    async def render(self, ctx: BriefingContext) -> TierOutput:
        budget = self._budget(ctx)
        metadata_store = ctx.metadata_store
        if metadata_store is None:
            return TierOutput(
                tier="T1",
                text=format_horizon_tier(scored=[], empty_message="Store unavailable."),
                tokens=0,
                budget=budget,
                memories_count=0,
            )

        # Pool size: enough to let the scorer pick diverse top-K without
        # scanning the whole table. We bound by the max-candidate cap to
        # keep the 10k-memory perf target.
        pool_size = max(
            _MIN_HORIZON_CANDIDATES,
            min(_MAX_HORIZON_CANDIDATES, budget.max_memories * _HORIZON_CANDIDATE_FACTOR),
        )

        candidates: list[Memory] = []

        # Pinned memories always make the cut, so grab them first.
        try:
            pinned = await metadata_store.get_pinned_memories(
                user_id=ctx.user_id, limit=min(50, budget.max_memories)
            )
        except Exception as exc:
            logger.warning("briefing.horizon.pinned_fetch_failed", error=str(exc))
            pinned = []
        seen_ids = {m.id for m in pinned}
        candidates.extend(pinned)

        # Recency-ordered pool from the metadata store. ``get_memories_by_filter``
        # orders by ``created_at DESC`` which matches our recency term well.
        try:
            recent = await metadata_store.get_memories_by_filter(
                session_config=ctx.session_config,
                limit=pool_size,
                user_id=ctx.user_id,
            )
        except Exception as exc:
            logger.warning("briefing.horizon.recent_fetch_failed", error=str(exc))
            recent = []

        for mem in recent:
            if mem.id not in seen_ids:
                candidates.append(mem)
                seen_ids.add(mem.id)

        if not candidates:
            text = format_horizon_tier(scored=[], collection_name=ctx.collection)
            return TierOutput(
                tier="T1",
                text=text,
                tokens=count_tokens(text),
                budget=budget,
                memories_count=0,
            )

        # Fetch embeddings in a single batch. ``get_embedding`` is the
        # vector-store contract we rely on; when it's unavailable, the
        # scorer's cluster term simply evaluates to 0. This keeps the
        # cold-start path fast (plan §12).
        embeddings: dict[str, list[float]] = {}
        if ctx.vector_store is not None:
            embeddings = await _bulk_get_embeddings(ctx.vector_store, [c.id for c in candidates])

        centroid = centroid_of([v for v in embeddings.values() if v])

        weights = ctx.weights or default_weights()
        now = datetime.now(UTC)
        scored = score_memories(
            candidates,
            weights=weights,
            now=now,
            active_skills=ctx.active_skills,
            embeddings=embeddings,
            centroid=centroid,
        )

        k = min(MAX_HORIZON_MEMORIES, budget.max_memories)
        selected = select_with_mmr(scored, k=k, preserve_pinned=True)

        # Active skills block — top-3 by creation order when no usage
        # counter exists yet. Populated only when the metadata store
        # exposes the skills endpoint (skips quietly otherwise).
        skills_block: list[dict[str, Any]] = []
        try:
            get_skills = getattr(metadata_store, "get_skills", None)
            if callable(get_skills):
                skills = await get_skills(user_id=ctx.user_id)
                for skill in skills[:3]:
                    skills_block.append(
                        {
                            "name": skill.name,
                            # No usage counter in schema yet — leave 0
                            # so the formatter drops the "(used Nx)" suffix.
                            "usage": 0,
                        }
                    )
        except Exception as exc:
            logger.debug("briefing.horizon.skills_fetch_failed", error=str(exc))

        text = format_horizon_tier(
            scored=selected,
            collection_name=ctx.collection,
            active_skills=skills_block,
        )

        return TierOutput(
            tier="T1",
            text=text,
            tokens=count_tokens(text),
            budget=budget,
            memories_count=len(selected),
            meta={
                "candidate_count": len(candidates),
                "weights": weights.as_dict(),
                "embeddings_hit": len(embeddings),
            },
        )


async def _bulk_get_embeddings(vector_store: Any, ids: list[str]) -> dict[str, list[float]]:
    """Fetch embeddings for the given IDs in a single batch call.

    Different vector-store backends expose slightly different method
    names. We try the common shapes in order and fall back to an
    empty dict — never raising, because a missing vector cache is
    "expected" on cold start.
    """
    if not ids:
        return {}

    # Common shapes, in priority order. Each may or may not exist on
    # the store; we duck-type and bail silently if not.
    for method_name in ("get_embeddings", "get_vectors_batch", "retrieve_vectors"):
        fn = getattr(vector_store, method_name, None)
        if callable(fn):
            try:
                result = await fn(ids)
            except Exception as exc:
                logger.debug(
                    "briefing.horizon.vector_fetch_failed",
                    method=method_name,
                    error=str(exc),
                )
                continue
            if isinstance(result, dict):
                return {k: list(v) for k, v in result.items() if v}
    return {}


# --- T2 Orbit ------------------------------------------------------------


class OrbitTier(BaseTier):
    """T2 — memories filtered by collection / topic."""

    name: TierName = "T2"
    label: str = "Orbit"

    async def render(self, ctx: BriefingContext) -> TierOutput:
        budget = self._budget(ctx)
        metadata_store = ctx.metadata_store
        if metadata_store is None:
            text = format_orbit_tier(
                memories=[],
                collection_name=ctx.collection,
                topic=ctx.topic,
                empty_message="Store unavailable.",
            )
            return TierOutput(
                tier="T2",
                text=text,
                tokens=count_tokens(text),
                budget=budget,
                memories_count=0,
            )

        memories: list[Memory] = []

        # Collection path — either explicit ID or name lookup.
        if ctx.collection_id or ctx.collection:
            memories = await _memories_in_collection(
                metadata_store,
                collection_id=ctx.collection_id,
                collection_name=ctx.collection,
                limit=budget.max_memories,
            )
        else:
            # Topic-only: fall back to a metadata-store scan and filter
            # client-side. The metadata store has no topic index today,
            # so this stays bounded via ``limit``.
            pool = await metadata_store.get_memories_by_filter(
                session_config=ctx.session_config,
                limit=min(200, budget.max_memories * 5),
                user_id=ctx.user_id,
            )
            if ctx.topic:
                needle = ctx.topic.lower()
                memories = [m for m in pool if any(needle == t.lower() for t in m.topics)]
            else:
                memories = pool

        if ctx.topic and memories and ctx.collection:
            needle = ctx.topic.lower()
            memories = [m for m in memories if any(needle == t.lower() for t in m.topics)]

        memories = memories[: budget.max_memories]
        text = format_orbit_tier(
            memories=memories,
            collection_name=ctx.collection,
            topic=ctx.topic,
        )
        return TierOutput(
            tier="T2",
            text=text,
            tokens=count_tokens(text),
            budget=budget,
            memories_count=len(memories),
        )


async def _memories_in_collection(
    metadata_store: Any,
    *,
    collection_id: str | None,
    collection_name: str | None,
    limit: int,
) -> list[Memory]:
    """Resolve a collection by ID or name and return its memories.

    Returns an empty list on miss — callers decide how to render the
    emptiness.
    """
    target_id = collection_id
    if not target_id and collection_name:
        try:
            collections = await metadata_store.get_collections()
        except Exception:
            return []
        for c in collections:
            if c.name == collection_name:
                target_id = c.id
                break
    if not target_id:
        return []
    try:
        return await metadata_store.get_collection_memories(target_id, limit=limit, offset=0)
    except Exception:
        return []


# --- T3 Deep Recall ------------------------------------------------------


class DeepRecallTier(BaseTier):
    """T3 — full hybrid (semantic + FTS5) search."""

    name: TierName = "T3"
    label: str = "Deep Recall"

    async def render(self, ctx: BriefingContext) -> TierOutput:
        budget = self._budget(ctx)
        query = (ctx.query or "").strip()
        if not query:
            text = format_deep_recall_tier(
                results=[],
                query="",
                empty_message="Provide a query with `--query`.",
            )
            return TierOutput(
                tier="T3",
                text=text,
                tokens=count_tokens(text),
                budget=budget,
                memories_count=0,
            )

        results: list[dict[str, Any]] = []
        search_fn = ctx.hybrid_search_fn
        if search_fn is None:
            # Lazy import — intelligence extras may not be installed.
            try:
                from memgentic.graph.search import hybrid_search as _hs

                search_fn = _hs
            except ImportError:
                search_fn = None

        basic_fn = ctx.basic_search_fn
        if basic_fn is None:
            from memgentic.processing.search_basic import basic_search as _bs

            basic_fn = _bs

        try:
            if search_fn is not None:
                results = await search_fn(
                    query=query,
                    metadata_store=ctx.metadata_store,
                    vector_store=ctx.vector_store,
                    embedder=ctx.embedder,
                    graph=ctx.graph,
                    session_config=ctx.session_config,
                    limit=budget.max_memories,
                    user_id=ctx.user_id,
                )
            elif ctx.vector_store is not None and ctx.embedder is not None:
                results = await basic_fn(
                    query=query,
                    metadata_store=ctx.metadata_store,
                    vector_store=ctx.vector_store,
                    embedder=ctx.embedder,
                    session_config=ctx.session_config,
                    limit=budget.max_memories,
                    user_id=ctx.user_id,
                )
        except Exception as exc:
            logger.warning("briefing.deep_recall.search_failed", error=str(exc))
            results = []

        text = format_deep_recall_tier(results=results, query=query)
        return TierOutput(
            tier="T3",
            text=text,
            tokens=count_tokens(text),
            budget=budget,
            memories_count=len(results),
        )


# --- T4 Atlas ------------------------------------------------------------


class AtlasTier(BaseTier):
    """T4 — knowledge-graph traversal.

    Stubbed when the graph has no nodes yet (Chronograph parallel work
    populates the graph; we must not block on it). When populated but
    no entity was provided, we emit a gentle "pass --entity" hint.
    """

    name: TierName = "T4"
    label: str = "Atlas"

    async def render(self, ctx: BriefingContext) -> TierOutput:
        budget = self._budget(ctx)
        graph = ctx.graph
        graph_empty = graph is None or getattr(graph, "node_count", 0) == 0
        neighbors: list[dict[str, Any]] | None = None

        if not graph_empty and ctx.entity:
            try:
                data = await graph.query_neighbors(ctx.entity, depth=2)
                neighbors = list(data.get("neighbors") or [])
                if data.get("not_found"):
                    neighbors = []
            except Exception as exc:
                logger.warning("briefing.atlas.query_failed", entity=ctx.entity, error=str(exc))
                neighbors = []

        text = format_atlas_tier(
            entity=ctx.entity,
            neighbors=neighbors,
            graph_empty=graph_empty,
        )
        return TierOutput(
            tier="T4",
            text=text,
            tokens=count_tokens(text),
            budget=budget,
            memories_count=len(neighbors or []),
            meta={"graph_empty": graph_empty},
        )


# --- Orchestrator --------------------------------------------------------


@dataclass
class RecallStack:
    """Bundle of all five tiers + convenience briefing helpers.

    Typical use::

        stack = RecallStack()
        text = await stack.briefing(ctx)             # T0 + T1
        orbit = await stack.tier_recall("T2", ctx)   # explicit tier
    """

    persona: PersonaTier = field(default_factory=PersonaTier)
    horizon: HorizonTier = field(default_factory=HorizonTier)
    orbit: OrbitTier = field(default_factory=OrbitTier)
    deep_recall: DeepRecallTier = field(default_factory=DeepRecallTier)
    atlas: AtlasTier = field(default_factory=AtlasTier)

    _last_run: dict[str, Any] = field(default_factory=dict, repr=False)

    # Shortcut: name → tier instance.
    def _by_name(self, tier: str) -> BaseTier:
        mapping: dict[str, BaseTier] = {
            "T0": self.persona,
            "T1": self.horizon,
            "T2": self.orbit,
            "T3": self.deep_recall,
            "T4": self.atlas,
        }
        try:
            return mapping[tier]
        except KeyError as exc:
            raise ValueError(
                f"Unknown tier {tier!r}. Expected one of: T0, T1, T2, T3, T4."
            ) from exc

    async def briefing(self, ctx: BriefingContext) -> str:
        """Default wake-up: T0 + T1 assembled as a single string."""
        t0 = await self.persona._timed_render(ctx)
        t1 = await self.horizon._timed_render(ctx)
        self._last_run = {
            "mode": "briefing",
            "tiers": [t0.__dict__, t1.__dict__],
            "tokens": t0.tokens + t1.tokens,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        return assemble([t0.text, t1.text])

    async def tier_recall(self, tier: str, ctx: BriefingContext) -> TierOutput:
        """Render a single tier explicitly."""
        t = self._by_name(tier)
        out = await t._timed_render(ctx)
        self._last_run = {
            "mode": "tier_recall",
            "tier": tier,
            "tiers": [out.__dict__],
            "tokens": out.tokens,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        return out

    async def render_many(self, tiers: list[str], ctx: BriefingContext) -> list[TierOutput]:
        """Render multiple tiers in sequence (order preserved)."""
        outputs: list[TierOutput] = []
        total_tokens = 0
        for name in tiers:
            out = await self._by_name(name)._timed_render(ctx)
            outputs.append(out)
            total_tokens += out.tokens
        self._last_run = {
            "mode": "render_many",
            "tiers": [o.__dict__ for o in outputs],
            "tokens": total_tokens,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        return outputs

    def status(self) -> dict[str, Any]:
        """Snapshot of budgets and the most recent run's stats.

        Drives ``memgentic briefing --status`` and the dashboard's
        "briefing status" panel.
        """
        return {
            "tiers": {
                "T0": {"label": self.persona.label},
                "T1": {"label": self.horizon.label},
                "T2": {"label": self.orbit.label},
                "T3": {"label": self.deep_recall.label},
                "T4": {"label": self.atlas.label},
            },
            "budgets": {
                "T0": resolve_budget("T0").__dict__,
                "T1": resolve_budget("T1").__dict__,
                "T2": resolve_budget("T2").__dict__,
                "T3": resolve_budget("T3").__dict__,
                "T4": resolve_budget("T4").__dict__,
            },
            "last_run": self._last_run,
        }


async def get_briefing(ctx: BriefingContext) -> str:
    """Build a default :class:`RecallStack` and return its T0+T1 briefing."""
    return await RecallStack().briefing(ctx)


__all__ = [
    "AtlasTier",
    "BaseTier",
    "BriefingContext",
    "DeepRecallTier",
    "HorizonTier",
    "OrbitTier",
    "PersonaTier",
    "RecallStack",
    "TierOutput",
    "get_briefing",
]
