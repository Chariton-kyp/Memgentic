"""Tests for Codex CLI adapter — reads SQLite ``threads`` + JSONL rollouts."""

import json
import sqlite3

import pytest

from memgentic.adapters.codex_cli import CodexCliAdapter
from memgentic.models import ContentType, Platform


@pytest.fixture
def adapter():
    return CodexCliAdapter()


def _create_state_db(tmp_path, threads):
    """Build a minimal ``state_5.sqlite`` populated with the supplied threads."""
    db_path = tmp_path / "state_5.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE threads (
            id TEXT,
            rollout_path TEXT,
            created_at INTEGER,
            updated_at INTEGER,
            source TEXT,
            model_provider TEXT,
            cwd TEXT,
            title TEXT,
            sandbox_policy TEXT,
            approval_mode TEXT,
            tokens_used INTEGER,
            has_user_event INTEGER,
            archived INTEGER,
            archived_at INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT,
            first_user_message TEXT,
            agent_nickname TEXT,
            agent_role TEXT,
            memory_mode TEXT,
            model TEXT,
            reasoning_effort TEXT,
            agent_path TEXT,
            created_at_ms INTEGER,
            updated_at_ms INTEGER
        )
        """
    )
    for t in threads:
        cur.execute(
            "INSERT INTO threads (id, rollout_path, title, first_user_message, "
            "cwd, created_at_ms, archived) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                t["id"],
                t["rollout_path"],
                t.get("title", ""),
                t.get("first_user_message", ""),
                t.get("cwd", ""),
                t.get("created_at_ms", 0),
                int(t.get("archived", 0)),
            ),
        )
    conn.commit()
    conn.close()
    return db_path


def _write_rollout(path, events):
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.CODEX_CLI


def test_adapter_file_patterns(adapter):
    assert "state_5.sqlite" in adapter.file_patterns


def test_adapter_watch_paths(adapter):
    assert len(adapter.watch_paths) == 1
    assert "codex" in str(adapter.watch_paths[0])


@pytest.mark.asyncio
async def test_parse_no_threads_returns_empty(adapter, tmp_path):
    db_path = _create_state_db(tmp_path, [])
    chunks = await adapter.parse_file(db_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_thread_with_top_level_envelope(adapter, tmp_path):
    """Codex rollout events with top-level ``role``/``content`` keys."""
    rollout_path = tmp_path / "rollout-thread-1.jsonl"
    _write_rollout(
        rollout_path,
        [
            {"role": "user", "content": "How do I deploy a FastAPI app behind Caddy?"},
            {
                "role": "assistant",
                "content": "Add a Caddyfile that reverse-proxies to localhost:3691 and run caddy run.",
            },
            {"role": "user", "content": "And how do I add HTTPS?"},
            {
                "role": "assistant",
                "content": "Caddy auto-provisions Let's Encrypt certs once your domain points at the server.",
            },
        ],
    )
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "t1",
                "rollout_path": str(rollout_path),
                "title": "FastAPI deploy",
                "first_user_message": "How do I deploy a FastAPI app behind Caddy?",
                "cwd": "/repo/api",
                "created_at_ms": 1,
                "archived": 0,
            }
        ],
    )
    chunks = await adapter.parse_file(db_path)
    # 2 user/assistant exchanges + 0 summary (need >2 to add summary)
    assert len(chunks) == 2
    assert "Caddyfile" in chunks[0].content
    assert "Let's Encrypt" in chunks[1].content
    for chunk in chunks:
        assert "Human:" in chunk.content
        assert "Assistant:" in chunk.content


@pytest.mark.asyncio
async def test_parse_thread_with_payload_envelope(adapter, tmp_path):
    """Codex rollout events with ``payload.role``/``payload.content`` envelope."""
    rollout_path = tmp_path / "rollout-thread-2.jsonl"
    _write_rollout(
        rollout_path,
        [
            {"payload": {"role": "user", "content": "Explain Python decorators with an example"}},
            {
                "payload": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "A decorator is a function that wraps another function.",
                        },
                        {
                            "type": "text",
                            "text": "Example:\n```python\n@functools.wraps\ndef my_decorator(...): ...\n```",
                        },
                    ],
                }
            },
        ],
    )
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "t2",
                "rollout_path": str(rollout_path),
                "title": "Decorators",
                "created_at_ms": 2,
            }
        ],
    )
    chunks = await adapter.parse_file(db_path)
    assert len(chunks) == 1
    assert "decorator" in chunks[0].content.lower()
    assert "functools.wraps" in chunks[0].content


@pytest.mark.asyncio
async def test_parse_thread_with_record_type_envelope(adapter, tmp_path):
    """Codex rollout events using legacy ``record_type``/``text`` envelope."""
    rollout_path = tmp_path / "rollout-thread-3.jsonl"
    _write_rollout(
        rollout_path,
        [
            {"record_type": "user_message", "text": "Generate a SQL schema for a memory store"},
            {
                "record_type": "assistant_response",
                "text": "CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL);",
            },
        ],
    )
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "t3",
                "rollout_path": str(rollout_path),
                "title": "SQL schema",
                "created_at_ms": 3,
            }
        ],
    )
    chunks = await adapter.parse_file(db_path)
    assert len(chunks) == 1
    assert "CREATE TABLE memories" in chunks[0].content


@pytest.mark.asyncio
async def test_archived_threads_skipped(adapter, tmp_path):
    rollout_path = tmp_path / "rollout-archived.jsonl"
    _write_rollout(rollout_path, [{"role": "user", "content": "x" * 80}])
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "archived",
                "rollout_path": str(rollout_path),
                "title": "Old session",
                "created_at_ms": 4,
                "archived": 1,
            }
        ],
    )
    chunks = await adapter.parse_file(db_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_missing_rollout_file_logged_and_skipped(adapter, tmp_path):
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "ghost",
                "rollout_path": str(tmp_path / "does-not-exist.jsonl"),
                "title": "Ghost thread",
                "created_at_ms": 5,
            }
        ],
    )
    chunks = await adapter.parse_file(db_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_summary_chunk_for_long_thread(adapter, tmp_path):
    """Threads with >2 exchanges get a leading summary chunk."""
    rollout_path = tmp_path / "rollout-long.jsonl"
    events = []
    for i in range(4):
        events.append({"role": "user", "content": f"Question number {i + 1} about a long topic"})
        events.append(
            {
                "role": "assistant",
                "content": f"Detailed answer to question {i + 1} explaining the topic",
            }
        )
    _write_rollout(rollout_path, events)
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "long",
                "rollout_path": str(rollout_path),
                "title": "Long thread",
                "first_user_message": "Question number 1 about a long topic",
                "cwd": "/projects/foo",
                "created_at_ms": 6,
            }
        ],
    )
    chunks = await adapter.parse_file(db_path)
    # 4 exchanges + 1 summary = 5
    assert len(chunks) == 5
    assert chunks[0].content_type == ContentType.CONVERSATION_SUMMARY
    assert "Long thread" in chunks[0].content
    assert "/projects/foo" in chunks[0].content


@pytest.mark.asyncio
async def test_get_session_title_falls_back_to_first_user_message(adapter, tmp_path):
    db_path = _create_state_db(
        tmp_path,
        [
            {
                "id": "untitled",
                "rollout_path": str(tmp_path / "x.jsonl"),
                "title": "",
                "first_user_message": "Help me debug this Python function",
                "created_at_ms": 7,
            }
        ],
    )
    title = await adapter.get_session_title(db_path)
    assert title is not None
    assert "Python" in title


@pytest.mark.asyncio
async def test_missing_database_returns_empty(adapter, tmp_path):
    nonexistent = tmp_path / "no-such-db.sqlite"
    chunks = await adapter.parse_file(nonexistent)
    assert chunks == []
