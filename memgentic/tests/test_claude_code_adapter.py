"""Tests for Claude Code adapter."""

import json

import pytest

from memgentic.adapters.claude_code import ClaudeCodeAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return ClaudeCodeAdapter()


@pytest.fixture
def sample_conversation(tmp_path):
    """Create a sample Claude Code JSONL conversation file."""
    turns = [
        {
            "role": "human",
            "content": (
                "How should I structure my FastAPI project? I want to have a clean"
                " separation of concerns with routers, models, schemas, and services."
                " What is the best practice for a medium-sized API?"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "I recommend using a modular structure with separate directories for"
                " routers, models, schemas, and services. Each router should handle"
                " one domain, and dependency injection keeps things testable."
            ),
        },
        {
            "role": "human",
            "content": (
                "Let's go with that approach. What about testing? I need to test"
                " both synchronous and asynchronous endpoints with proper fixtures"
                " and database isolation between tests."
            ),
        },
        {
            "role": "assistant",
            "content": (
                "For testing, use pytest with pytest-asyncio for async endpoints."
                " Create fixtures for your test database and use httpx.AsyncClient"
                " for making requests. Isolate each test with transactions."
            ),
        },
        {
            "role": "human",
            "content": (
                "Can you write a sample test that demonstrates the async testing"
                " pattern with proper setup and teardown for the database connection?"
            ),
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Here's a sample test that shows the full pattern with async"
                        " client, database fixtures, and proper assertions:"
                    ),
                },
                {
                    "type": "text",
                    "text": "```python\nimport pytest\nfrom httpx import AsyncClient\n\n@pytest.mark.asyncio\nasync def test_health(client: AsyncClient):\n    resp = await client.get('/health')\n    assert resp.status_code == 200\n```",
                },
            ],
        },
    ]

    file_path = tmp_path / "test-session.jsonl"
    with open(file_path, "w") as f:
        for turn in turns:
            f.write(json.dumps(turn) + "\n")

    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.CLAUDE_CODE


def test_adapter_file_patterns(adapter):
    assert "*.jsonl" in adapter.file_patterns


@pytest.mark.asyncio
async def test_parse_file(adapter, sample_conversation):
    chunks = await adapter.parse_file(sample_conversation)
    assert len(chunks) > 0
    # Should have exchange chunks + possibly a summary
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_conversation):
    session_id = await adapter.get_session_id(sample_conversation)
    assert session_id == "test-session"


@pytest.mark.asyncio
async def test_get_session_title(adapter, sample_conversation):
    title = await adapter.get_session_title(sample_conversation)
    assert title is not None
    assert "FastAPI" in title


@pytest.mark.asyncio
async def test_parse_empty_file(adapter, tmp_path):
    empty_file = tmp_path / "empty.jsonl"
    empty_file.write_text("")
    chunks = await adapter.parse_file(empty_file)
    assert chunks == []


@pytest.mark.asyncio
async def test_content_classification(adapter, sample_conversation):
    chunks = await adapter.parse_file(sample_conversation)
    # At least one chunk should be detected as having code
    content_types = [c.content_type for c in chunks]
    # The conversation mentions code, so at least one should be code_snippet or decision
    assert any(
        ct in (ContentType.CODE_SNIPPET, ContentType.DECISION, ContentType.RAW_EXCHANGE)
        for ct in content_types
    )


def test_clean_text_strips_xml_noise():
    text = (
        "Hello world\n"
        "<system-reminder>This is internal noise\nwith multiple lines</system-reminder>\n"
        "Important content here\n"
        "<command-name>some_cmd</command-name>\n"
        "<local-command-stdout>lots of output</local-command-stdout>\n"
        "Final sentence"
    )
    result = ClaudeCodeAdapter._clean_text(text)
    assert "<system-reminder>" not in result
    assert "<command-name>" not in result
    assert "<local-command-stdout>" not in result
    assert "Hello world" in result
    assert "Important content here" in result
    assert "Final sentence" in result


def test_clean_text_collapses_newlines():
    text = "Line one\n\n\n\n\nLine two"
    result = ClaudeCodeAdapter._clean_text(text)
    assert result == "Line one\n\nLine two"


def test_extract_text_skips_tool_blocks():
    turn = {
        "message": {
            "content": [
                {"type": "text", "text": "Here is my explanation."},
                {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                {"type": "tool_result", "content": "file1.py\nfile2.py"},
                {"type": "thinking", "text": "Let me think about this..."},
                {"type": "text", "text": "And here is the conclusion."},
            ]
        }
    }
    result = ClaudeCodeAdapter._extract_text(turn)
    assert "Here is my explanation." in result
    assert "And here is the conclusion." in result
    assert "Bash" not in result
    assert "tool" not in result.lower()
    assert "thinking" not in result.lower()
    assert "file1.py" not in result


def test_is_substantive_filters_short_exchanges():
    # Too short
    short = ["Human: hi", "Assistant: hello"]
    assert ClaudeCodeAdapter._is_substantive_exchange(short) is False

    # Missing assistant
    no_assistant = ["Human: " + "x" * 300]
    assert ClaudeCodeAdapter._is_substantive_exchange(no_assistant) is False

    # Missing human
    no_human = ["Assistant: " + "x" * 300]
    assert ClaudeCodeAdapter._is_substantive_exchange(no_human) is False

    # Substantive
    good = [
        "Human: How should I structure my FastAPI project with proper testing?",
        "Assistant: I recommend using a modular structure with routers, models, and schemas separated. For testing use pytest with httpx for async endpoints.",
    ]
    assert ClaudeCodeAdapter._is_substantive_exchange(good) is True
