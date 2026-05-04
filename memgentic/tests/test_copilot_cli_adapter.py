"""Tests for Copilot CLI adapter — reads ``~/.copilot/command-history-state.json``."""

import json

import pytest

from memgentic.adapters.copilot_cli import CopilotCliAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return CopilotCliAdapter()


def _write_history(tmp_path, prompts):
    file_path = tmp_path / "command-history-state.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({"commandHistory": prompts}, f)
    return file_path


@pytest.fixture
def sample_history(tmp_path):
    """Realistic-shape history JSON with five prompts, one short slash command."""
    return _write_history(
        tmp_path,
        [
            "How do I configure Docker networking with custom subnets?",
            "Write a Python function that sorts a list of dicts by nested key",
            "/usage",  # too short — should be skipped
            "Explain the difference between rebase and merge in git",
            "Generate a fastapi endpoint with rate limiting and request size cap",
        ],
    )


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.COPILOT_CLI


def test_adapter_file_patterns(adapter):
    assert "command-history-state.json" in adapter.file_patterns


def test_adapter_watch_paths(adapter):
    assert len(adapter.watch_paths) == 1
    assert "copilot" in str(adapter.watch_paths[0])


@pytest.mark.asyncio
async def test_parse_file_emits_chunk_per_prompt(adapter, sample_history):
    chunks = await adapter.parse_file(sample_history)
    # 4 substantive prompts (one short ``/usage`` skipped) + 1 summary = 5
    assert len(chunks) == 5
    summary = chunks[0]
    assert summary.content_type == ContentType.CONVERSATION_SUMMARY
    body = chunks[1:]
    for chunk in body:
        assert chunk.content.startswith("Human:")
        assert "GitHub Copilot CLI does not persist" in chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_file_skips_short_prompts(adapter, tmp_path):
    file_path = _write_history(tmp_path, ["/usage", "/resume", "?"])
    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_get_session_id_is_stable(adapter, sample_history):
    sid = await adapter.get_session_id(sample_history)
    assert sid == "copilot-history"


@pytest.mark.asyncio
async def test_get_session_title_is_first_substantive_prompt(adapter, sample_history):
    title = await adapter.get_session_title(sample_history)
    assert title is not None
    assert "Docker" in title


@pytest.mark.asyncio
async def test_parse_empty_history(adapter, tmp_path):
    file_path = _write_history(tmp_path, [])
    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_invalid_json(adapter, tmp_path):
    file_path = tmp_path / "command-history-state.json"
    file_path.write_text("not valid json {{{", encoding="utf-8")
    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_missing_command_history_key(adapter, tmp_path):
    file_path = tmp_path / "command-history-state.json"
    file_path.write_text(json.dumps({"unrelated": []}), encoding="utf-8")
    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_assistant_disclaimer_in_every_chunk(adapter, sample_history):
    """The CLI does not persist responses; chunk content must say so."""
    chunks = await adapter.parse_file(sample_history)
    body = [c for c in chunks if c.content_type != ContentType.CONVERSATION_SUMMARY]
    for chunk in body:
        assert "[GitHub Copilot CLI does not persist assistant responses on disk" in chunk.content
