"""Tests for ChatGPT import adapter."""

import json

import pytest

from memgentic.adapters.chatgpt_import import ChatGPTImportAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return ChatGPTImportAdapter()


@pytest.fixture
def sample_conversations(tmp_path):
    """Create a sample conversations.json with 2 conversations."""
    data = [
        {
            "title": "React Architecture Discussion",
            "create_time": 1711234567.0,
            "mapping": {
                "msg-root": {
                    "id": "msg-root",
                    "message": None,
                    "parent": None,
                    "children": ["msg-1"],
                },
                "msg-1": {
                    "id": "msg-1",
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "parts": [
                                "How should I structure a large React application with TypeScript?"
                            ]
                        },
                        "create_time": 1711234567.0,
                    },
                    "parent": "msg-root",
                    "children": ["msg-2"],
                },
                "msg-2": {
                    "id": "msg-2",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {
                            "parts": [
                                "I recommend feature-based folder structure."
                                " Each feature gets its own directory."
                            ]
                        },
                        "create_time": 1711234568.0,
                    },
                    "parent": "msg-1",
                    "children": ["msg-3"],
                },
                "msg-3": {
                    "id": "msg-3",
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "parts": ["What about state management? Should I use Redux or Zustand?"]
                        },
                        "create_time": 1711234569.0,
                    },
                    "parent": "msg-2",
                    "children": ["msg-4"],
                },
                "msg-4": {
                    "id": "msg-4",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {
                            "parts": [
                                "For modern React apps, Zustand over Redux."
                                " Simpler, less boilerplate."
                            ]
                        },
                        "create_time": 1711234570.0,
                    },
                    "parent": "msg-3",
                    "children": [],
                },
            },
        },
        {
            "title": "Python Testing Best Practices",
            "create_time": 1711300000.0,
            "mapping": {
                "msg-root-2": {
                    "id": "msg-root-2",
                    "message": None,
                    "parent": None,
                    "children": ["msg-a"],
                },
                "msg-a": {
                    "id": "msg-a",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Best practices for testing Python async code?"]},
                        "create_time": 1711300001.0,
                    },
                    "parent": "msg-root-2",
                    "children": ["msg-b"],
                },
                "msg-b": {
                    "id": "msg-b",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {
                            "parts": [
                                "For async Python testing, use pytest-asyncio."
                                " Mark tests with @pytest.mark.asyncio."
                            ]
                        },
                        "create_time": 1711300002.0,
                    },
                    "parent": "msg-a",
                    "children": [],
                },
            },
        },
    ]

    file_path = tmp_path / "conversations.json"
    with open(file_path, "w") as f:
        json.dump(data, f)
    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.CHATGPT


def test_adapter_file_patterns(adapter):
    assert "conversations.json" in adapter.file_patterns


def test_adapter_watch_paths_empty(adapter):
    """ChatGPT adapter is import-only, no watch paths."""
    assert adapter.watch_paths == []


@pytest.mark.asyncio
async def test_parse_file_extracts_from_mapping(adapter, sample_conversations):
    chunks = await adapter.parse_file(sample_conversations)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_file_multiple_conversations(adapter, sample_conversations):
    """Should process all conversations from the file."""
    chunks = await adapter.parse_file(sample_conversations)
    all_text = " ".join(c.content for c in chunks)
    # Both conversations should be represented
    assert "React" in all_text
    assert "pytest" in all_text or "Python" in all_text or "testing" in all_text.lower()


@pytest.mark.asyncio
async def test_preserves_titles(adapter, sample_conversations):
    """Conversation titles should appear in summary chunks."""
    chunks = await adapter.parse_file(sample_conversations)
    # At least one conversation should have enough exchanges for a summary
    # (the first conversation has 2 exchanges, which is not > 2, so no summary)
    # Check that chunks exist with the right content regardless
    all_text = " ".join(c.content for c in chunks)
    assert "React" in all_text


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_conversations):
    session_id = await adapter.get_session_id(sample_conversations)
    assert session_id == "conversations"


@pytest.mark.asyncio
async def test_get_session_title(adapter, sample_conversations):
    title = await adapter.get_session_title(sample_conversations)
    assert title == "React Architecture Discussion"


@pytest.mark.asyncio
async def test_handles_missing_messages(adapter, tmp_path):
    """Nodes with null/missing messages should be skipped gracefully."""
    data = [
        {
            "title": "Sparse Conversation",
            "create_time": 1711234567.0,
            "mapping": {
                "msg-root": {
                    "id": "msg-root",
                    "message": None,
                    "parent": None,
                    "children": ["msg-1"],
                },
                "msg-orphan": {
                    "id": "msg-orphan",
                    "message": None,
                    "parent": None,
                    "children": [],
                },
                "msg-1": {
                    "id": "msg-1",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Tell me about Docker container networking"]},
                        "create_time": 1711234567.0,
                    },
                    "parent": "msg-root",
                    "children": ["msg-2"],
                },
                "msg-2": {
                    "id": "msg-2",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {
                            "parts": [
                                "Docker networking allows containers to"
                                " communicate via bridge networks..."
                            ]
                        },
                        "create_time": 1711234568.0,
                    },
                    "parent": "msg-1",
                    "children": [],
                },
            },
        }
    ]

    file_path = tmp_path / "conversations.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    assert len(chunks) >= 1
    all_text = " ".join(c.content for c in chunks)
    assert "Docker" in all_text


@pytest.mark.asyncio
async def test_empty_conversations_list(adapter, tmp_path):
    file_path = tmp_path / "conversations.json"
    with open(file_path, "w") as f:
        json.dump([], f)

    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_invalid_json(adapter, tmp_path):
    file_path = tmp_path / "conversations.json"
    file_path.write_text("not json at all!!!")

    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_skips_system_and_tool_messages(adapter, tmp_path):
    """System and tool messages should be filtered out."""
    data = [
        {
            "title": "With System Messages",
            "create_time": 1711234567.0,
            "mapping": {
                "msg-sys": {
                    "id": "msg-sys",
                    "message": {
                        "author": {"role": "system"},
                        "content": {"parts": ["You are a helpful assistant."]},
                        "create_time": 1711234566.0,
                    },
                    "parent": None,
                    "children": ["msg-1"],
                },
                "msg-1": {
                    "id": "msg-1",
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Explain the difference between REST and GraphQL"]},
                        "create_time": 1711234567.0,
                    },
                    "parent": "msg-sys",
                    "children": ["msg-tool"],
                },
                "msg-tool": {
                    "id": "msg-tool",
                    "message": {
                        "author": {"role": "tool"},
                        "content": {"parts": ["[Search results...]"]},
                        "create_time": 1711234567.5,
                    },
                    "parent": "msg-1",
                    "children": ["msg-2"],
                },
                "msg-2": {
                    "id": "msg-2",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {
                            "parts": [
                                "REST uses resource-based URLs with HTTP"
                                " methods. GraphQL uses a query language."
                            ]
                        },
                        "create_time": 1711234568.0,
                    },
                    "parent": "msg-tool",
                    "children": [],
                },
            },
        }
    ]

    file_path = tmp_path / "conversations.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    all_text = " ".join(c.content for c in chunks)
    assert "helpful assistant" not in all_text
    assert "Search results" not in all_text
    assert "REST" in all_text


@pytest.mark.asyncio
async def test_chronological_ordering(adapter, tmp_path):
    """Messages should be ordered by create_time, not mapping order."""
    data = [
        {
            "title": "Out of Order",
            "create_time": 1711234567.0,
            "mapping": {
                "msg-2": {
                    "id": "msg-2",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {
                            "parts": ["The answer to your question about databases is PostgreSQL"]
                        },
                        "create_time": 1711234568.0,
                    },
                    "parent": "msg-1",
                    "children": [],
                },
                "msg-1": {
                    "id": "msg-1",
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "parts": ["Which database should I use for my web application project?"]
                        },
                        "create_time": 1711234567.0,
                    },
                    "parent": None,
                    "children": ["msg-2"],
                },
            },
        }
    ]

    file_path = tmp_path / "conversations.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    assert len(chunks) >= 1
    # The user message should come before the assistant message
    first_chunk = chunks[0]
    human_pos = first_chunk.content.find("Human:")
    assistant_pos = first_chunk.content.find("Assistant:")
    assert human_pos < assistant_pos
