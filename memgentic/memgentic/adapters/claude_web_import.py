"""Claude Web Import adapter — parses exported JSON from Claude web/desktop."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()


class ClaudeWebImportAdapter(BaseAdapter):
    """Parse Claude web/desktop conversation exports.

    Claude web exports produce a JSON file containing an array of conversations.
    Each conversation has a uuid, name, timestamps, and chat_messages array.
    This is an import-only adapter (no watch_paths).
    """

    @property
    def platform(self) -> Platform:
        return Platform.CLAUDE_WEB

    @property
    def watch_paths(self) -> list[Path]:
        return []  # Import-only adapter

    @property
    def file_patterns(self) -> list[str]:
        return ["*.json"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Extract session_id from the first conversation's UUID, or file stem."""
        data = await asyncio.to_thread(self._read_json, file_path)
        if data and isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict):
                uid = first.get("uuid")
                if uid:
                    return str(uid)
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Extract title from the first conversation's name."""
        data = await asyncio.to_thread(self._read_json, file_path)
        if data and isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict):
                name = first.get("name")
                if name:
                    return str(name)[:100].strip()
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse a Claude web export JSON file into chunks.

        The file contains an array of conversations. Each conversation's
        chat_messages are grouped into human-assistant exchange pairs.
        All chunks from all conversations are returned.
        """
        data = await asyncio.to_thread(self._read_json, file_path)

        if not data or not isinstance(data, list):
            return []

        all_chunks: list[ConversationChunk] = []

        for conversation in data:
            if not isinstance(conversation, dict):
                continue

            conv_title = conversation.get("name", "Untitled")
            conv_uuid = conversation.get("uuid", "unknown")
            chat_messages = conversation.get("chat_messages", [])

            if not chat_messages:
                continue

            chunks = self._parse_conversation(chat_messages, conv_title, conv_uuid)
            all_chunks.extend(chunks)

        logger.info(
            "claude_web.parsed",
            file=str(file_path),
            conversations=len(data),
            chunks=len(all_chunks),
        )
        return all_chunks

    def _parse_conversation(
        self,
        messages: list[dict],
        conv_title: str,
        conv_uuid: str,
    ) -> list[ConversationChunk]:
        """Parse a single conversation's messages into chunks."""
        chunks: list[ConversationChunk] = []
        current_exchange: list[str] = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue

            sender = msg.get("sender", "")
            text = self._extract_text(msg)

            if not text:
                continue

            if sender == "human":
                # Flush pending exchange
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
            elif sender == "assistant":
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

        # Create summary chunk for longer conversations
        if len(chunks) > 2:
            summary_parts = []
            for i, chunk in enumerate(chunks[:5], 1):
                preview = chunk.content[:200]
                summary_parts.append(f"Exchange {i}: {preview}")

            summary = (
                f"[{conv_title}] (ID: {conv_uuid}) "
                f"Conversation with {len(chunks)} exchanges.\n\n" + "\n\n".join(summary_parts)
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

    # --- Private helpers ---

    @staticmethod
    def _read_json(file_path: Path) -> list | None:
        """Synchronous helper — read and parse JSON array from *file_path*."""
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("claude_web.parse_error", file=str(file_path), error=str(e))
            return None

    @staticmethod
    def _extract_text(msg: dict) -> str:
        """Extract readable text from a chat message.

        Handles both "text" and "content" fields for message content.
        """
        # Try "text" first (primary field in Claude web exports)
        text = msg.get("text", "")
        if isinstance(text, str) and text.strip():
            return text.strip()

        # Fall back to "content"
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
