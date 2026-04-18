"""Memgentic MCP Server — source-aware AI memory with semantic search.

Tools:
- memgentic_recall: Semantic search with source filtering
- memgentic_remember: Store a new memory
- memgentic_sources: List available sources and stats
- memgentic_configure_session: Set session-level source filters
- memgentic_search: Full-text keyword search
- memgentic_recent: Get recent memories
- memgentic_stats: Memory statistics
- memgentic_briefing: Cross-agent briefing of recent memories

Prompts (slash commands):
- briefing: Get a cross-tool memory briefing of recent activity
- recall: Search memory for past solutions to a problem
- project-context: Load all known context about the current project

Resources (readable data endpoints):
- memory://recent: Memories from the last 24 hours
- memory://sources: Statistics about memory sources and platforms
- memory://briefing: Auto-generated briefing of recent memory activity
"""

from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from memgentic.config import settings
from memgentic.models import ContentType, MemoryStatus, Platform, SessionConfig
from memgentic.processing.embedder import Embedder
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.processing.search_basic import basic_search
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

# Intelligence imports — available when [intelligence] extras are installed
try:
    from memgentic.graph.knowledge import KnowledgeGraph, create_knowledge_graph
    from memgentic.graph.search import hybrid_search
    from memgentic.processing.llm import LLMClient

    HAS_INTELLIGENCE = True
except ImportError:
    HAS_INTELLIGENCE = False
    KnowledgeGraph = None  # type: ignore[assignment,misc]
    hybrid_search = None  # type: ignore[assignment]
    LLMClient = None  # type: ignore[assignment,misc]

logger = structlog.get_logger()

# Per-session configuration (keyed by session ID).
# Stored as (config, last_touched_utc) so we can evict stale entries.
_session_configs: dict[str, tuple[SessionConfig, datetime]] = {}
_SESSION_TTL = timedelta(hours=2)


def _evict_stale_sessions() -> None:
    """Drop session configs that have not been touched within the TTL."""
    now = datetime.now(UTC)
    stale = [sid for sid, (_, ts) in _session_configs.items() if now - ts > _SESSION_TTL]
    for sid in stale:
        _session_configs.pop(sid, None)


def _get_session_id(ctx: Context) -> str:
    """Derive a stable session ID from the MCP request context.

    Tries (in order): the FastMCP session's ``client_id``, its
    ``session_id``, and finally the Python object identity of the
    underlying session object — which at minimum isolates per-connection
    state. Falls back to ``"default"`` only if no context is available
    at all (e.g. legacy code paths or tests without a real Context).
    """
    try:
        session = ctx.request_context.session
        client_id = getattr(session, "client_id", None)
        if client_id:
            return str(client_id)
        sid = getattr(session, "session_id", None)
        if sid:
            return str(sid)
        return f"session_{id(session)}"
    except Exception:
        return "default"


def _get_session_config(ctx: Context) -> SessionConfig:
    """Look up the session config for the current context, or return a fresh default."""
    entry = _session_configs.get(_get_session_id(ctx))
    if entry is None:
        return SessionConfig()
    return entry[0]


def _set_session_config(session_id: str, config: SessionConfig) -> None:
    """Store a session config with a fresh TTL timestamp and prune stale entries."""
    _evict_stale_sessions()
    _session_configs[session_id] = (config, datetime.now(UTC))


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize storage and processing on server startup."""
    metadata_store = MetadataStore(settings.sqlite_path)
    vector_store = VectorStore(settings)
    embedder = Embedder(settings)

    # Optional: LLM client and knowledge graph (require [intelligence] extras)
    llm_client = None
    graph = None
    if LLMClient:
        llm_client = LLMClient(settings)
    if HAS_INTELLIGENCE and KnowledgeGraph:
        graph = create_knowledge_graph(settings.graph_path)
        await graph.load()
        logger.info("mcp_server.intelligence_loaded", graph_nodes=graph.node_count)
    else:
        logger.info(
            "mcp_server.no_intelligence",
            msg="Intelligence extras not installed. Using basic search. "
            "Install with: pip install mneme-core[intelligence]",
        )

    pipeline = IngestionPipeline(
        settings,
        metadata_store,
        vector_store,
        embedder,
        llm_client=llm_client,
        graph=graph,
    )

    await metadata_store.initialize()
    await vector_store.initialize(metadata_store)

    logger.info("mcp_server.ready", storage=settings.storage_backend.value)

    state = {
        "metadata_store": metadata_store,
        "vector_store": vector_store,
        "embedder": embedder,
        "pipeline": pipeline,
        "graph": graph,
    }

    # If ``run_server_with_watcher`` asked to fuse the daemon, start it now
    # against the same stores and register a shutdown hook. Any failure here
    # is logged but does not abort the MCP server — MCP alone is still useful.
    daemon_shutdown = None
    if _watch_mode_attach is not None:
        try:
            _daemon, daemon_shutdown = await _watch_mode_attach(state)
        except Exception as exc:
            logger.error("mcp_server.watch_mode.attach_failed", error=str(exc))
            daemon_shutdown = None

    try:
        yield state
    finally:
        if daemon_shutdown is not None:
            await daemon_shutdown()

        if graph:
            await graph.save()
        await embedder.close()
        await metadata_store.close()
        await vector_store.close()


# Initialize MCP server
mcp = FastMCP("memgentic_mcp", lifespan=app_lifespan)


# --- Input Models ---


class RecallInput(BaseModel):
    """Input for semantic memory recall with source filtering."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description="What to search for in memory (semantic search)",
        min_length=2,
        max_length=1000,
    )
    sources: list[str] | None = Field(
        default=None,
        description=(
            "Only include memories from these platforms "
            "(e.g., ['claude_code', 'chatgpt']). None = use session defaults."
        ),
    )
    exclude_sources: list[str] | None = Field(
        default=None,
        description="Exclude memories from these platforms (e.g., ['codex_cli'])",
    )
    content_types: list[str] | None = Field(
        default=None,
        description=(
            "Filter by content type: decision, code_snippet, fact, "
            "preference, learning, action_item, conversation_summary"
        ),
    )
    limit: int = Field(
        default=10,
        description="Maximum number of results (1-50)",
        ge=1,
        le=50,
    )
    detail: Literal["index", "preview", "full"] = Field(
        default="preview",
        description=(
            "Detail level: 'index' (~50 tok/result, ID+type+date+50char), "
            "'preview' (~200 tok/result, 300char content, default), "
            "'full' (~500+ tok/result, complete content + metadata)"
        ),
    )


class ExpandInput(BaseModel):
    """Input for expanding a memory by ID."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    memory_id: str = Field(
        ...,
        description="Memory ID returned by a previous memgentic_recall call",
        min_length=1,
    )


class RememberInput(BaseModel):
    """Input for storing a new memory."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(
        ...,
        description="The knowledge/fact/decision to remember",
        min_length=3,
        max_length=10000,
    )
    content_type: str = Field(
        default="fact",
        description=("Type: fact, decision, code_snippet, preference, learning, action_item"),
    )
    topics: list[str] | None = Field(
        default=None,
        description="Tags/topics for this memory (e.g., ['python', 'architecture'])",
    )
    entities: list[str] | None = Field(
        default=None,
        description="People/projects/technologies mentioned",
    )
    source: str = Field(
        default="unknown",
        description="Source platform (e.g., 'claude_code', 'chatgpt'). Auto-detected.",
    )


class ConfigureSessionInput(BaseModel):
    """Input for setting session-level source filters."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    include_sources: list[str] | None = Field(
        default=None,
        description="Only include these platforms in all recall calls (None = all)",
    )
    exclude_sources: list[str] | None = Field(
        default=None,
        description="Exclude these platforms from all recall calls",
    )
    content_types: list[str] | None = Field(
        default=None,
        description="Only include these content types",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold (0.0-1.0)",
    )


class SearchInput(BaseModel):
    """Input for full-text keyword search."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Keywords to search for", min_length=2)
    limit: int = Field(default=10, ge=1, le=50)


class RecentInput(BaseModel):
    """Input for retrieving recent memories."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    limit: int = Field(default=10, ge=1, le=50, description="Number of recent memories")
    source: str | None = Field(default=None, description="Filter by platform")
    content_type: str | None = Field(default=None, description="Filter by content type")


# --- Helper Functions ---


def _get_effective_config(
    ctx: Context,
    sources: list[str] | None = None,
    exclude_sources: list[str] | None = None,
    content_types: list[str] | None = None,
) -> SessionConfig:
    """Merge per-call filters with session-level defaults."""
    session_config = _get_session_config(ctx)
    config = SessionConfig(
        include_sources=session_config.include_sources,
        exclude_sources=session_config.exclude_sources,
        include_content_types=session_config.include_content_types,
        min_confidence=session_config.min_confidence,
    )

    # Per-call overrides take precedence
    if sources is not None:
        config.include_sources = [Platform(s) for s in sources]
    if exclude_sources is not None:
        config.exclude_sources = [Platform(s) for s in exclude_sources]
    if content_types is not None:
        config.include_content_types = [ContentType(ct) for ct in content_types]

    return config


def _format_memory_md(
    memory_data: dict, score: float | None = None, detail: str = "preview"
) -> str:
    """Format a memory as markdown at the requested detail level."""
    platform = memory_data.get("platform", "unknown")
    content_type = memory_data.get("content_type", "fact")
    mid = memory_data.get("id", "")
    content = memory_data.get("content", "")
    created = memory_data.get("created_at", "")
    date = created[:10] if created else ""

    if detail == "index":
        preview = content[:50].replace("\n", " ")
        suffix = "..." if len(content) > 50 else ""
        return f"- `{mid}` [{content_type}] {preview}{suffix} | {platform} | {date}"

    score_str = f" (relevance: {score:.2f})" if score is not None else ""
    lines = [f"### [{content_type}] from {platform}{score_str}", ""]

    if detail == "full":
        lines.append(content)
    else:  # preview (default)
        lines.append(content[:300] + ("..." if len(content) > 300 else ""))
    lines.append("")

    topics = memory_data.get("topics", [])
    if topics:
        lines.append(f"**Topics:** {', '.join(topics)}")

    session_title = memory_data.get("session_title", "")
    if session_title and detail == "full" or session_title and detail != "full":
        lines.append(f"**Session:** {session_title}")

    if detail == "full" and mid:
        lines.append(f"**ID:** `{mid}`")

    if date:
        lines.append(f"**Date:** {date}")

    lines.append("---")
    return "\n".join(lines)


# --- MCP Tools ---


@mcp.tool(
    name="memgentic_recall",
    annotations={
        "title": "Recall from Memory",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_recall(params: RecallInput, ctx: Context) -> str:
    """Search your AI memory using semantic similarity.

    Finds relevant memories across all your AI conversations, with optional
    source-level filtering. Respects session configuration set via
    memgentic_configure_session.

    Args:
        params (RecallInput): Search parameters:
            - query (str): What to search for
            - sources (list[str]): Only these platforms (overrides session config)
            - exclude_sources (list[str]): Exclude these platforms
            - content_types (list[str]): Filter by type (decision, code_snippet, etc.)
            - limit (int): Max results (default 10)

    Returns:
        str: Markdown-formatted list of relevant memories with source metadata.

    Examples:
        - "React performance optimization" → finds related discussions
        - query="FastAPI architecture", sources=["claude_code"] → only Claude Code
        - query="what did we decide", content_types=["decision"] → decisions only
    """
    try:
        state = ctx.request_context.lifespan_context
        embedder: Embedder = state["embedder"]
        vector_store: VectorStore = state["vector_store"]
        metadata_store: MetadataStore = state["metadata_store"]
        graph = state.get("graph")

        # Build effective filter config
        config = _get_effective_config(
            ctx,
            sources=params.sources,
            exclude_sources=params.exclude_sources,
            content_types=params.content_types,
        )

        # Use hybrid search if intelligence installed, otherwise basic vector search
        if HAS_INTELLIGENCE and hybrid_search is not None:
            results = await hybrid_search(
                query=params.query,
                metadata_store=metadata_store,
                vector_store=vector_store,
                embedder=embedder,
                graph=graph,
                session_config=config,
                limit=params.limit,
            )
        else:
            results = await basic_search(
                query=params.query,
                metadata_store=metadata_store,
                vector_store=vector_store,
                embedder=embedder,
                session_config=config,
                limit=params.limit,
            )

        if not results:
            return f"No memories found for: '{params.query}'"

        # Format results
        lines = [f"# Memory Recall: '{params.query}'", ""]
        lines.append(f"Found {len(results)} relevant memories:")
        lines.append("")

        for result in results:
            # Update access stats
            await metadata_store.update_access(result["id"])
            payload = dict(result.get("payload") or {})
            payload.setdefault("id", result["id"])
            lines.append(_format_memory_md(payload, result["score"], detail=params.detail))

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_recall.error", error=str(exc))
        return f"Error searching memories: {exc}"


@mcp.tool(
    name="memgentic_expand",
    annotations={
        "title": "Expand Memory",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_expand(params: ExpandInput, ctx: Context) -> str:
    """Get full content and metadata for a specific memory by ID.

    Use after memgentic_recall with detail='index' to drill into specific results.
    """
    try:
        state = ctx.request_context.lifespan_context
        metadata_store: MetadataStore = state["metadata_store"]
        memory = await metadata_store.get_memory(params.memory_id)
        if memory is None:
            return f"Memory not found: {params.memory_id}"
        await metadata_store.update_access(params.memory_id)

        data = {
            "id": memory.id,
            "content": memory.content,
            "content_type": memory.content_type.value,
            "platform": memory.source.platform.value,
            "created_at": memory.created_at.isoformat() if memory.created_at else "",
            "topics": memory.topics,
            "session_title": memory.source.session_title or "",
        }
        return _format_memory_md(data, detail="full")
    except Exception as exc:
        logger.error("memgentic_expand.error", error=str(exc))
        return f"Error expanding memory: {exc}"


@mcp.tool(
    name="memgentic_remember",
    annotations={
        "title": "Remember Something",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def memgentic_remember(params: RememberInput, ctx: Context) -> str:
    """Store a new memory in Memgentic.

    Saves a piece of knowledge with full source metadata so it can be
    recalled later from any AI tool.

    Args:
        params (RememberInput): Memory to store:
            - content (str): The knowledge to remember
            - content_type (str): Type (fact, decision, code_snippet, etc.)
            - topics (list[str]): Tags for this memory
            - entities (list[str]): People/projects mentioned
            - source (str): Source platform

    Returns:
        str: Confirmation with memory ID.
    """
    try:
        state = ctx.request_context.lifespan_context
        pipeline: IngestionPipeline = state["pipeline"]

        try:
            ct = ContentType(params.content_type)
        except ValueError:
            ct = ContentType.FACT

        try:
            platform = Platform(params.source)
        except ValueError:
            platform = Platform.UNKNOWN

        memory = await pipeline.ingest_single(
            content=params.content,
            content_type=ct,
            platform=platform,
            topics=params.topics,
            entities=params.entities,
        )

        return (
            f"Remembered! Memory ID: `{memory.id}`\n\n"
            f"- **Type:** {memory.content_type.value}\n"
            f"- **Source:** {memory.source.platform.value}\n"
            f"- **Topics:** {', '.join(memory.topics) if memory.topics else 'none'}\n"
            f"- **Content preview:** {memory.content[:100]}..."
        )
    except Exception as exc:
        logger.error("memgentic_remember.error", error=str(exc))
        return f"Error storing memory: {exc}"


@mcp.tool(
    name="memgentic_sources",
    annotations={
        "title": "List Memory Sources",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_sources(ctx: Context) -> str:
    """List all source platforms and their memory counts.

    Shows which AI tools have contributed memories and how many from each.

    Returns:
        str: Markdown table of sources and counts.
    """
    try:
        state = ctx.request_context.lifespan_context
        metadata_store: MetadataStore = state["metadata_store"]

        stats = await metadata_store.get_source_stats()
        total = await metadata_store.get_total_count()

        if not stats:
            return "No memories stored yet. Use `memgentic_remember` to add your first memory."

        lines = ["# Memory Sources", ""]
        lines.append(f"**Total memories:** {total}")
        lines.append("")
        lines.append("| Platform | Memories |")
        lines.append("|----------|----------|")
        for platform, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {platform} | {count} |")
        lines.append("")
        lines.append(
            "Use `memgentic_configure_session` to set default source filters for this session."
        )

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_sources.error", error=str(exc))
        return f"Error listing sources: {exc}"


@mcp.tool(
    name="memgentic_configure_session",
    annotations={
        "title": "Configure Session Filters",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_configure_session(params: ConfigureSessionInput, ctx: Context) -> str:
    """Set session-level default filters for memory recall.

    All subsequent `memgentic_recall` calls in this session will use these
    defaults unless explicitly overridden per-call.

    Args:
        params (ConfigureSessionInput): Session filters:
            - include_sources: Only these platforms (e.g., ['claude_code', 'gemini_cli'])
            - exclude_sources: Exclude these (e.g., ['codex_cli'])
            - content_types: Only these types (e.g., ['decision', 'code_snippet'])
            - min_confidence: Minimum confidence (0.0-1.0)

    Returns:
        str: Confirmation of applied session configuration.

    Examples:
        - include_sources=["claude_code", "gemini_cli"] → only these two
        - exclude_sources=["codex_cli"] → everything except Codex
        - content_types=["decision"] → only decisions
    """
    try:
        session_id = _get_session_id(ctx)

        session_config = SessionConfig(
            include_sources=[Platform(s) for s in params.include_sources]
            if params.include_sources
            else None,
            exclude_sources=[Platform(s) for s in params.exclude_sources]
            if params.exclude_sources
            else None,
            include_content_types=[ContentType(ct) for ct in params.content_types]
            if params.content_types
            else None,
            min_confidence=params.min_confidence,
        )
        _set_session_config(session_id, session_config)

        lines = ["# Session Configured", ""]
        if session_config.include_sources:
            lines.append(
                f"- **Include:** {', '.join(s.value for s in session_config.include_sources)}"
            )
        if session_config.exclude_sources:
            lines.append(
                f"- **Exclude:** {', '.join(s.value for s in session_config.exclude_sources)}"
            )
        if session_config.include_content_types:
            lines.append(
                f"- **Types:** {', '.join(ct.value for ct in session_config.include_content_types)}"
            )
        if session_config.min_confidence > 0:
            lines.append(f"- **Min confidence:** {session_config.min_confidence}")
        lines.append("")
        lines.append("All subsequent `memgentic_recall` calls will use these defaults.")

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_configure_session.error", error=str(exc))
        return f"Error configuring session: {exc}"


@mcp.tool(
    name="memgentic_search",
    annotations={
        "title": "Keyword Search Memory",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_search(params: SearchInput, ctx: Context) -> str:
    """Full-text keyword search across all memories.

    Unlike `memgentic_recall` (semantic), this does exact keyword matching
    using SQLite FTS5. Useful for finding specific terms or code.

    Args:
        params (SearchInput): Search parameters:
            - query (str): Keywords to search for
            - limit (int): Max results

    Returns:
        str: Markdown-formatted matching memories.
    """
    try:
        state = ctx.request_context.lifespan_context
        metadata_store: MetadataStore = state["metadata_store"]

        session_config = _get_session_config(ctx)

        memories = await metadata_store.search_fulltext(
            query=params.query,
            session_config=session_config,
            limit=params.limit,
        )

        if not memories:
            return f"No memories found matching keywords: '{params.query}'"

        lines = [f"# Keyword Search: '{params.query}'", ""]
        lines.append(f"Found {len(memories)} matches:")
        lines.append("")

        for mem in memories:
            lines.append(f"### [{mem.content_type.value}] from {mem.source.platform.value}")
            lines.append("")
            lines.append(mem.content[:500])
            if mem.topics:
                lines.append(f"\n**Topics:** {', '.join(mem.topics)}")
            lines.append(f"\n**Date:** {mem.created_at.strftime('%Y-%m-%d')}")
            lines.append("---")

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_search.error", error=str(exc))
        return f"Error searching memories: {exc}"


@mcp.tool(
    name="memgentic_recent",
    annotations={
        "title": "Recent Memories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_recent(params: RecentInput, ctx: Context) -> str:
    """Get the most recent memories, optionally filtered by source or type.

    Args:
        params (RecentInput): Parameters:
            - limit (int): How many recent memories (default 10)
            - source (str): Filter by platform (e.g., 'claude_code')
            - content_type (str): Filter by type (e.g., 'decision')

    Returns:
        str: Markdown list of recent memories.
    """
    try:
        state = ctx.request_context.lifespan_context
        metadata_store: MetadataStore = state["metadata_store"]

        config = _get_session_config(ctx)
        if params.source:
            config = SessionConfig(
                include_sources=[Platform(params.source)],
                exclude_sources=config.exclude_sources,
                include_content_types=config.include_content_types,
                min_confidence=config.min_confidence,
            )

        ct = ContentType(params.content_type) if params.content_type else None

        memories = await metadata_store.get_memories_by_filter(
            session_config=config,
            content_type=ct,
            limit=params.limit,
        )

        if not memories:
            return "No recent memories found."

        lines = ["# Recent Memories", ""]
        for mem in memories:
            lines.append(f"### [{mem.content_type.value}] from {mem.source.platform.value}")
            lines.append(f"*{mem.created_at.strftime('%Y-%m-%d %H:%M')}*")
            lines.append("")
            lines.append(mem.content[:300])
            if mem.topics:
                lines.append(f"\n**Topics:** {', '.join(mem.topics)}")
            lines.append("---")

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_recent.error", error=str(exc))
        return f"Error retrieving recent memories: {exc}"


@mcp.tool(
    name="memgentic_stats",
    annotations={
        "title": "Memory Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_stats(ctx: Context) -> str:
    """Get comprehensive memory statistics.

    Returns:
        str: Stats including total memories, per-source counts,
             vector store info, and current session config.
    """
    try:
        state = ctx.request_context.lifespan_context
        metadata_store: MetadataStore = state["metadata_store"]
        vector_store: VectorStore = state["vector_store"]

        source_stats = await metadata_store.get_source_stats()
        total = await metadata_store.get_total_count()
        vector_info = await vector_store.get_collection_info()

        lines = ["# Memgentic Statistics", ""]
        lines.append(f"**Total memories:** {total}")
        lines.append(f"**Vector count:** {vector_info.get('indexed_vectors_count', 0)}")
        lines.append(f"**Store status:** {vector_info.get('status', 'unknown')}")
        lines.append("")

        if source_stats:
            lines.append("## By Source")
            for platform, count in sorted(source_stats.items(), key=lambda x: x[1], reverse=True):
                pct = (count / total * 100) if total > 0 else 0
                lines.append(f"- **{platform}:** {count} ({pct:.0f}%)")
            lines.append("")

        # Current session config
        session_config = _get_session_config(ctx)
        lines.append("## Session Config")
        if session_config.include_sources:
            lines.append(f"- Include: {', '.join(s.value for s in session_config.include_sources)}")
        elif session_config.exclude_sources:
            lines.append(f"- Exclude: {', '.join(s.value for s in session_config.exclude_sources)}")
        else:
            lines.append("- All sources active (no filters)")

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_stats.error", error=str(exc))
        return f"Error retrieving stats: {exc}"


class BriefingInput(BaseModel):
    """Input for cross-agent briefing."""

    model_config = ConfigDict(str_strip_whitespace=True)

    since_hours: int = Field(
        default=24, ge=1, le=720, description="Hours to look back (default: 24)"
    )


@mcp.tool(
    name="memgentic_briefing",
    annotations={
        "title": "Cross-Agent Briefing",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_briefing(params: BriefingInput, ctx: Context) -> str:
    """Get a briefing of new memories since your last session.

    Shows what's new across all AI tools — perfect for starting a new
    conversation with context from other agents.

    Args:
        params (BriefingInput): Parameters:
            - since_hours (int): Hours to look back (default 24, max 720)

    Returns:
        str: Markdown briefing with platform counts, top topics, and previews.
    """
    try:
        metadata_store = ctx.request_context.lifespan_context["metadata_store"]
        since = datetime.now(UTC) - timedelta(hours=params.since_hours)
        memories = await metadata_store.get_memories_since(since, limit=100)

        if not memories:
            return f"No new memories in the last {params.since_hours} hours."

        # Group by platform
        platform_counts = Counter(m.source.platform.value for m in memories)
        all_topics: list[str] = []
        for m in memories:
            all_topics.extend(m.topics)
        top_topics = Counter(all_topics).most_common(10)

        lines = [f"# Briefing — Last {params.since_hours} hours", ""]
        lines.append(f"**{len(memories)} new memories** across {len(platform_counts)} platforms:")
        lines.append("")
        for platform, count in platform_counts.most_common():
            lines.append(f"- **{platform}**: {count} memories")

        if top_topics:
            lines.append("")
            lines.append("**Top topics:** " + ", ".join(t for t, _ in top_topics[:8]))

        # Preview latest 5
        lines.append("")
        lines.append("## Latest")
        for m in memories[:5]:
            preview = m.content[:150].replace("\n", " ")
            lines.append(f"- [{m.content_type.value}] {preview}...")

        return "\n".join(lines)
    except Exception as e:
        logger.error("memgentic_briefing.error", error=str(e))
        return f"Error generating briefing: {e}"


class ForgetInput(BaseModel):
    """Input for archiving a memory."""

    model_config = ConfigDict(str_strip_whitespace=True)

    memory_id: str = Field(..., description="ID of the memory to archive/forget")


@mcp.tool(
    name="memgentic_forget",
    description="Archive (soft-delete) a memory by ID. The memory is not permanently deleted.",
    annotations={"destructiveHint": True, "idempotentHint": True, "readOnlyHint": False},
)
async def memgentic_forget(params: ForgetInput, ctx: Context) -> str:
    """Archive a memory so it no longer appears in search results.

    Args:
        params (ForgetInput): Parameters:
            - memory_id (str): ID of the memory to archive

    Returns:
        str: Confirmation or error message.
    """
    try:
        metadata_store: MetadataStore = ctx.request_context.lifespan_context["metadata_store"]
        vector_store: VectorStore = ctx.request_context.lifespan_context["vector_store"]

        memory = await metadata_store.get_memory(params.memory_id)
        if not memory:
            return f"Memory {params.memory_id} not found."

        memory.status = MemoryStatus.ARCHIVED
        await metadata_store.save_memory(memory)
        await vector_store.delete_memory(params.memory_id)

        return f"Memory {params.memory_id} archived successfully."
    except Exception as e:
        logger.error("memgentic_forget.error", error=str(e))
        return f"Error archiving memory: {e}"


class ExportInput(BaseModel):
    """Input for exporting memories."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source: str | None = Field(default=None, description="Filter by platform (optional)")
    limit: int = Field(default=100, ge=1, le=1000, description="Max memories to export")


@mcp.tool(
    name="memgentic_export",
    description="Export memories as JSON. Optionally filter by platform.",
    annotations={"readOnlyHint": True},
)
async def memgentic_export(params: ExportInput, ctx: Context) -> str:
    """Export memories as a JSON array for backup or migration.

    Args:
        params (ExportInput): Parameters:
            - source (str | None): Filter by platform
            - limit (int): Max memories to export (1-1000)

    Returns:
        str: JSON array of memories.
    """
    try:
        import json

        metadata_store: MetadataStore = ctx.request_context.lifespan_context["metadata_store"]

        config = SessionConfig()
        if params.source:
            config.include_sources = [Platform(params.source)]

        memories = await metadata_store.get_memories_by_filter(
            session_config=config, limit=params.limit
        )

        data = [
            {
                "id": m.id,
                "content": m.content,
                "content_type": m.content_type.value,
                "platform": m.source.platform.value,
                "topics": m.topics,
                "entities": m.entities,
                "created_at": m.created_at.isoformat(),
            }
            for m in memories
        ]

        return json.dumps(data, indent=2)
    except Exception as e:
        logger.error("memgentic_export.error", error=str(e))
        return f"Error exporting memories: {e}"


# ---------------------------------------------------------------------------
# MCP Prompts — slash commands for common memory workflows
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="briefing",
    description="Get a cross-tool memory briefing of recent activity",
)
async def briefing_prompt(project: str = "") -> str:
    """Generate a cross-tool memory briefing."""
    base = (
        "Please call the memgentic_briefing tool to get recent memories from all AI tools, "
        "then provide a concise summary of what's been happening. "
        "Highlight any decisions, learnings, and action items."
    )
    if project:
        base += f"\n\nFocus specifically on the project: {project}"
    return base


@mcp.prompt(
    name="recall",
    description="Search memory for past solutions to a problem",
)
async def recall_prompt(query: str = "recent work") -> str:
    """Have we solved this before?"""
    return (
        f'Please call the memgentic_recall tool with query="{query}" to check if we\'ve '
        f"encountered this before or have relevant context from any AI tool. "
        f"Summarize what you find and explain how it applies to the current situation."
    )


@mcp.prompt(
    name="project-context",
    description="Load all known context about the current project",
)
async def project_context_prompt(path: str = "") -> str:
    """What do we know about this project?"""
    project_hint = f" for the project at {path}" if path else ""
    return (
        f"Please build comprehensive project context{project_hint}:\n"
        f"1. Call memgentic_briefing to get recent activity\n"
        f"2. Call memgentic_recall with relevant project keywords\n"
        f"3. Call memgentic_sources to see which tools have contributed\n"
        f"4. Summarize all decisions, preferences, and key learnings"
    )


# ---------------------------------------------------------------------------
# MCP Resources — readable data endpoints for memory state
# ---------------------------------------------------------------------------


# NOTE: FastMCP resource handlers are invoked with no arguments by
# ``FunctionResource.read()`` — unlike tools, they cannot receive a
# ``Context`` object and therefore cannot access ``lifespan_state``.
# As a result, each resource handler below opens its own short-lived
# ``MetadataStore``. This is a known FastMCP API limitation (see
# ``mcp.server.fastmcp.resources.types.FunctionResource.read``). If the
# upstream API gains context support we should refactor to use the
# lifespan-managed store.
@mcp.resource(
    "memory://recent",
    name="Recent Memories",
    description="Memories from the last 24 hours",
    mime_type="text/markdown",
)
async def recent_memories_resource() -> str:
    """Return recent memories as markdown."""
    store = MetadataStore(settings.sqlite_path)
    await store.initialize()
    try:
        since = datetime.now(UTC) - timedelta(hours=24)
        memories = await store.get_memories_since(since, limit=50)
        if not memories:
            return "No memories in the last 24 hours."

        lines = ["# Recent Memories (Last 24h)", ""]
        for m in memories:
            platform = m.source.platform.value
            ct = m.content_type.value
            preview = m.content[:150].replace("\n", " ")
            lines.append(f"- **[{ct}]** {preview}")
            lines.append(f"  _{platform} | {m.created_at.strftime('%Y-%m-%d %H:%M')}_")
            lines.append("")
        return "\n".join(lines)
    finally:
        await store.close()


@mcp.resource(
    "memory://sources",
    name="Memory Sources",
    description="Statistics about memory sources and platforms",
    mime_type="text/markdown",
)
async def sources_resource() -> str:
    """Return source statistics as markdown."""
    store = MetadataStore(settings.sqlite_path)
    await store.initialize()
    try:
        stats = await store.get_source_stats()
        total = await store.get_total_count()
        if not stats:
            return "No memories stored yet."

        lines = [f"# Memory Sources (Total: {total})", ""]
        lines.append("| Platform | Count | % |")
        lines.append("|----------|------:|--:|")
        for platform, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"| {platform} | {count} | {pct:.0f}% |")
        return "\n".join(lines)
    finally:
        await store.close()


@mcp.resource(
    "memory://briefing",
    name="Auto Briefing",
    description="Auto-generated briefing of recent memory activity",
    mime_type="text/markdown",
)
async def briefing_resource() -> str:
    """Return an auto-generated briefing."""
    store = MetadataStore(settings.sqlite_path)
    await store.initialize()
    try:
        since = datetime.now(UTC) - timedelta(hours=24)
        memories = await store.get_memories_since(since, limit=100)
        if not memories:
            return "No new memories in the last 24 hours."

        platform_counts = Counter(m.source.platform.value for m in memories)
        all_topics: list[str] = []
        for m in memories:
            all_topics.extend(m.topics)
        top_topics = Counter(all_topics).most_common(10)

        lines = ["# Memory Briefing", ""]
        lines.append(f"**{len(memories)} memories** in the last 24 hours:")
        lines.append("")
        for platform, count in platform_counts.most_common():
            lines.append(f"- {platform}: {count} memories")
        if top_topics:
            lines.append("")
            lines.append("**Top topics:** " + ", ".join(t for t, _ in top_topics[:8]))

        # Show a few recent highlights
        lines.append("")
        lines.append("**Recent highlights:**")
        for m in memories[:5]:
            preview = m.content[:100].replace("\n", " ")
            lines.append(f"- [{m.source.platform.value}] {preview}...")

        return "\n".join(lines)
    finally:
        await store.close()


class PinInput(BaseModel):
    """Input for pinning/unpinning a memory."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    memory_id: str = Field(..., description="ID of the memory to pin or unpin")
    unpin: bool = Field(
        default=False,
        description="If true, unpin instead of pin",
    )


@mcp.tool(
    name="memgentic_pin",
    annotations={
        "title": "Pin/Unpin Memory",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_pin(params: PinInput, ctx: Context) -> str:
    """Pin or unpin a memory for quick access.

    Pinned memories appear in the pinned list and are easier to find.

    Args:
        params (PinInput): Parameters:
            - memory_id (str): ID of the memory
            - unpin (bool): If true, unpin instead of pin (default false)

    Returns:
        str: Confirmation message.
    """
    try:
        metadata_store: MetadataStore = ctx.request_context.lifespan_context["metadata_store"]

        memory = await metadata_store.get_memory(params.memory_id)
        if not memory:
            return f"Memory {params.memory_id} not found."

        if params.unpin:
            await metadata_store.unpin_memory(params.memory_id)
            return f"Memory {params.memory_id} unpinned."
        else:
            await metadata_store.pin_memory(params.memory_id)
            return f"Memory {params.memory_id} pinned."
    except Exception as exc:
        logger.error("memgentic_pin.error", error=str(exc))
        return f"Error pinning/unpinning memory: {exc}"


@mcp.tool(
    name="memgentic_skills",
    annotations={
        "title": "List Skills",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_skills_tool(ctx: Context) -> str:
    """List all available skills with their names and descriptions.

    Returns a compact list of skill names and descriptions for discovery.

    Returns:
        str: Markdown list of available skills.
    """
    try:
        metadata_store: MetadataStore = ctx.request_context.lifespan_context["metadata_store"]

        skills = await metadata_store.get_skills()
        if not skills:
            return "No skills available. Create one via the dashboard or API."

        lines = ["# Available Skills", ""]
        for skill in skills:
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            lines.append(f"- **{skill.name}**: {skill.description or '(no description)'}{tags_str}")

        lines.append("")
        lines.append("Use `memgentic_skill` with a skill name to get the full content.")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_skills.error", error=str(exc))
        return f"Error listing skills: {exc}"


class SkillInput(BaseModel):
    """Input for retrieving a single skill by name."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(..., description="Name of the skill to retrieve", min_length=1)


@mcp.tool(
    name="memgentic_skill",
    annotations={
        "title": "Get Skill",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def memgentic_skill_tool(params: SkillInput, ctx: Context) -> str:
    """Get a specific skill's full content by name.

    Returns the complete SKILL.md content and lists any supporting files.

    Args:
        params (SkillInput): Parameters:
            - name (str): Name of the skill to retrieve

    Returns:
        str: Full skill content in markdown format.
    """
    try:
        metadata_store: MetadataStore = ctx.request_context.lifespan_context["metadata_store"]

        skill = await metadata_store.get_skill_by_name(params.name)
        if not skill:
            return (
                f"Skill '{params.name}' not found. Use `memgentic_skills` to see available skills."
            )

        lines = [f"# Skill: {skill.name}", ""]
        if skill.description:
            lines.append(f"*{skill.description}*")
            lines.append("")
        if skill.tags:
            lines.append(f"**Tags:** {', '.join(skill.tags)}")
            lines.append("")

        lines.append("## Content")
        lines.append("")
        lines.append(skill.content)

        if skill.files:
            lines.append("")
            lines.append("## Files")
            for sf in skill.files:
                lines.append(f"\n### {sf.path}")
                lines.append(f"```\n{sf.content}\n```")

        return "\n".join(lines)
    except Exception as exc:
        logger.error("memgentic_skill.error", error=str(exc))
        return f"Error retrieving skill: {exc}"


# Entry point
def run_server() -> None:
    """Run the Memgentic MCP server."""
    mcp.run(transport=settings.mcp_transport)


# Module-level hook used by the ``--watch`` path to attach the capture daemon
# to the MCP server's lifespan. When set, ``app_lifespan`` calls it with the
# fully-initialised store state and expects back an async shutdown callable.
# Starting the daemon inside the lifespan means MCP tools and the watcher
# share a single SQLite writer and Qdrant handle (no lock contention, no
# duplicate embedding clients). ``cli.py`` is the sole expected setter.
_watch_mode_attach = None  # type: ignore[var-annotated]


async def run_server_with_watcher(scan_existing: bool = True) -> None:
    """Run the MCP stdio server with the capture daemon in the same loop.

    Fuses ``memgentic serve`` and ``memgentic daemon`` into a single process
    so there is exactly one SQLite writer and one Qdrant handle. The daemon's
    lifecycle is bound to the server: the watcher starts inside the FastMCP
    lifespan (reusing the same stores the MCP tools use) and stops when the
    server exits. Only stdio transport is supported.
    """
    from memgentic.adapters import get_daemon_adapters
    from memgentic.daemon.watcher import MemgenticDaemon

    global _watch_mode_attach

    async def _attach(state: dict):
        adapters = get_daemon_adapters()
        daemon = MemgenticDaemon(
            settings,
            state["pipeline"],
            adapters,
            metadata_store=state["metadata_store"],
        )

        if scan_existing:
            logger.info("mcp_server.watch_mode.scanning_existing")
            try:
                count = await daemon.scan_existing()
                logger.info("mcp_server.watch_mode.scan_complete", files=count)
            except Exception as exc:  # non-fatal: still watch new files
                logger.error("mcp_server.watch_mode.scan_failed", error=str(exc))

        await daemon.start()
        logger.info("mcp_server.watch_mode.daemon_started")

        async def _shutdown() -> None:
            import contextlib as _ctx

            with _ctx.suppress(Exception):
                await daemon.stop()
            logger.info("mcp_server.watch_mode.daemon_stopped")

        return daemon, _shutdown

    _watch_mode_attach = _attach
    try:
        await mcp.run_stdio_async()
    finally:
        _watch_mode_attach = None
