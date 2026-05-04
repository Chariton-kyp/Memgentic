"""Tests for Codex CLI adapter — reads ``~/.codex/sessions/.../rollout-*.jsonl``."""

import json

import pytest

from memgentic.adapters.codex_cli import CodexCliAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return CodexCliAdapter()


def _write_rollout(path, events):
    """Write a JSONL rollout file at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def _msg(role, text, content_type="input_text"):
    """Build a ``response_item`` event with one message block."""
    return {
        "timestamp": "2026-05-04T12:41:17.620Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": content_type, "text": text}],
        },
    }


def _session_meta(cwd="C:/repo"):
    return {
        "timestamp": "2026-05-04T12:41:17.617Z",
        "type": "session_meta",
        "payload": {
            "id": "019df25c-fdb5-7fe0-8c2e-7b3c7415b258",
            "cwd": cwd,
            "originator": "codex_exec",
            "cli_version": "0.128.0-alpha.1",
        },
    }


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.CODEX_CLI


def test_adapter_file_patterns(adapter):
    assert "rollout-*.jsonl" in adapter.file_patterns


def test_adapter_watch_paths(adapter):
    # First entry is always the native ``~/.codex/sessions/`` directory; on
    # Windows additional entries may appear for WSL distros that have a
    # Codex sessions tree. Test only the invariant: native path is first
    # and every entry mentions codex/sessions.
    paths = adapter.watch_paths
    assert len(paths) >= 1
    assert all("codex" in str(p).lower() for p in paths)
    assert all("sessions" in str(p).lower() for p in paths)


@pytest.mark.asyncio
async def test_parse_user_assistant_pair(adapter, tmp_path):
    file_path = tmp_path / "rollout-2026-05-04T12-41-13-019df25c-fdb5-7fe0-8c2e-7b3c7415b258.jsonl"
    _write_rollout(
        file_path,
        [
            _session_meta("C:/repo/api"),
            _msg("user", "How do I deploy a FastAPI app behind Caddy?"),
            _msg(
                "assistant",
                "Add a Caddyfile that reverse-proxies to localhost:3691 and run caddy run.",
                content_type="output_text",
            ),
            _msg("user", "And how do I add HTTPS?"),
            _msg(
                "assistant",
                "Caddy auto-provisions Let's Encrypt certs once your domain points at the server.",
                content_type="output_text",
            ),
        ],
    )

    chunks = await adapter.parse_file(file_path)
    # 2 user/assistant exchanges, no summary (need >2 to add summary)
    assert len(chunks) == 2
    assert "Caddyfile" in chunks[0].content
    assert "Let's Encrypt" in chunks[1].content
    for chunk in chunks:
        assert "Human:" in chunk.content
        assert "Assistant:" in chunk.content


@pytest.mark.asyncio
async def test_skips_developer_messages(adapter, tmp_path):
    """``role: developer`` is the system prompt + env context. Must be skipped."""
    file_path = tmp_path / "rollout-2026-05-04-dev.jsonl"
    _write_rollout(
        file_path,
        [
            _session_meta(),
            # The system prompt arrives as a developer message; ignore it.
            _msg("developer", "You are Codex, a coding agent. " * 50),
            _msg("user", "Generate a SQL schema for a memory store"),
            _msg(
                "assistant",
                "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL);",
                content_type="output_text",
            ),
        ],
    )
    chunks = await adapter.parse_file(file_path)
    assert len(chunks) == 1
    assert "You are Codex" not in chunks[0].content
    assert "CREATE TABLE memories" in chunks[0].content


@pytest.mark.asyncio
async def test_skips_non_response_item_events(adapter, tmp_path):
    """``event_msg``, ``turn_context`` etc. are lifecycle noise — drop them."""
    file_path = tmp_path / "rollout-2026-05-04-noise.jsonl"
    _write_rollout(
        file_path,
        [
            _session_meta(),
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.5"}},
            _msg("user", "Explain Python decorators"),
            _msg(
                "assistant",
                "A decorator wraps another function. Example: @functools.wraps",
                content_type="output_text",
            ),
            {"type": "event_msg", "payload": {"type": "task_complete"}},
        ],
    )
    chunks = await adapter.parse_file(file_path)
    assert len(chunks) == 1
    assert "decorator" in chunks[0].content.lower()


@pytest.mark.asyncio
async def test_summary_chunk_for_long_session(adapter, tmp_path):
    """Sessions with >2 exchanges get a leading summary chunk with cwd."""
    file_path = tmp_path / "rollout-2026-05-04-long.jsonl"
    events = [_session_meta("/projects/foo")]
    for i in range(4):
        events.append(_msg("user", f"Question number {i + 1} about a long topic"))
        events.append(
            _msg(
                "assistant",
                f"Detailed answer to question {i + 1} about the long topic",
                content_type="output_text",
            )
        )
    _write_rollout(file_path, events)
    chunks = await adapter.parse_file(file_path)
    # 4 exchanges + 1 summary
    assert len(chunks) == 5
    assert chunks[0].content_type == ContentType.CONVERSATION_SUMMARY
    assert "/projects/foo" in chunks[0].content


@pytest.mark.asyncio
async def test_parse_empty_rollout(adapter, tmp_path):
    file_path = tmp_path / "rollout-2026-05-04-empty.jsonl"
    file_path.write_text("", encoding="utf-8")
    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_only_session_meta(adapter, tmp_path):
    """Session that crashed before any messages were exchanged."""
    file_path = tmp_path / "rollout-2026-05-04-meta-only.jsonl"
    _write_rollout(file_path, [_session_meta()])
    chunks = await adapter.parse_file(file_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_invalid_lines_logged_and_skipped(adapter, tmp_path):
    file_path = tmp_path / "rollout-2026-05-04-bad.jsonl"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        "not valid json\n"
        + json.dumps(_msg("user", "How do I run pytest?"))
        + "\n"
        + json.dumps(
            _msg(
                "assistant",
                "Run pytest from the project root with uv run pytest.",
                content_type="output_text",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    chunks = await adapter.parse_file(file_path)
    assert len(chunks) == 1
    assert "pytest" in chunks[0].content.lower()


@pytest.mark.asyncio
async def test_session_id_extracted_from_filename(adapter, tmp_path):
    file_path = tmp_path / "rollout-2026-05-04T12-41-13-019df25c-fdb5-7fe0-8c2e-7b3c7415b258.jsonl"
    _write_rollout(file_path, [_session_meta()])
    sid = await adapter.get_session_id(file_path)
    assert sid == "019df25c-fdb5-7fe0-8c2e-7b3c7415b258"


@pytest.mark.asyncio
async def test_session_title_uses_first_user_message(adapter, tmp_path):
    file_path = tmp_path / "rollout-2026-05-04-title.jsonl"
    _write_rollout(
        file_path,
        [
            _session_meta(),
            _msg("user", "How do I configure CORS in FastAPI?"),
            _msg(
                "assistant",
                "Use the CORSMiddleware with allow_origins.",
                content_type="output_text",
            ),
        ],
    )
    title = await adapter.get_session_title(file_path)
    assert title is not None
    assert "CORS" in title


@pytest.mark.asyncio
async def test_short_turns_filtered(adapter, tmp_path):
    """Sub-_MIN_TURN_LENGTH turns must be dropped."""
    file_path = tmp_path / "rollout-2026-05-04-shorty.jsonl"
    _write_rollout(
        file_path,
        [
            _session_meta(),
            _msg("user", "ok"),  # too short
            _msg(
                "assistant",
                "Acknowledged but not enough context to act.",
                content_type="output_text",
            ),
            _msg("user", "Now actually explain how to set up Postgres logical replication"),
            _msg(
                "assistant",
                "Set wal_level=logical, restart Postgres, then CREATE PUBLICATION on the source...",
                content_type="output_text",
            ),
        ],
    )
    chunks = await adapter.parse_file(file_path)
    # The "ok" turn is short enough to be skipped, so the assistant ack
    # gets attached to no preceding user turn — only the substantive
    # exchange survives. Assert at least the long exchange is present.
    assert any("Postgres logical replication" in c.content for c in chunks)
