"""Codex CLI adapter — reads sessions from ``~/.codex/state_5.sqlite``.

OpenAI's Codex CLI (the standalone Rust binary at ``codex``) tracks each
session as a row in ``state_5.sqlite``'s ``threads`` table. The actual
turn-by-turn conversation is written to a JSONL **rollout** file whose
path is stored in ``threads.rollout_path``. This adapter:

1. Opens the SQLite ``threads`` table and walks every non-archived row.
2. For each row, reads the rollout JSONL referenced by ``rollout_path``.
3. Parses the JSONL turns into ``ConversationChunk`` objects.

The OpenAI ChatGPT VS Code extension (``openai.chatgpt``) uses this same
database as its backend, so threads created from VS Code are captured by
the same code path.

If ``threads`` is empty (the user has Codex installed but never created a
persistent session), the adapter returns no chunks rather than failing —
the daemon will simply re-check the file when it next changes.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Codex CLI / OpenAI ChatGPT VS Code extension state.
CODEX_HOME = Path.home() / ".codex"
CODEX_STATE_DB = CODEX_HOME / "state_5.sqlite"


class CodexCliAdapter(BaseAdapter):
    """Parse OpenAI Codex CLI sessions from the SQLite + JSONL rollout layout.

    The adapter is keyed off the ``threads`` table in
    ``~/.codex/state_5.sqlite``. Each thread's ``rollout_path`` points at
    a JSONL file under ``~/.codex/`` with one wire message per line. The
    JSONL schema is the OpenAI Codex agent-loop event log: every message
    is wrapped in a ``record_type`` envelope and the inner ``payload``
    carries the actual turn role + content.

    We surface the file-watcher and ``import-existing`` semantics by
    treating the SQLite database itself as the watch target. Each call to
    :meth:`parse_file` re-reads the database and emits chunks for every
    non-archived thread; deduplication at the metadata layer prevents
    re-ingestion of unchanged sessions.
    """

    @property
    def platform(self) -> Platform:
        return Platform.CODEX_CLI

    @property
    def watch_paths(self) -> list[Path]:
        return [CODEX_HOME]

    @property
    def file_patterns(self) -> list[str]:
        # The SQLite file's WAL-mode change touches both the DB itself
        # and a `-wal` sibling. We only register the main file; the
        # daemon's debounce handles the WAL chatter.
        return ["state_5.sqlite"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """One Memgentic session per Codex thread; the row's ``id`` is unique."""
        # The adapter emits one chunk-set per thread, but the BaseAdapter
        # expects a single session_id per file. Defer to the database file
        # name; the per-thread id ends up in the rollout chunk metadata.
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Most recent thread's title is the closest thing to "session" title."""
        threads = await asyncio.to_thread(self._list_threads, file_path)
        for thread in threads:
            if thread.title:
                return thread.title[:100]
            if thread.first_user_message:
                return thread.first_user_message[:100]
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Walk every thread in the SQLite DB and emit chunks per thread."""
        threads = await asyncio.to_thread(self._list_threads, file_path)

        if not threads:
            logger.info(
                "codex_cli.no_threads",
                file=str(file_path),
                msg="state_5.sqlite has no thread rows yet",
            )
            return []

        chunks: list[ConversationChunk] = []

        for thread in threads:
            if thread.archived:
                continue
            rollout_path = self._resolve_rollout_path(thread.rollout_path)
            if rollout_path is None or not rollout_path.exists():
                logger.warning(
                    "codex_cli.rollout_missing",
                    thread_id=thread.id,
                    path=str(thread.rollout_path),
                )
                continue
            turns = await asyncio.to_thread(self._read_rollout, rollout_path)
            if not turns:
                continue
            chunks.extend(self._turns_to_chunks(thread, turns))

        logger.info(
            "codex_cli.parsed",
            file=str(file_path),
            threads=len(threads),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    def _list_threads(self, db_path: Path) -> list[_Thread]:
        """Read every row of the ``threads`` table."""
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, rollout_path, title, first_user_message,
                       cwd, created_at_ms, archived
                FROM threads
                ORDER BY created_at_ms DESC
                """
            )
            rows = cur.fetchall()
            conn.close()
        except sqlite3.Error as e:
            logger.warning("codex_cli.db_error", file=str(db_path), error=str(e))
            return []

        return [
            _Thread(
                id=row[0],
                rollout_path=row[1] or "",
                title=row[2] or "",
                first_user_message=row[3] or "",
                cwd=row[4] or "",
                created_at_ms=row[5] or 0,
                archived=bool(row[6]),
            )
            for row in rows
            if row[0]
        ]

    @staticmethod
    def _resolve_rollout_path(rollout_path: str) -> Path | None:
        """Resolve a ``threads.rollout_path`` to an absolute Path.

        The column may store an absolute path or one relative to ``~/.codex``.
        """
        if not rollout_path:
            return None
        candidate = Path(rollout_path)
        if candidate.is_absolute():
            return candidate
        return CODEX_HOME / rollout_path

    @staticmethod
    def _read_rollout(rollout_path: Path) -> list[dict]:
        """Load every JSONL line from a rollout file.

        Each line is a JSON object representing one Codex agent-loop event;
        we keep the raw dicts and let :meth:`_turns_to_chunks` extract
        user/assistant pairs.
        """
        try:
            text = rollout_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("codex_cli.rollout_read_error", file=str(rollout_path), error=str(e))
            return []

        events: list[dict] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(
                    "codex_cli.rollout_parse_error",
                    file=str(rollout_path),
                    line=line_no,
                    error=str(e),
                )
        return events

    def _turns_to_chunks(self, thread: _Thread, events: list[dict]) -> list[ConversationChunk]:
        """Reduce a rollout event stream to user/assistant exchanges.

        The rollout JSONL records many event types (tool calls, model
        deltas, agent status). We only keep the canonical user / assistant
        message events and pair them up.
        """
        chunks: list[ConversationChunk] = []
        current_exchange: list[str] = []

        for event in events:
            role, text = self._extract_message(event)
            if not text:
                continue

            if role == "user":
                if current_exchange:
                    chunk_text = "\n\n".join(current_exchange)
                    if len(chunk_text) > 50:
                        chunks.append(
                            ConversationChunk(
                                content=chunk_text,
                                content_type=self._classify_content(chunk_text),
                                topics=self._extract_topics(chunk_text),
                                entities=[],
                                confidence=0.9,
                            )
                        )
                current_exchange = [f"Human: {text}"]
            elif role == "assistant":
                current_exchange.append(f"Assistant: {text}")

        if current_exchange:
            chunk_text = "\n\n".join(current_exchange)
            if len(chunk_text) > 50:
                chunks.append(
                    ConversationChunk(
                        content=chunk_text,
                        content_type=self._classify_content(chunk_text),
                        topics=self._extract_topics(chunk_text),
                        entities=[],
                        confidence=0.9,
                    )
                )

        # Summary chunk for longer threads.
        if len(chunks) > 2:
            preview_parts = [
                f"Exchange {i}: {c.content[:200]}" for i, c in enumerate(chunks[:5], 1)
            ]
            title = thread.title or thread.first_user_message[:60] or "Codex session"
            summary = (
                f"Codex thread '{title}' with {len(chunks)} exchanges (cwd: "
                f"{thread.cwd or 'unknown'}).\n\n" + "\n\n".join(preview_parts)
            )
            chunks.insert(
                0,
                ConversationChunk(
                    content=summary,
                    content_type=ContentType.CONVERSATION_SUMMARY,
                    topics=self._merge_topics(chunks),
                    entities=[],
                    confidence=0.85,
                ),
            )

        return chunks

    @staticmethod
    def _extract_message(event: dict) -> tuple[str, str]:
        """Pull (role, text) out of one rollout event, or ('', '') if irrelevant.

        The Codex rollout records use a few different envelopes depending
        on the event type. We try the documented envelopes plus a couple
        of historical variants so older sessions keep parsing.
        """
        # Envelope 1: top-level {"role": "...", "content": "..."}
        role = event.get("role")
        if role in ("user", "assistant") and isinstance(event.get("content"), str):
            return role, event["content"].strip()

        # Envelope 2: {"payload": {"role": "...", "content": "..."}}
        payload = event.get("payload")
        if isinstance(payload, dict):
            role = payload.get("role")
            content = payload.get("content")
            if role in ("user", "assistant"):
                if isinstance(content, str):
                    return role, content.strip()
                if isinstance(content, list):
                    parts: list[str] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    return role, "\n".join(parts).strip()

        # Envelope 3: {"record_type": "user_message", "text": "..."}
        record_type = event.get("record_type") or event.get("type")
        text = event.get("text") or event.get("message")
        if record_type and isinstance(text, str):
            if "user" in record_type.lower():
                return "user", text.strip()
            if "assistant" in record_type.lower() or "response" in record_type.lower():
                return "assistant", text.strip()

        return "", ""


# Internal helper — small dataclass-like for thread rows. We avoid the
# ``dataclasses`` import to keep the module's import surface minimal.
class _Thread:
    __slots__ = (
        "id",
        "rollout_path",
        "title",
        "first_user_message",
        "cwd",
        "created_at_ms",
        "archived",
    )

    def __init__(
        self,
        *,
        id: str,
        rollout_path: str,
        title: str,
        first_user_message: str,
        cwd: str,
        created_at_ms: int,
        archived: bool,
    ) -> None:
        self.id = id
        self.rollout_path = rollout_path
        self.title = title
        self.first_user_message = first_user_message
        self.cwd = cwd
        self.created_at_ms = created_at_ms
        self.archived = archived
