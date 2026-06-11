"""Codex CLI adapter — reads rollout JSONL files from ``~/.codex/sessions/``.

OpenAI's standalone Codex CLI (Rust binary at ``codex``) writes a rollout
JSONL per session under ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``.
Each rollout file is a sequence of JSON event objects with the shape:

    {"timestamp": "...", "type": "<event-type>", "payload": {...}}

Event types we care about:

- ``session_meta``       one-time per file; carries cwd, model provider, etc.
- ``response_item``      payload.type=="message" — the actual user / assistant
                         turns. ``payload.role`` is ``"user"`` /
                         ``"assistant"`` / ``"developer"``; ``payload.content``
                         is a list of ``{"type": "input_text" | "output_text",
                         "text": "..."}`` blocks. Developer messages
                         (system prompts, env metadata) are skipped.
- ``event_msg``          internal lifecycle events (task_started, task_complete);
                         skipped.
- ``turn_context``       per-turn metadata (cwd, model); skipped.

Sessions written by ``codex exec`` and the interactive ``codex`` TUI both
land here. Sessions started inside the VS Code OpenAI extension may use
``--ephemeral`` and not persist anywhere on disk — they are cloud-only and
unrecoverable. The adapter only sees what reaches the local sessions
directory.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters._wsl import wsl_user_paths
from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform
from memgentic.processing.project import derive_project

logger = structlog.get_logger()

# Codex CLI session storage. Override-able via the CODEX_HOME env var on the
# Codex side; the adapter does not currently read that override because the
# default path is what every user runs with unless they explicitly set it.
CODEX_HOME = Path.home() / ".codex"
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"

# Drop turns shorter than this — typically empty stdin reads or tool acks.
_MIN_TURN_LENGTH = 5


class CodexCliAdapter(BaseAdapter):
    """Parse OpenAI Codex CLI rollout JSONL conversation files.

    Each rollout file is one logical session. Turns are extracted from
    ``response_item`` events whose payload is a ``message`` with role
    ``user`` or ``assistant``. The role ``developer`` is skipped — those
    are the system prompt + tool descriptions that Codex prepends to every
    session and would dominate semantic search if ingested.
    """

    @property
    def platform(self) -> Platform:
        return Platform.CODEX_CLI

    @property
    def watch_paths(self) -> list[Path]:
        # Native ``~/.codex/sessions/`` plus any Codex sessions directories
        # found inside WSL distros (Windows-only; many users run ``codex``
        # from a WSL shell, not PowerShell, and the rollouts land in WSL's
        # filesystem — invisible to a Windows-side watcher otherwise).
        return [CODEX_SESSIONS_DIR, *wsl_user_paths(".codex/sessions")]

    @property
    def file_patterns(self) -> list[str]:
        # Codex names files ``rollout-<timestamp>-<session-id>.jsonl``; we
        # match by suffix because the date directory pattern (YYYY/MM/DD/)
        # is handled by the BaseAdapter's recursive walk via ``watch_paths``.
        return ["rollout-*.jsonl"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session id is the trailing UUID embedded in the filename.

        ``rollout-2026-05-04T12-41-13-019df25c-fdb5-7fe0-8c2e-7b3c7415b258.jsonl``
        → ``019df25c-fdb5-7fe0-8c2e-7b3c7415b258``
        """
        stem = file_path.stem
        # Filename format: rollout-<YYYY-MM-DDTHH-MM-SS>-<UUID>
        # UUID is 36 chars (8-4-4-4-12). Take the last 36 chars of the stem
        # and validate they look UUID-shaped.
        if len(stem) >= 36:
            tail = stem[-36:]
            if tail.count("-") == 4:
                return tail
        return stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """First user message in the rollout works as a title."""
        events = await asyncio.to_thread(self._read_events, file_path)
        for role, text in self._iter_messages(events):
            if role == "user":
                return text[:100].strip()
        return None

    async def get_project(self, file_path: Path) -> str | None:
        """Codex stores ``cwd`` inside ``session_meta`` — perfect signal."""
        events = await asyncio.to_thread(self._read_events, file_path)
        cwd = self._extract_cwd(events)
        return derive_project(cwd=cwd) or None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Group user-assistant message pairs into chunks.

        Strategy mirrors the other adapters: every "user → ...assistant..."
        block becomes one chunk. Developer messages (system prompt) are
        excluded entirely.
        """
        events = await asyncio.to_thread(self._read_events, file_path)

        if not events:
            return []

        chunks: list[ConversationChunk] = []
        current_exchange: list[str] = []

        for role, text in self._iter_messages(events):
            if len(text) < _MIN_TURN_LENGTH:
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

        if len(chunks) > 2:
            preview_parts = [
                f"Exchange {i}: {c.content[:200]}" for i, c in enumerate(chunks[:5], 1)
            ]
            cwd = self._extract_cwd(events) or "unknown cwd"
            summary = f"Codex session ({cwd}) with {len(chunks)} exchanges.\n\n" + "\n\n".join(
                preview_parts
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

        logger.info(
            "codex_cli.parsed",
            file=str(file_path),
            events=len(events),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    @staticmethod
    def _read_events(file_path: Path) -> list[dict]:
        """Load every JSONL line as a dict; warn-and-skip on parse errors."""
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("codex_cli.rollout_read_error", file=str(file_path), error=str(e))
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
                    file=str(file_path),
                    line=line_no,
                    error=str(e),
                )
        return events

    @staticmethod
    def _iter_messages(events: list[dict]):
        """Yield ``(role, text)`` for every user/assistant message in order.

        Codex writes turns as:
            {"type": "response_item",
             "payload": {"type": "message",
                         "role": "user" | "assistant" | "developer",
                         "content": [{"type": "input_text" | "output_text",
                                      "text": "..."}, ...]}}

        Developer messages (system prompt, environment context, skill list)
        are skipped — they would otherwise dominate semantic recall.
        """
        for event in events:
            if event.get("type") != "response_item":
                continue
            payload = event.get("payload") or {}
            if payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            content = payload.get("content") or []
            if not isinstance(content, list):
                continue
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                # Codex uses input_text for user-side, output_text for
                # assistant-side. Some legacy variants also emit raw "text".
                if btype in ("input_text", "output_text", "text"):
                    text = block.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            joined = "\n".join(text_parts).strip()
            if joined:
                yield role, joined

    @staticmethod
    def _extract_cwd(events: list[dict]) -> str | None:
        """Pull the cwd off the ``session_meta`` event for the summary chunk."""
        for event in events:
            if event.get("type") == "session_meta":
                payload = event.get("payload") or {}
                cwd = payload.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
        return None
