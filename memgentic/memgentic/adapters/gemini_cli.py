"""Gemini CLI adapter — parses JSON conversation files from ~/.gemini/tmp/."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform
from memgentic.processing.project import derive_project

logger = structlog.get_logger()

# Gemini CLI stores conversations at ~/.gemini/tmp/<project_hash>/chats/*.json
GEMINI_CLI_BASE = Path.home() / ".gemini" / "tmp"

# Tool-response markers Gemini emits when a turn is a function-call output
# (``[Function Response: read_many_files]`` and friends). These outputs are
# often hundreds of KB of file dumps and add zero conversational signal —
# we skip them at the parser layer.
_TOOL_RESPONSE_MARKERS: tuple[str, ...] = (
    "[Function Response:",
    "[Tool Output:",
    "[Tool Response:",
    "[Function Call:",
)


def _is_tool_response_dump(text: str) -> bool:
    """Return True if ``text`` is dominated by a tool-response payload.

    Triggers on either an explicit marker prefix at the start of the text
    or, defensively, when a marker appears within the first 200 chars
    (Gemini sometimes prepends a one-line "Calling tool ..." preamble).
    """
    head = text.lstrip()[:300]
    return any(marker in head for marker in _TOOL_RESPONSE_MARKERS)


class GeminiCliAdapter(BaseAdapter):
    """Parse Gemini CLI conversation history.

    Gemini CLI stores conversations as JSON files in two possible formats:
    1. Dict with "messages" key containing a list of turns
    2. Flat list of turns

    Each turn has a "role" (user/model) and content as either "parts" (list of
    dicts with "text" key) or a "content" string.
    """

    @property
    def platform(self) -> Platform:
        return Platform.GEMINI_CLI

    @property
    def watch_paths(self) -> list[Path]:
        # Native ``~/.gemini/tmp/`` plus WSL equivalents on Windows.
        from memgentic.adapters._wsl import wsl_user_paths

        return [GEMINI_CLI_BASE, *wsl_user_paths(".gemini/tmp")]

    @property
    def file_patterns(self) -> list[str]:
        return ["*.json"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session ID is the filename without extension."""
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Try to extract title from the first user message."""
        return await asyncio.to_thread(self._read_session_title, file_path)

    async def get_project(self, file_path: Path) -> str | None:
        """Try the JSON ``cwd`` field, fall back to no signal.

        Newer Gemini CLI sessions write a top-level ``cwd`` field; older ones
        only carry an opaque project hash directory name (``<hex>``) which
        cannot be reliably mapped back to a friendly project key.
        """
        cwd = await asyncio.to_thread(self._read_cwd, file_path)
        return derive_project(cwd=cwd) or None

    @staticmethod
    def _read_cwd(file_path: Path) -> str | None:
        """Best-effort scan for a top-level ``cwd`` or ``workingDirectory`` key."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(data, dict):
            for key in ("cwd", "workingDirectory", "working_directory", "projectPath"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def _read_session_title(self, file_path: Path) -> str | None:
        """Synchronous helper — reads the first user message as title."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

        turns = self._normalize_turns(data)
        for turn in turns:
            if turn.get("role") == "user":
                text = self._extract_text(turn)
                if text:
                    return text[:100].strip()
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse a Gemini CLI JSON conversation into chunks.

        Strategy: Group user-model exchanges into logical chunks.
        Each exchange becomes a memory unit preserving the dialogue context.
        """
        turns = await asyncio.to_thread(self._read_turns, file_path)

        if not turns:
            return []

        chunks: list[ConversationChunk] = []

        # Group into user-model pairs
        current_exchange: list[str] = []

        for turn in turns:
            # Newer Gemini CLI sessions use "type"; older ones used "role".
            role = turn.get("role") or turn.get("type") or ""
            text = self._extract_text(turn)

            if not text:
                continue

            # Drop Function-Response / Tool-Output turn dumps. Gemini CLI
            # surfaces large tool outputs (e.g. ``read_many_files`` reading
            # dozens of files at once) as a single user turn whose text
            # starts with ``[Function Response: ...]`` and grows to 100s
            # of KB. Indexing these as memories is pure noise — they
            # bloat the vector store and dominate semantic recall.
            if _is_tool_response_dump(text):
                continue

            if role == "user":
                # If we have a pending exchange, flush it
                if current_exchange:
                    chunk_text = "\n\n".join(current_exchange)
                    if len(chunk_text) > 50:  # Skip trivially short exchanges
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
            elif role in ("model", "gemini", "assistant"):
                # Newer Gemini CLI emits type="gemini" for assistant turns;
                # older sessions used role="model"; some forks use "assistant".
                current_exchange.append(f"Assistant: {text}")

        # Flush last exchange
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

        # Also create a summary chunk for the whole conversation
        if len(chunks) > 2:
            summary_parts = []
            for i, chunk in enumerate(chunks[:5], 1):  # First 5 exchanges
                preview = chunk.content[:200]
                summary_parts.append(f"Exchange {i}: {preview}")

            summary = f"Conversation with {len(chunks)} exchanges.\n\n" + "\n\n".join(summary_parts)
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
            "gemini_cli.parsed",
            file=str(file_path),
            turns=len(turns),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    @staticmethod
    def _normalize_turns(data: dict | list) -> list[dict]:
        """Normalize both JSON formats into a flat list of turn dicts.

        Handles:
        1. {"messages": [...]} — dict with messages key
        2. [...] — flat list of turns
        """
        if isinstance(data, dict):
            messages = data.get("messages", [])
            if isinstance(messages, list):
                return messages
            return []

        if isinstance(data, list):
            return data

        return []

    def _read_turns(self, file_path: Path) -> list[dict]:
        """Synchronous helper — read and parse all turns from a JSON file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("gemini_cli.parse_error", file=str(file_path), error=str(e))
            return []

        return self._normalize_turns(data)

    @staticmethod
    def _extract_text(turn: dict) -> str:
        """Extract readable text from a Gemini CLI turn.

        Content can be:
        - "content": [{"text": "..."}, ...] (newer Gemini CLI: list of part dicts)
        - "parts": [{"text": "..."}, ...] (older Gemini "parts" key)
        - "content": "..." (flat fallback)
        """
        # Newer format: content is a list of {"text": ...} dicts
        content = turn.get("content")
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
                elif isinstance(part, str):
                    text_parts.append(part)
            return "\n".join(text_parts).strip()

        # Older "parts" format
        parts = turn.get("parts")
        if isinstance(parts, list):
            text_parts = []
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
                elif isinstance(part, str):
                    text_parts.append(part)
            return "\n".join(text_parts).strip()

        # Flat string fallback
        if isinstance(content, str):
            return content.strip()

        return ""
