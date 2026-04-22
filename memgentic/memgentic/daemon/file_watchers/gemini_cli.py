"""Gemini CLI file watcher.

Gemini CLI writes conversations to ``~/.gemini/tmp/<project>/chats/*.json``.
The file format is a full JSON document (either ``{"messages": [...]}`` or a
flat list), so the watcher re-parses the file on each change and captures
*new* turns by comparing the total turn count against the persisted
``last_offset`` (here repurposed as a turn-count cursor).

Partial writes — when Gemini flushes an incomplete JSON document — are
handled by the adapter's JSON-parse guard; when parsing fails we return
``None`` so the orchestrator retries later without advancing the cursor.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.adapters.gemini_cli import GEMINI_CLI_BASE, GeminiCliAdapter
from memgentic.daemon.file_watchers.base import BaseFileWatcher, DeltaPayload
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()


class GeminiCliFileWatcher(BaseFileWatcher):
    tool = "gemini_cli"
    platform = Platform.GEMINI_CLI

    def watch_dirs(self) -> list[Path]:
        return [GEMINI_CLI_BASE]

    def patterns(self) -> list[str]:
        return ["*.json"]

    def adapter(self) -> BaseAdapter:
        return GeminiCliAdapter()

    async def parse_delta(self, file_path: Path, last_offset: int) -> DeltaPayload | None:
        turns = await asyncio.to_thread(_safe_read_turns, file_path)
        if turns is None:
            # Partial write or transient read error — let the orchestrator retry.
            return None

        total = len(turns)
        if total <= last_offset:
            return DeltaPayload(
                chunks=[],
                new_offset=total,
                session_id=file_path.stem,
                session_title=None,
            )

        new_turns = turns[last_offset:]
        chunks = _pair_turns_into_chunks(new_turns)
        title = _first_user_text(turns)

        logger.debug(
            "gemini_cli_watcher.delta",
            file=str(file_path),
            new_turns=len(new_turns),
            new_chunks=len(chunks),
        )

        return DeltaPayload(
            chunks=chunks,
            new_offset=total,
            session_id=file_path.stem,
            session_title=title,
        )


def _safe_read_turns(file_path: Path) -> list[dict] | None:
    """Read + normalize turns, returning ``None`` on partial/invalid JSON."""
    try:
        raw = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return GeminiCliAdapter._normalize_turns(data)  # type: ignore[attr-defined]


def _first_user_text(turns: list[dict]) -> str | None:
    for turn in turns:
        if turn.get("role") == "user":
            text = GeminiCliAdapter._extract_text(turn)  # type: ignore[attr-defined]
            if text:
                return text[:100].strip()
    return None


def _pair_turns_into_chunks(turns: list[dict]) -> list[ConversationChunk]:
    """Group turns into exchange-level chunks (user + one or more models)."""
    chunks: list[ConversationChunk] = []
    buffer: list[str] = []

    for turn in turns:
        role = turn.get("role", "")
        text = GeminiCliAdapter._extract_text(turn)  # type: ignore[attr-defined]
        if not text:
            continue
        if role == "user":
            if buffer:
                _flush(buffer, chunks)
            buffer = [f"Human: {text}"]
        elif role in {"model", "assistant"}:
            buffer.append(f"Assistant: {text}")

    if buffer:
        _flush(buffer, chunks)
    return chunks


def _flush(buffer: list[str], chunks: list[ConversationChunk]) -> None:
    text = "\n\n".join(buffer)
    if len(text) < 50:
        return
    chunks.append(
        ConversationChunk(
            content=text,
            content_type=ContentType.RAW_EXCHANGE,
            topics=[],
            entities=[],
            confidence=0.9,
        )
    )


__all__ = ["GeminiCliFileWatcher"]
