"""Cursor adapter — best-effort import of Cursor IDE conversation history.

Cursor stores chat/conversation state inside SQLite databases under its
user-data directory (``state.vscdb``). The exact schema is undocumented and
changes between Cursor releases, so this adapter takes a defensive,
best-effort approach:

1. Discover ``state.vscdb`` files in the standard Cursor locations for the
   current OS (Windows/macOS/Linux).
2. Look for rows whose JSON values appear to contain conversation/chat data
   (keys matching ``aichat``, ``interactive``, ``composer``, ``chat``).
3. Extract plain-text turns from whatever JSON structure is found, falling
   back to stringifying values if the structure is unfamiliar.

The adapter is registered under ``get_import_adapters()`` only (not as a
daemon-watched source) because Cursor writes to these databases as a live
SQLite handle and real-time watching is unreliable.

TODO: Once Cursor publishes a stable export format, replace this heuristic
parser with a schema-aware one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ConversationChunk, Platform

logger = structlog.get_logger()

# Keys that typically identify Cursor chat-related rows in ItemTable.
_CHAT_KEY_HINTS = (
    "aichat",
    "interactive",
    "composer",
    "chat",
    "cursor.chat",
    "workbench.panel.aichat",
)


class CursorAdapter(BaseAdapter):
    """Best-effort adapter for Cursor IDE conversation history."""

    @property
    def platform(self) -> Platform:
        return Platform.CURSOR

    @property
    def watch_paths(self) -> list[Path]:
        """Standard Cursor user-data locations per OS."""
        paths: list[Path] = []
        home = Path.home()

        if sys.platform.startswith("win"):
            appdata = os.environ.get("APPDATA")
            if appdata:
                paths.append(Path(appdata) / "Cursor" / "User" / "globalStorage")
                paths.append(Path(appdata) / "Cursor" / "User" / "workspaceStorage")
        elif sys.platform == "darwin":
            mac_base = home / "Library" / "Application Support" / "Cursor" / "User"
            paths.append(mac_base / "globalStorage")
            paths.append(mac_base / "workspaceStorage")
        else:  # linux and friends
            paths.append(home / ".config" / "Cursor" / "User" / "globalStorage")
            paths.append(home / ".config" / "Cursor" / "User" / "workspaceStorage")

        return paths

    @property
    def file_patterns(self) -> list[str]:
        return ["state.vscdb"]

    async def get_session_id(self, file_path: Path) -> str | None:
        # Workspace storage dirs are named with a hash — use that as session id.
        return file_path.parent.name or "cursor-global"

    async def get_session_title(self, file_path: Path) -> str | None:
        return f"Cursor ({file_path.parent.name})"

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Extract conversation chunks from a Cursor state.vscdb file."""
        return await asyncio.to_thread(self._parse_sync, file_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_sync(self, file_path: Path) -> list[ConversationChunk]:
        rows: list[tuple[str, Any]] = []
        try:
            # Open in read-only URI mode to avoid contention with a running Cursor.
            uri = f"file:{file_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        except sqlite3.Error as e:
            logger.warning("cursor.open_failed", file=str(file_path), error=str(e))
            return []

        try:
            with contextlib.closing(conn):
                cur = conn.cursor()
                try:
                    cur.execute("SELECT key, value FROM ItemTable")
                except sqlite3.Error:
                    # Some Cursor DBs use a different table name.
                    return []

                for key, value in cur.fetchall():
                    if not isinstance(key, str):
                        continue
                    lower_key = key.lower()
                    if not any(hint in lower_key for hint in _CHAT_KEY_HINTS):
                        continue
                    rows.append((key, value))
        except sqlite3.Error as e:
            logger.warning("cursor.query_failed", file=str(file_path), error=str(e))
            return []

        chunks: list[ConversationChunk] = []
        for _key, value in rows:
            texts = self._extract_texts(value)
            for text in texts:
                if len(text) < 50:
                    continue
                chunks.append(
                    ConversationChunk(
                        content=text[:4000],
                        content_type=self._classify_content(text),
                        topics=self._extract_topics(text),
                        entities=[],
                        confidence=0.6,  # Heuristic parse — lower confidence.
                    )
                )

        if chunks:
            logger.info(
                "cursor.parsed",
                file=str(file_path),
                rows=len(rows),
                chunks=len(chunks),
            )
        return chunks

    def _extract_texts(self, raw_value: Any) -> list[str]:
        """Extract human-readable text fragments from a Cursor ItemTable value."""
        if raw_value is None:
            return []

        # Values are typically bytes containing JSON.
        if isinstance(raw_value, (bytes, bytearray)):
            try:
                raw_value = raw_value.decode("utf-8", errors="replace")
            except Exception:
                return []

        if not isinstance(raw_value, str):
            return []

        # Try JSON first, then fall back to the raw string.
        try:
            parsed = json.loads(raw_value)
        except (json.JSONDecodeError, ValueError):
            return [raw_value] if len(raw_value) >= 50 else []

        found: list[str] = []
        self._walk_for_text(parsed, found)
        return found

    def _walk_for_text(self, node: Any, out: list[str]) -> None:
        """Recursively collect string values that look like chat content."""
        if isinstance(node, dict):
            # Common Cursor fields: text, content, message, richText
            for key in ("text", "content", "message", "richText", "markdown"):
                val = node.get(key)
                if isinstance(val, str) and val.strip():
                    out.append(val.strip())
            for v in node.values():
                self._walk_for_text(v, out)
        elif isinstance(node, list):
            for item in node:
                self._walk_for_text(item, out)
