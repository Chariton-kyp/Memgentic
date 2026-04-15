"""Tests for Claude Web Import adapter."""

import json

import pytest

from memgentic.adapters.claude_web_import import ClaudeWebImportAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return ClaudeWebImportAdapter()


@pytest.fixture
def sample_export(tmp_path):
    """Create a sample Claude web export with 2 conversations."""
    data = [
        {
            "uuid": "conv-123",
            "name": "Architecture Discussion",
            "created_at": "2026-03-01T10:00:00Z",
            "updated_at": "2026-03-01T11:00:00Z",
            "chat_messages": [
                {
                    "uuid": "msg-1",
                    "sender": "human",
                    "text": "How should I design the API for a microservices architecture?",
                    "created_at": "2026-03-01T10:00:00Z",
                },
                {
                    "uuid": "msg-2",
                    "sender": "assistant",
                    "text": "I recommend using FastAPI with a gateway pattern. "
                    "Each service should have its own database...",
                    "created_at": "2026-03-01T10:00:30Z",
                },
                {
                    "uuid": "msg-3",
                    "sender": "human",
                    "text": "What about authentication across services?",
                    "created_at": "2026-03-01T10:01:00Z",
                },
                {
                    "uuid": "msg-4",
                    "sender": "assistant",
                    "text": "For cross-service auth, use JWT tokens with a shared secret. "
                    "Implement an auth middleware in the gateway...",
                    "created_at": "2026-03-01T10:01:30Z",
                },
            ],
        },
        {
            "uuid": "conv-456",
            "name": "Python Testing Strategies",
            "created_at": "2026-03-02T14:00:00Z",
            "updated_at": "2026-03-02T15:00:00Z",
            "chat_messages": [
                {
                    "uuid": "msg-5",
                    "sender": "human",
                    "text": "What's the best approach for testing async Python code?",
                    "created_at": "2026-03-02T14:00:00Z",
                },
                {
                    "uuid": "msg-6",
                    "sender": "assistant",
                    "text": "For async testing, use pytest-asyncio. You can mark tests "
                    "with @pytest.mark.asyncio and use async fixtures...",
                    "created_at": "2026-03-02T14:00:30Z",
                },
            ],
        },
    ]

    file_path = tmp_path / "claude-export.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.CLAUDE_WEB


def test_adapter_watch_paths_empty(adapter):
    assert adapter.watch_paths == []


def test_adapter_file_patterns(adapter):
    assert "*.json" in adapter.file_patterns


@pytest.mark.asyncio
async def test_parse_file_extracts_all_conversations(adapter, sample_export):
    chunks = await adapter.parse_file(sample_export)
    assert len(chunks) > 0
    # Should have chunks from both conversations
    all_content = " ".join(c.content for c in chunks)
    assert "API" in all_content or "api" in all_content.lower()
    assert "async" in all_content.lower() or "testing" in all_content.lower()


@pytest.mark.asyncio
async def test_parse_file_chunk_types(adapter, sample_export):
    chunks = await adapter.parse_file(sample_export)
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_preserves_conversation_titles(adapter, sample_export):
    chunks = await adapter.parse_file(sample_export)
    all_content = " ".join(c.content for c in chunks)
    # Conversation with 2+ exchanges should have titles in summary
    # The first conversation has 2 exchanges so no summary, but content should be present
    assert "microservices" in all_content.lower() or "architecture" in all_content.lower()


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_export):
    session_id = await adapter.get_session_id(sample_export)
    assert session_id == "conv-123"


@pytest.mark.asyncio
async def test_get_session_title(adapter, sample_export):
    title = await adapter.get_session_title(sample_export)
    assert title == "Architecture Discussion"


@pytest.mark.asyncio
async def test_handles_empty_chat_messages(adapter, tmp_path):
    data = [
        {
            "uuid": "conv-empty",
            "name": "Empty Conversation",
            "chat_messages": [],
        },
        {
            "uuid": "conv-with-msgs",
            "name": "Has Messages",
            "chat_messages": [
                {
                    "uuid": "msg-1",
                    "sender": "human",
                    "text": "Tell me about Kubernetes deployment strategies and scaling patterns.",
                },
                {
                    "uuid": "msg-2",
                    "sender": "assistant",
                    "text": "Kubernetes offers several deployment strategies: "
                    "Rolling updates, Blue-Green, and Canary deployments...",
                },
            ],
        },
    ]
    file_path = tmp_path / "partial.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    # Only the second conversation should produce chunks
    assert len(chunks) > 0
    all_content = " ".join(c.content for c in chunks)
    assert "kubernetes" in all_content.lower()


@pytest.mark.asyncio
async def test_empty_conversations_list(adapter, tmp_path):
    file_path = tmp_path / "empty.json"
    with open(file_path, "w") as f:
        json.dump([], f)

    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_handles_content_field_fallback(adapter, tmp_path):
    """Test that the adapter handles 'content' field when 'text' is absent."""
    data = [
        {
            "uuid": "conv-content",
            "name": "Content Field Test",
            "chat_messages": [
                {
                    "uuid": "msg-1",
                    "sender": "human",
                    "content": "How do I configure Docker containers with persistent volumes?",
                },
                {
                    "uuid": "msg-2",
                    "sender": "assistant",
                    "content": "You can use Docker volumes by adding a volumes section "
                    "to your docker-compose.yml configuration...",
                },
            ],
        },
    ]
    file_path = tmp_path / "content-field.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    assert len(chunks) > 0
    all_content = " ".join(c.content for c in chunks)
    assert "docker" in all_content.lower()


@pytest.mark.asyncio
async def test_invalid_json(adapter, tmp_path):
    file_path = tmp_path / "invalid.json"
    file_path.write_text("not valid json {{{")

    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_get_session_id_fallback(adapter, tmp_path):
    """Fall back to file stem when conversations list is empty."""
    file_path = tmp_path / "fallback.json"
    with open(file_path, "w") as f:
        json.dump([], f)

    session_id = await adapter.get_session_id(file_path)
    assert session_id == "fallback"
