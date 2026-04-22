"""Aider file watcher.

Aider appends to ``<project>/.aider.chat.history.md``. We reuse the main
Aider adapter to parse the whole file and track progress via a *byte*
offset so re-entering the watcher after a daemon restart doesn't reingest
previous turns.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from memgentic.adapters.aider import AiderAdapter
from memgentic.adapters.base import BaseAdapter
from memgentic.daemon.file_watchers.base import BaseFileWatcher, DeltaPayload
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()


class AiderFileWatcher(BaseFileWatcher):
    tool = "aider"
    platform = Platform.AIDER

    def watch_dirs(self) -> list[Path]:
        # Aider is project-local — user configures project paths via
        # ``memgentic watchers install --tool aider --path <dir>``. The
        # orchestrator reads extras from ctx.
        return [p for p in self._ctx.extra_watch_paths]

    def patterns(self) -> list[str]:
        return [".aider.chat.history.md"]

    def adapter(self) -> BaseAdapter:
        return AiderAdapter()

    async def parse_delta(
        self,
        file_path: Path,
        last_offset: int,
    ) -> DeltaPayload | None:
        raw = await self.read_new_bytes(file_path, last_offset)
        if not raw:
            size = _safe_size(file_path)
            return DeltaPayload(chunks=[], new_offset=size, session_id=file_path.parent.name)

        # Only act once the append ends on a newline — otherwise we have a
        # partial turn that the next event will finish.
        if not raw.endswith(b"\n"):
            return None

        text = raw.decode("utf-8", errors="replace").strip()
        chunks = _split_markdown_turns(text)
        size = last_offset + len(raw)

        logger.debug(
            "aider_watcher.delta",
            file=str(file_path),
            bytes=len(raw),
            chunks=len(chunks),
        )

        return DeltaPayload(
            chunks=chunks,
            new_offset=size,
            session_id=file_path.parent.name,
            session_title=None,
        )


def _safe_size(file_path: Path) -> int:
    try:
        return file_path.stat().st_size
    except OSError:
        return 0


def _split_markdown_turns(text: str) -> list[ConversationChunk]:
    """Split an Aider delta on ``#### user`` / ``#### assistant`` headers."""
    if not text:
        return []

    lines = text.splitlines()
    buffer: list[str] = []
    role: str | None = None
    chunks: list[ConversationChunk] = []
    current_exchange: list[str] = []

    def flush_role() -> None:
        nonlocal buffer, role
        if not role or not buffer:
            buffer = []
            return
        payload = "\n".join(buffer).strip()
        if not payload:
            buffer = []
            return
        if role == "user" and current_exchange:
            _finalize(current_exchange, chunks)
            current_exchange.clear()
        prefix = "Human: " if role == "user" else "Assistant: "
        current_exchange.append(prefix + payload)
        buffer = []

    for line in lines:
        lower = line.strip().lower()
        if lower in {"#### user", "#### assistant"}:
            flush_role()
            role = "user" if lower == "#### user" else "assistant"
            continue
        buffer.append(line)

    flush_role()
    if current_exchange:
        _finalize(current_exchange, chunks)
    return chunks


def _finalize(exchange: list[str], out: list[ConversationChunk]) -> None:
    content = "\n\n".join(exchange).strip()
    if len(content) < 50:
        return
    out.append(
        ConversationChunk(
            content=content,
            content_type=ContentType.RAW_EXCHANGE,
            topics=[],
            entities=[],
            confidence=0.9,
        )
    )


__all__ = ["AiderFileWatcher"]
