"""Copilot CLI file watcher.

Copilot CLI writes session state as JSON files in
``~/.copilot/session-state/``. Because the format is a full JSON document
we reparse on each change and count new messages against the persisted
offset — mirroring the Gemini CLI watcher.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.adapters.copilot_cli import COPILOT_CLI_BASE, CopilotCliAdapter
from memgentic.daemon.file_watchers.base import BaseFileWatcher, DeltaPayload
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()


class CopilotCliFileWatcher(BaseFileWatcher):
    tool = "copilot_cli"
    platform = Platform.COPILOT_CLI

    def watch_dirs(self) -> list[Path]:
        return [COPILOT_CLI_BASE]

    def patterns(self) -> list[str]:
        return ["*.json"]

    def adapter(self) -> BaseAdapter:
        return CopilotCliAdapter()

    async def parse_delta(
        self,
        file_path: Path,
        last_offset: int,
    ) -> DeltaPayload | None:
        data = await asyncio.to_thread(_safe_read_json, file_path)
        if data is None:
            return None

        messages = _extract_messages(data)
        total = len(messages)
        session_id = _session_id(data, file_path)
        if total <= last_offset:
            return DeltaPayload(chunks=[], new_offset=total, session_id=session_id)

        new_msgs = messages[last_offset:]
        chunks: list[ConversationChunk] = []
        buffer: list[str] = []
        for msg in new_msgs:
            role = str(msg.get("role", "")).lower()
            text = str(msg.get("content", "")).strip()
            if not text:
                continue
            if role in {"user", "human"}:
                _flush(buffer, chunks)
                buffer = [f"Human: {text}"]
            elif role in {"assistant", "model", "copilot"}:
                buffer.append(f"Assistant: {text}")
        _flush(buffer, chunks)

        return DeltaPayload(
            chunks=chunks,
            new_offset=total,
            session_id=session_id,
            session_title=None,
        )


def _safe_read_json(file_path: Path) -> dict | None:
    try:
        raw = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _extract_messages(data: dict) -> list[dict]:
    msgs = data.get("messages") if isinstance(data, dict) else None
    if isinstance(msgs, list):
        return msgs
    return []


def _session_id(data: dict, file_path: Path) -> str:
    if isinstance(data, dict):
        sid = data.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    return file_path.stem


def _flush(buffer: list[str], out: list[ConversationChunk]) -> None:
    if not buffer:
        return
    text = "\n\n".join(buffer)
    if len(text) < 50:
        buffer.clear()
        return
    out.append(
        ConversationChunk(
            content=text,
            content_type=ContentType.RAW_EXCHANGE,
            topics=[],
            entities=[],
            confidence=0.9,
        )
    )
    buffer.clear()


__all__ = ["CopilotCliFileWatcher"]
