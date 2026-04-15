"""Tests for Copilot CLI adapter."""

import json

import pytest

from memgentic.adapters.copilot_cli import CopilotCliAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return CopilotCliAdapter()


@pytest.fixture
def sample_session(tmp_path):
    """Create a sample Copilot CLI JSON session file."""
    data = {
        "session_id": "abc123",
        "messages": [
            {"role": "user", "content": "How do I use git rebase?"},
            {
                "role": "assistant",
                "content": "To rebase, you can use `git rebase <branch>`. "
                "This replays your commits on top of the target branch...",
            },
            {"role": "user", "content": "What about interactive rebase?"},
            {
                "role": "assistant",
                "content": "For interactive rebase, use `git rebase -i HEAD~N` "
                "where N is the number of commits to edit...",
            },
        ],
    }

    file_path = tmp_path / "session-abc123.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    return file_path


@pytest.fixture
def sample_session_list_content(tmp_path):
    """Create a session with content as list of parts."""
    data = {
        "session_id": "list-parts",
        "messages": [
            {"role": "user", "content": "Write a Python function to sort a list"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Here's a sorting function:"},
                    {
                        "type": "text",
                        "text": "```python\ndef sort_list(items):\n    return sorted(items)\n```",
                    },
                ],
            },
        ],
    }

    file_path = tmp_path / "session-list.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.COPILOT_CLI


def test_adapter_file_patterns(adapter):
    assert "*.json" in adapter.file_patterns


def test_adapter_watch_paths(adapter):
    assert len(adapter.watch_paths) == 1
    assert "copilot" in str(adapter.watch_paths[0])


@pytest.mark.asyncio
async def test_parse_file(adapter, sample_session):
    chunks = await adapter.parse_file(sample_session)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_file_extracts_exchanges(adapter, sample_session):
    chunks = await adapter.parse_file(sample_session)
    # Should have 2 exchange chunks (2 user-assistant pairs)
    assert len(chunks) == 2
    assert "Human:" in chunks[0].content
    assert "Assistant:" in chunks[0].content
    assert "git rebase" in chunks[0].content.lower()


@pytest.mark.asyncio
async def test_parse_file_list_content(adapter, sample_session_list_content):
    chunks = await adapter.parse_file(sample_session_list_content)
    assert len(chunks) > 0
    # Should contain the code from list content
    assert "python" in chunks[0].content.lower()


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_session):
    session_id = await adapter.get_session_id(sample_session)
    assert session_id == "abc123"


@pytest.mark.asyncio
async def test_get_session_id_fallback(adapter, tmp_path):
    """Fall back to file stem when no session_id in JSON."""
    data = {"messages": []}
    file_path = tmp_path / "fallback-session.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    session_id = await adapter.get_session_id(file_path)
    assert session_id == "fallback-session"


@pytest.mark.asyncio
async def test_get_session_title(adapter, sample_session):
    title = await adapter.get_session_title(sample_session)
    assert title is not None
    assert "git rebase" in title.lower()


@pytest.mark.asyncio
async def test_parse_empty_messages(adapter, tmp_path):
    data = {"session_id": "empty", "messages": []}
    file_path = tmp_path / "empty.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_invalid_json(adapter, tmp_path):
    file_path = tmp_path / "invalid.json"
    file_path.write_text("not valid json {{{")

    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_skips_system_messages(adapter, tmp_path):
    data = {
        "session_id": "sys",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "How do I configure Docker containers with networking?"},
            {
                "role": "assistant",
                "content": "You can configure Docker networking using docker-compose.yml...",
            },
        ],
    }
    file_path = tmp_path / "system.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    # System message should be skipped, only user-assistant exchange
    assert len(chunks) == 1
    assert "system" not in chunks[0].content.lower().split("human:")[0]
