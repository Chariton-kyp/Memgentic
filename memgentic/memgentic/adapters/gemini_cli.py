"""Gemini CLI adapter — parses JSON conversation files from ~/.gemini/tmp/."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Gemini CLI stores conversations at ~/.gemini/tmp/<project_hash>/chats/*.json
GEMINI_CLI_BASE = Path.home() / ".gemini" / "tmp"


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
        return [GEMINI_CLI_BASE]

    @property
    def file_patterns(self) -> list[str]:
        return ["*.json"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session ID is the filename without extension."""
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Try to extract title from the first user message."""
        return await asyncio.to_thread(self._read_session_title, file_path)

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
            role = turn.get("role", "")
            text = self._extract_text(turn)

            if not text:
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
            elif role == "model":
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
        - "parts": [{"text": "..."}, ...] (Gemini format)
        - "content": "..." (flat format)
        """
        # Try "parts" format first (Gemini native)
        parts = turn.get("parts")
        if isinstance(parts, list):
            text_parts: list[str] = []
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
                    # Skip non-text parts (images, etc.)
                elif isinstance(part, str):
                    text_parts.append(part)
            return "\n".join(text_parts).strip()

        # Try "content" format (flat)
        content = turn.get("content", "")
        if isinstance(content, str):
            return content.strip()

        return ""
