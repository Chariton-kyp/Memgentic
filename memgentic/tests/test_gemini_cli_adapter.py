"""Tests for Gemini CLI adapter."""

import json

import pytest

from memgentic.adapters.gemini_cli import GeminiCliAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return GeminiCliAdapter()


@pytest.fixture
def sample_dict_format(tmp_path):
    """Create a sample Gemini CLI JSON file with dict/messages format."""
    data = {
        "messages": [
            {"role": "user", "parts": [{"text": "How do I deploy a FastAPI app to Docker?"}]},
            {
                "role": "model",
                "parts": [
                    {"text": "Here's how to deploy FastAPI with Docker:"},
                    {"text": "```dockerfile\nFROM python:3.12\nCOPY . /app\n```"},
                ],
            },
            {"role": "user", "parts": [{"text": "What about kubernetes deployment?"}]},
            {
                "role": "model",
                "parts": [{"text": "For Kubernetes, you'll need a deployment manifest..."}],
            },
        ]
    }

    file_path = tmp_path / "chat-session-1.json"
    with open(file_path, "w") as f:
        json.dump(data, f)
    return file_path


@pytest.fixture
def sample_flat_format(tmp_path):
    """Create a sample Gemini CLI JSON file with flat list format."""
    data = [
        {"role": "user", "content": "Explain Python decorators with examples"},
        {
            "role": "model",
            "content": (
                "Decorators are functions that modify other functions."
                " Here's a basic example with def decorator(func): ..."
            ),
        },
        {"role": "user", "content": "Can you show a class-based decorator?"},
        {
            "role": "model",
            "content": (
                "Sure! A class-based decorator uses __call__:"
                " class MyDecorator: def __init__(self, func): ..."
            ),
        },
    ]

    file_path = tmp_path / "chat-session-2.json"
    with open(file_path, "w") as f:
        json.dump(data, f)
    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.GEMINI_CLI


def test_adapter_file_patterns(adapter):
    assert "*.json" in adapter.file_patterns


def test_adapter_watch_paths(adapter):
    paths = adapter.watch_paths
    assert len(paths) == 1
    assert paths[0].name == "tmp"
    assert ".gemini" in str(paths[0])


@pytest.mark.asyncio
async def test_parse_file_dict_format(adapter, sample_dict_format):
    chunks = await adapter.parse_file(sample_dict_format)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_file_flat_format(adapter, sample_flat_format):
    chunks = await adapter.parse_file(sample_flat_format)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_preserves_exchange_structure(adapter, sample_dict_format):
    chunks = await adapter.parse_file(sample_dict_format)
    # Find non-summary chunks
    exchange_chunks = [c for c in chunks if c.content_type != ContentType.CONVERSATION_SUMMARY]
    assert len(exchange_chunks) >= 1
    # Exchanges should contain Human/Assistant labels
    for chunk in exchange_chunks:
        assert "Human:" in chunk.content or "Assistant:" in chunk.content


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_dict_format):
    session_id = await adapter.get_session_id(sample_dict_format)
    assert session_id == "chat-session-1"


@pytest.mark.asyncio
async def test_get_session_title_dict_format(adapter, sample_dict_format):
    title = await adapter.get_session_title(sample_dict_format)
    assert title is not None
    assert "FastAPI" in title


@pytest.mark.asyncio
async def test_get_session_title_flat_format(adapter, sample_flat_format):
    title = await adapter.get_session_title(sample_flat_format)
    assert title is not None
    assert "Python" in title


@pytest.mark.asyncio
async def test_parse_empty_file(adapter, tmp_path):
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("")
    chunks = await adapter.parse_file(empty_file)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_invalid_json(adapter, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json!!!}")
    chunks = await adapter.parse_file(bad_file)
    assert chunks == []


@pytest.mark.asyncio
async def test_skips_non_text_parts(adapter, tmp_path):
    """Non-text parts (images, etc.) should be skipped."""
    data = {
        "messages": [
            {
                "role": "user",
                "parts": [
                    {"text": "Analyze this image for me please, what do you see in this picture?"}
                ],
            },
            {
                "role": "model",
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": "base64..."}},
                    {
                        "text": (
                            "I see a diagram showing a microservices"
                            " architecture pattern with Docker containers"
                        )
                    },
                ],
            },
        ]
    }

    file_path = tmp_path / "with-image.json"
    with open(file_path, "w") as f:
        json.dump(data, f)

    chunks = await adapter.parse_file(file_path)
    assert len(chunks) >= 1
    # The image part should be skipped, but the text part should be present
    all_text = " ".join(c.content for c in chunks)
    assert "diagram" in all_text
    assert "base64" not in all_text


@pytest.mark.asyncio
async def test_topic_extraction(adapter, sample_dict_format):
    chunks = await adapter.parse_file(sample_dict_format)
    all_topics = set()
    for chunk in chunks:
        all_topics.update(chunk.topics)
    assert "docker" in all_topics or "kubernetes" in all_topics or "fastapi" in all_topics
