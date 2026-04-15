"""Copilot CLI adapter — parses JSON session files from ~/.copilot/session-state/."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Copilot CLI stores sessions at ~/.copilot/session-state/
COPILOT_CLI_BASE = Path.home() / ".copilot" / "session-state"


class CopilotCliAdapter(BaseAdapter):
    """Parse Copilot CLI session history.

    Copilot CLI stores each session as a JSON file containing a session_id
    and a messages array with role/content pairs.
    """

    @property
    def platform(self) -> Platform:
        return Platform.COPILOT_CLI

    @property
    def watch_paths(self) -> list[Path]:
        return [COPILOT_CLI_BASE]

    @property
    def file_patterns(self) -> list[str]:
        return ["*.json"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Extract session_id from JSON content, falling back to file stem."""
        data = await asyncio.to_thread(self._read_json, file_path)
        if data and isinstance(data, dict):
            sid = data.get("session_id")
            if sid:
                return str(sid)
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Extract title from the first user message."""
        return await asyncio.to_thread(self._read_session_title, file_path)

    def _read_session_title(self, file_path: Path) -> str | None:
        """Synchronous helper — reads the first user message as title."""
        data = self._read_json(file_path)
        if not data or not isinstance(data, dict):
            return None

        messages = data.get("messages", [])
        for msg in messages:
            role = msg.get("role", "")
            if role == "user":
                text = self._extract_text(msg)
                if text:
                    return text[:100].strip()
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse a Copilot CLI JSON session into chunks.

        Strategy: Group user-assistant exchanges into logical chunks.
        Each exchange becomes a memory unit preserving the dialogue context.
        """
        data = await asyncio.to_thread(self._read_json, file_path)

        if not data or not isinstance(data, dict):
            return []

        messages = data.get("messages", [])
        if not messages:
            return []

        chunks: list[ConversationChunk] = []

        # Group into user-assistant pairs
        current_exchange: list[str] = []

        for msg in messages:
            role = msg.get("role", "")

            # Skip system messages
            if role == "system":
                continue

            text = self._extract_text(msg)
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
            elif role == "assistant":
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

        # Create a summary chunk for longer conversations
        if len(chunks) > 2:
            summary_parts = []
            for i, chunk in enumerate(chunks[:5], 1):
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
            "copilot_cli.parsed",
            file=str(file_path),
            messages=len(messages),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    @staticmethod
    def _read_json(file_path: Path) -> dict | None:
        """Synchronous helper — read and parse JSON from *file_path*."""
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("copilot_cli.parse_error", file=str(file_path), error=str(e))
            return None

    @staticmethod
    def _extract_text(msg: dict) -> str:
        """Extract readable text from a message.

        Content can be a string or a list of parts.
        """
        content = msg.get("content", "")

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts).strip()

        return str(content).strip() if content else ""
