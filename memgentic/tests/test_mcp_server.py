"""Tests for MCP server tool functions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import the tool functions directly
from memgentic.mcp.server import (
    BriefingInput,
    ConfigureSessionInput,
    ContextInput,
    ExportInput,
    ForgetInput,
    HandoffInput,
    InventoryInput,
    RecallInput,
    RecentInput,
    RememberInput,
    SearchInput,
    _get_session_id,
    _session_configs,
    _set_session_config,
    memgentic_briefing,
    memgentic_configure_session,
    memgentic_context,
    memgentic_export,
    memgentic_forget,
    memgentic_handoff,
    memgentic_inventory,
    memgentic_recall,
    memgentic_recent,
    memgentic_remember,
    memgentic_search,
    memgentic_sources,
    memgentic_stats,
)
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    MemoryStatus,
    Platform,
    SourceMetadata,
)

DIMS = 768


def _fake_embedding(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


def _make_memory(mid: str = "mem-001", content: str = "Test memory content") -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=Platform.CLAUDE_CODE,
            capture_method=CaptureMethod.MCP_TOOL,
            original_timestamp=datetime(2026, 3, 25, 10, 0, 0, tzinfo=UTC),
        ),
        topics=["python", "testing"],
        entities=["Memgentic"],
    )


def _mock_ctx(metadata_store, vector_store, embedder, pipeline, graph):
    """Create a mock MCP Context with lifespan context (matches server.py)."""
    ctx = MagicMock()
    state = {
        "metadata_store": metadata_store,
        "vector_store": vector_store,
        "embedder": embedder,
        "pipeline": pipeline,
        "graph": graph,
    }
    ctx.request_context.lifespan_context = state
    return ctx


@pytest.fixture()
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed.return_value = _fake_embedding()
    embedder.embed_query = embedder.embed
    embedder.embed_document = embedder.embed
    return embedder


@pytest.fixture()
def mock_vector_store():
    store = AsyncMock()
    store.search.return_value = []
    store.get_collection_info.return_value = {
        "indexed_vectors_count": 42,
        "status": "green",
    }
    return store


@pytest.fixture()
def mock_metadata_store():
    store = AsyncMock()
    store.search_fulltext.return_value = []
    store.get_source_stats.return_value = {"claude_code": 10, "chatgpt": 5}
    store.get_total_count.return_value = 15
    store.update_access.return_value = None
    store.get_memory.return_value = None  # Default: no memory lookup for decay
    store._db = None
    return store


@pytest.fixture()
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.ingest_single.return_value = _make_memory()
    return pipeline


@pytest.fixture()
def mock_graph():
    graph = MagicMock()
    graph.node_count = 0
    return graph


@pytest.fixture()
def ctx(mock_metadata_store, mock_vector_store, mock_embedder, mock_pipeline, mock_graph):
    return _mock_ctx(
        mock_metadata_store, mock_vector_store, mock_embedder, mock_pipeline, mock_graph
    )


# --- memgentic_remember ---


async def test_memgentic_remember_creates_memory(ctx, mock_pipeline):
    """memgentic_remember should call pipeline.ingest_single and return confirmation."""
    params = RememberInput(
        content="Python uses indentation for blocks",
        content_type="fact",
        topics=["python"],
        source="claude_code",
    )

    result = await memgentic_remember(params, ctx)

    assert "Remembered!" in result
    assert "mem-001" in result
    mock_pipeline.ingest_single.assert_awaited_once()
    call_kwargs = mock_pipeline.ingest_single.call_args
    assert call_kwargs.kwargs["content"] == "Python uses indentation for blocks"
    assert call_kwargs.kwargs["content_type"] == ContentType.FACT
    assert call_kwargs.kwargs["platform"] == Platform.CLAUDE_CODE


async def test_memgentic_remember_with_unknown_content_type(ctx, mock_pipeline):
    """Invalid content_type should fall back to FACT."""
    params = RememberInput(
        content="Some content to remember",
        content_type="invalid_type_xyz",
    )

    result = await memgentic_remember(params, ctx)

    assert "Remembered!" in result
    call_kwargs = mock_pipeline.ingest_single.call_args
    assert call_kwargs.kwargs["content_type"] == ContentType.FACT


async def test_memgentic_remember_error_handling(ctx, mock_pipeline):
    """On pipeline error, return friendly error message, not traceback."""
    mock_pipeline.ingest_single.side_effect = RuntimeError("Embedding service down")

    params = RememberInput(content="Something to remember")

    result = await memgentic_remember(params, ctx)

    assert "Error storing memory" in result
    assert "Embedding service down" in result


# --- memgentic_recall ---


async def test_memgentic_recall_returns_formatted_results(ctx, mock_embedder, mock_vector_store):
    """memgentic_recall should return markdown-formatted results."""
    mock_vector_store.search.return_value = [
        {
            "id": "mem-1",
            "score": 0.85,
            "payload": {
                "content": "Qdrant is used for vectors",
                "platform": "claude_code",
                "content_type": "decision",
                "topics": ["qdrant"],
                "created_at": "2026-03-25",
            },
        },
    ]

    params = RecallInput(query="vector database choice")

    result = await memgentic_recall(params, ctx)

    assert "Memory Recall" in result
    assert "1 relevant memories" in result


async def test_memgentic_recall_no_results(ctx):
    """memgentic_recall with no matches should return a friendly message."""
    params = RecallInput(query="completely unknown topic xyz")

    result = await memgentic_recall(params, ctx)

    assert "No memories found" in result


async def test_memgentic_recall_error_handling(ctx, mock_embedder):
    """On error, return friendly error message."""
    mock_embedder.embed.side_effect = RuntimeError("Connection refused")

    params = RecallInput(query="test query")

    result = await memgentic_recall(params, ctx)

    assert "Error searching memories" in result


# --- memgentic_sources ---


async def test_memgentic_sources_returns_stats(ctx):
    """memgentic_sources should return a markdown table with source counts."""
    result = await memgentic_sources(ctx)

    assert "Memory Sources" in result
    assert "Total memories" in result
    assert "15" in result
    assert "claude_code" in result
    assert "chatgpt" in result


async def test_memgentic_sources_empty(ctx, mock_metadata_store):
    """When no memories exist, show a helpful message."""
    mock_metadata_store.get_source_stats.return_value = {}
    mock_metadata_store.get_total_count.return_value = 0

    result = await memgentic_sources(ctx)

    assert "No memories stored yet" in result


# --- memgentic_stats ---


async def test_memgentic_stats_returns_statistics(ctx):
    """memgentic_stats should return comprehensive stats."""
    result = await memgentic_stats(ctx)

    assert "Memgentic Statistics" in result
    assert "Total memories" in result
    assert "15" in result
    assert "Vector count" in result
    assert "42" in result
    assert "By Source" in result
    assert "claude_code" in result


async def test_memgentic_stats_error_handling(ctx, mock_metadata_store):
    """On error, return friendly error message."""
    mock_metadata_store.get_source_stats.side_effect = RuntimeError("DB locked")

    result = await memgentic_stats(ctx)

    assert "Error retrieving stats" in result


# --- memgentic_search ---


async def test_memgentic_search_returns_results(ctx, mock_metadata_store):
    """memgentic_search should return keyword search results."""
    mock_metadata_store.search_fulltext.return_value = [
        _make_memory("mem-kw-1", "Python async patterns"),
        _make_memory("mem-kw-2", "Python decorators guide"),
    ]

    params = SearchInput(query="Python")

    result = await memgentic_search(params, ctx)

    assert "Keyword Search" in result
    assert "2 matches" in result
    assert "Python async patterns" in result
    assert "Python decorators guide" in result


async def test_memgentic_search_no_results(ctx):
    """memgentic_search with no matches returns friendly message."""
    params = SearchInput(query="nonexistent")

    result = await memgentic_search(params, ctx)

    assert "No memories found matching keywords" in result


async def test_memgentic_search_error_handling(ctx, mock_metadata_store):
    """On error, return friendly error message."""
    mock_metadata_store.search_fulltext.side_effect = RuntimeError("FTS5 error")

    params = SearchInput(query="test")

    result = await memgentic_search(params, ctx)

    assert "Error searching memories" in result


# --- memgentic_forget ---


async def test_memgentic_forget_success(ctx, mock_metadata_store, mock_vector_store):
    """memgentic_forget should archive a memory and remove it from vector store."""
    mem = _make_memory("mem-forget-1", "Old memory to forget")
    mock_metadata_store.get_memory.return_value = mem

    params = ForgetInput(memory_id="mem-forget-1")
    result = await memgentic_forget(params, ctx)

    assert "archived successfully" in result
    assert "mem-forget-1" in result
    assert mem.status == MemoryStatus.ARCHIVED
    mock_metadata_store.save_memory.assert_awaited_once_with(mem)
    mock_vector_store.delete_memory.assert_awaited_once_with("mem-forget-1")


async def test_memgentic_forget_not_found(ctx, mock_metadata_store):
    """memgentic_forget should return not-found message for unknown memory ID."""
    mock_metadata_store.get_memory.return_value = None

    params = ForgetInput(memory_id="mem-nonexistent")
    result = await memgentic_forget(params, ctx)

    assert "not found" in result
    assert "mem-nonexistent" in result


async def test_memgentic_forget_error_handling(ctx, mock_metadata_store):
    """On error, return friendly error message."""
    mock_metadata_store.get_memory.side_effect = RuntimeError("DB error")

    params = ForgetInput(memory_id="mem-err")
    result = await memgentic_forget(params, ctx)

    assert "Error archiving memory" in result


# --- memgentic_export ---


async def test_memgentic_export_all(ctx, mock_metadata_store):
    """memgentic_export should return JSON array of all memories."""
    import json

    mock_metadata_store.get_memories_by_filter.return_value = [
        _make_memory("mem-exp-1", "First export memory"),
        _make_memory("mem-exp-2", "Second export memory"),
    ]

    params = ExportInput()
    result = await memgentic_export(params, ctx)

    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["id"] == "mem-exp-1"
    assert data[1]["id"] == "mem-exp-2"
    assert data[0]["content"] == "First export memory"
    assert data[0]["platform"] == "claude_code"
    assert data[0]["content_type"] == "fact"


async def test_memgentic_export_filtered_by_source(ctx, mock_metadata_store):
    """memgentic_export with source filter should pass it to metadata store."""
    import json

    mock_metadata_store.get_memories_by_filter.return_value = [
        _make_memory("mem-exp-3", "ChatGPT memory"),
    ]

    params = ExportInput(source="chatgpt")
    result = await memgentic_export(params, ctx)

    data = json.loads(result)
    assert len(data) == 1
    # Verify SessionConfig was passed with include_sources
    call_kwargs = mock_metadata_store.get_memories_by_filter.call_args
    session_config = call_kwargs.kwargs["session_config"]
    assert session_config.include_sources == [Platform.CHATGPT]


async def test_memgentic_export_empty(ctx, mock_metadata_store):
    """memgentic_export with no memories should return empty JSON array."""
    import json

    mock_metadata_store.get_memories_by_filter.return_value = []

    params = ExportInput()
    result = await memgentic_export(params, ctx)

    data = json.loads(result)
    assert data == []


async def test_memgentic_export_error_handling(ctx, mock_metadata_store):
    """On error, return friendly error message."""
    mock_metadata_store.get_memories_by_filter.side_effect = RuntimeError("DB locked")

    params = ExportInput()
    result = await memgentic_export(params, ctx)

    assert "Error exporting memories" in result


# --- memgentic_briefing ---


async def test_memgentic_briefing_with_memories(ctx, mock_metadata_store):
    """memgentic_briefing should return formatted briefing with platform counts and topics."""
    mem1 = _make_memory("mem-b-1", "Python async patterns are useful")
    mem2 = _make_memory("mem-b-2", "React hooks best practices")
    mem2.source.platform = Platform.CHATGPT
    mem2.topics = ["react", "frontend"]

    mock_metadata_store.get_memories_since.return_value = [mem1, mem2]

    params = BriefingInput(since_hours=24)
    result = await memgentic_briefing(params, ctx)

    assert "Briefing" in result
    assert "2 new memories" in result
    assert "2 platforms" in result
    assert "Latest" in result


async def test_memgentic_briefing_empty(ctx, mock_metadata_store):
    """memgentic_briefing with no recent memories should say so."""
    mock_metadata_store.get_memories_since.return_value = []

    params = BriefingInput(since_hours=24)
    result = await memgentic_briefing(params, ctx)

    assert "No new memories" in result
    assert "24" in result


async def test_memgentic_briefing_error_handling(ctx, mock_metadata_store):
    """On error, return friendly error message."""
    mock_metadata_store.get_memories_since.side_effect = RuntimeError("Connection error")

    params = BriefingInput(since_hours=48)
    result = await memgentic_briefing(params, ctx)

    assert "Error generating briefing" in result


async def test_memgentic_briefing_shows_top_topics(ctx, mock_metadata_store):
    """memgentic_briefing should show top topics from recent memories."""
    mem1 = _make_memory("mem-bt-1", "Topic test 1")
    mem1.topics = ["python", "async"]
    mem2 = _make_memory("mem-bt-2", "Topic test 2")
    mem2.topics = ["python", "testing"]

    mock_metadata_store.get_memories_since.return_value = [mem1, mem2]

    params = BriefingInput(since_hours=12)
    result = await memgentic_briefing(params, ctx)

    assert "Top topics" in result
    assert "python" in result


# --- memgentic_recent ---


async def test_memgentic_recent_returns_memories(ctx, mock_metadata_store):
    """memgentic_recent should return formatted recent memories."""
    mock_metadata_store.get_memories_by_filter.return_value = [
        _make_memory("mem-r-1", "Recent memory 1"),
        _make_memory("mem-r-2", "Recent memory 2"),
    ]

    params = RecentInput(limit=5)
    result = await memgentic_recent(params, ctx)

    assert "Recent Memories" in result
    assert "Recent memory 1" in result
    assert "Recent memory 2" in result


async def test_memgentic_recent_no_results(ctx, mock_metadata_store):
    """memgentic_recent with no memories should return friendly message."""
    mock_metadata_store.get_memories_by_filter.return_value = []

    params = RecentInput()
    result = await memgentic_recent(params, ctx)

    assert "No recent memories found" in result


async def test_memgentic_recent_with_source_filter(ctx, mock_metadata_store):
    """memgentic_recent with source filter should pass it through."""
    mock_metadata_store.get_memories_by_filter.return_value = [
        _make_memory("mem-rs-1", "Claude memory"),
    ]

    params = RecentInput(source="claude_code")
    result = await memgentic_recent(params, ctx)

    assert "Recent Memories" in result
    call_kwargs = mock_metadata_store.get_memories_by_filter.call_args
    session_config = call_kwargs.kwargs["session_config"]
    assert session_config.include_sources == [Platform.CLAUDE_CODE]


async def test_memgentic_recent_with_content_type_filter(ctx, mock_metadata_store):
    """memgentic_recent with content_type filter should pass ContentType enum."""
    mock_metadata_store.get_memories_by_filter.return_value = [
        _make_memory("mem-rct-1", "A decision we made"),
    ]

    params = RecentInput(content_type="decision")
    result = await memgentic_recent(params, ctx)

    assert "Recent Memories" in result
    call_kwargs = mock_metadata_store.get_memories_by_filter.call_args
    assert call_kwargs.kwargs["content_type"] == ContentType.DECISION


async def test_memgentic_recent_error_handling(ctx, mock_metadata_store):
    """On error, return friendly error message."""
    mock_metadata_store.get_memories_by_filter.side_effect = RuntimeError("DB error")

    params = RecentInput()
    result = await memgentic_recent(params, ctx)

    assert "Error retrieving recent memories" in result


# --- memgentic_handoff ---


async def test_memgentic_handoff_groups_recent_sessions(ctx, mock_metadata_store):
    """memgentic_handoff should render source-backed continuation bundles."""
    mem1 = _make_memory("mem-h-1", "Human: fix the auth redirect\n\nAssistant: found login bug")
    mem1.content_type = ContentType.RAW_EXCHANGE
    mem1.source.session_id = "claude-session-1"
    mem1.source.session_title = "Auth redirect debugging"
    mem1.created_at = datetime(2026, 4, 30, 15, 30, tzinfo=UTC)

    mem2 = _make_memory("mem-h-2", "Decision: keep API-key auth local-first for now")
    mem2.source.session_id = "claude-session-1"
    mem2.source.session_title = "Auth redirect debugging"
    mem2.created_at = datetime(2026, 4, 30, 15, 25, tzinfo=UTC)

    mock_metadata_store.get_recent_session_handoffs.return_value = [
        {
            "platform": "claude_code",
            "session_id": "claude-session-1",
            "session_title": "Auth redirect debugging",
            "file_path": "/tmp/session.jsonl",
            "last_activity": datetime(2026, 4, 30, 15, 30, tzinfo=UTC),
            "memories": [mem1, mem2],
            "memory_count": 2,
            "topics": ["auth", "dashboard"],
            "entities": ["Memgentic"],
        }
    ]

    result = await memgentic_handoff(HandoffInput(current_source="codex_cli"), ctx)

    assert "Cross-Tool Handoff" in result
    assert "claude_code" in result
    assert "Auth redirect debugging" in result
    assert "mem-h-1" in result
    assert "Continuation Instructions" in result
    mock_metadata_store.get_recent_session_handoffs.assert_awaited_once()


async def test_memgentic_handoff_empty(ctx, mock_metadata_store):
    """Empty handoff should return a useful no-context message."""
    mock_metadata_store.get_recent_session_handoffs.return_value = []

    result = await memgentic_handoff(HandoffInput(since_hours=24), ctx)

    assert "No cross-tool handoff context found" in result
    assert "24 hours" in result


async def test_memgentic_handoff_filters_current_source(ctx, mock_metadata_store):
    """When requested, current_source should be excluded from handoff candidates."""
    mock_metadata_store.get_recent_session_handoffs.return_value = []

    await memgentic_handoff(
        HandoffInput(current_source="codex_cli", include_current_source=False),
        ctx,
    )

    call_kwargs = mock_metadata_store.get_recent_session_handoffs.call_args.kwargs
    session_config = call_kwargs["session_config"]
    assert session_config.exclude_sources == [Platform.CODEX_CLI]


# --- memgentic_context ---


async def test_memgentic_context_shows_loaded_handoff_memories(ctx, mock_metadata_store):
    """Context ledger should show memories returned to this MCP session."""
    await memgentic_context(ContextInput(action="clear"), ctx)

    mem = _make_memory("mem-ctx-1", "Continue the dashboard auth fix")
    mem.source.session_id = "session-ctx"
    mock_metadata_store.get_recent_session_handoffs.return_value = [
        {
            "platform": "claude_code",
            "session_id": "session-ctx",
            "session_title": "Dashboard auth",
            "file_path": None,
            "last_activity": mem.created_at,
            "memories": [mem],
            "memory_count": 1,
            "topics": ["auth"],
            "entities": [],
        }
    ]

    await memgentic_handoff(HandoffInput(), ctx)
    result = await memgentic_context(ContextInput(), ctx)

    assert result["loaded_count"] == 1
    assert result["memories"][0]["id"] == "mem-ctx-1"
    assert result["memories"][0]["returned_by"] == "memgentic_handoff"


async def test_memgentic_context_clear(ctx):
    """Context ledger can be cleared without deleting persistent memories."""
    result = await memgentic_context(ContextInput(action="clear"), ctx)

    assert "cleared" in result


# --- memgentic_inventory ---


async def test_memgentic_inventory_manifest(ctx, mock_metadata_store):
    """Inventory manifest should expose exact stored memory IDs and metadata."""
    mem = _make_memory("mem-inv-1", "Inventory test memory")
    mem.source.session_id = "session-inv"
    mock_metadata_store.get_filtered_count.return_value = 1
    mock_metadata_store.get_memories_by_filter.return_value = [mem]

    result = await memgentic_inventory(InventoryInput(detail="manifest"), ctx)

    assert result["total_matching_active_memories"] == 1
    assert result["memories"][0]["id"] == "mem-inv-1"
    assert result["memories"][0]["session_id"] == "session-inv"


async def test_memgentic_inventory_filters_source(ctx, mock_metadata_store):
    """Inventory source filter should be passed as a SessionConfig."""
    mock_metadata_store.get_filtered_count.return_value = 0
    mock_metadata_store.get_memories_by_filter.return_value = []

    await memgentic_inventory(InventoryInput(source="claude_code"), ctx)

    call_kwargs = mock_metadata_store.get_memories_by_filter.call_args.kwargs
    assert call_kwargs["session_config"].include_sources == [Platform.CLAUDE_CODE]


async def test_memgentic_inventory_uses_public_count_helpers(ctx, mock_metadata_store):
    """Inventory summary should call public count helpers, not raw _db."""
    mock_metadata_store.get_filtered_count.return_value = 3
    mock_metadata_store.get_memories_by_filter.return_value = []
    mock_metadata_store.get_content_type_counts.return_value = {"fact": 2, "decision": 1}
    mock_metadata_store.get_capture_profile_counts.return_value = {"enriched": 3}

    result = await memgentic_inventory(InventoryInput(detail="summary"), ctx)

    assert result["content_types"] == {"fact": 2, "decision": 1}
    assert result["capture_profiles"] == {"enriched": 3}
    mock_metadata_store.get_content_type_counts.assert_awaited_once()
    mock_metadata_store.get_capture_profile_counts.assert_awaited_once()


async def test_memgentic_inventory_unknown_source_warns(ctx, mock_metadata_store):
    """Unknown source string should soft-fail with a warning, not raise."""
    mock_metadata_store.get_filtered_count.return_value = 0
    mock_metadata_store.get_memories_by_filter.return_value = []
    mock_metadata_store.get_content_type_counts.return_value = {}
    mock_metadata_store.get_capture_profile_counts.return_value = {}

    result = await memgentic_inventory(InventoryInput(source="not_a_tool", detail="summary"), ctx)

    assert "warnings" in result
    assert any("not_a_tool" in w for w in result["warnings"])


async def test_memgentic_handoff_unknown_current_source_warns(ctx, mock_metadata_store):
    """Unknown current_source should warn instead of raising."""
    mock_metadata_store.get_recent_session_handoffs.return_value = [
        {
            "platform": "claude_code",
            "session_id": "s1",
            "session_title": "t",
            "file_path": None,
            "last_activity": datetime(2026, 4, 30, tzinfo=UTC),
            "memories": [],
            "memory_count": 0,
            "topics": [],
            "entities": [],
        }
    ]

    result = await memgentic_handoff(
        HandoffInput(current_source="not_a_tool", include_current_source=False),
        ctx,
    )

    assert "Unknown current_source" in result
    assert "not_a_tool" in result


# --- memgentic_configure_session ---


async def test_memgentic_configure_session_include_sources(ctx):
    """memgentic_configure_session should store include_sources in session config."""
    params = ConfigureSessionInput(include_sources=["claude_code", "chatgpt"])
    result = await memgentic_configure_session(params, ctx)

    assert "Session Configured" in result
    assert "claude_code" in result
    assert "chatgpt" in result
    assert "Include" in result

    # Verify it was stored in _session_configs
    entry = _session_configs.get(_get_session_id(ctx))
    assert entry is not None
    config = entry[0]
    assert config.include_sources == [Platform.CLAUDE_CODE, Platform.CHATGPT]


async def test_memgentic_configure_session_exclude_sources(ctx):
    """memgentic_configure_session should store exclude_sources in session config."""
    params = ConfigureSessionInput(exclude_sources=["codex_cli"])
    result = await memgentic_configure_session(params, ctx)

    assert "Session Configured" in result
    assert "Exclude" in result
    assert "codex_cli" in result

    entry = _session_configs.get(_get_session_id(ctx))
    assert entry is not None
    config = entry[0]
    assert config.exclude_sources == [Platform.CODEX_CLI]


async def test_memgentic_configure_session_content_types(ctx):
    """memgentic_configure_session should store content type filters."""
    params = ConfigureSessionInput(content_types=["decision", "code_snippet"])
    result = await memgentic_configure_session(params, ctx)

    assert "Session Configured" in result
    assert "Types" in result
    assert "decision" in result

    entry = _session_configs.get(_get_session_id(ctx))
    assert entry is not None
    config = entry[0]
    assert config.include_content_types == [ContentType.DECISION, ContentType.CODE_SNIPPET]


async def test_memgentic_configure_session_min_confidence(ctx):
    """memgentic_configure_session should store min_confidence threshold."""
    params = ConfigureSessionInput(min_confidence=0.8)
    result = await memgentic_configure_session(params, ctx)

    assert "Session Configured" in result
    assert "0.8" in result

    entry = _session_configs.get(_get_session_id(ctx))
    assert entry is not None
    config = entry[0]
    assert config.min_confidence == 0.8


async def test_memgentic_configure_session_error_handling(ctx):
    """On invalid platform, return friendly error message."""
    params = ConfigureSessionInput(include_sources=["nonexistent_platform"])
    result = await memgentic_configure_session(params, ctx)

    assert "Error configuring session" in result


# --- memgentic_stats (additional) ---


async def test_memgentic_stats_with_session_config(ctx):
    """memgentic_stats should show current session config."""
    # First set a session config
    from memgentic.models import SessionConfig

    sid = _get_session_id(ctx)
    _set_session_config(sid, SessionConfig(include_sources=[Platform.CLAUDE_CODE]))

    result = await memgentic_stats(ctx)

    assert "Session Config" in result
    assert "claude_code" in result

    # Clean up
    _session_configs.pop(sid, None)
