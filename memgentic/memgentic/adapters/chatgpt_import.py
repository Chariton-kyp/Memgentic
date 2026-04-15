"""ChatGPT import adapter — parses exported conversations.json from ChatGPT."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Try to use the Rust-native ChatGPT parser (5-8x faster on large exports).
try:
    from memgentic_native.parsers import flatten_chatgpt_mapping as _native_flatten_mapping

    _USE_NATIVE_CHATGPT = True
except ImportError:
    _USE_NATIVE_CHATGPT = False


class ChatGPTImportAdapter(BaseAdapter):
    """Parse ChatGPT exported conversation data.

    ChatGPT exports produce a single ``conversations.json`` file containing an
    array of conversation objects.  Each conversation uses a ``mapping`` dict
    with parent/children links to represent the message tree.

    This adapter is import-only — it does not watch for file changes.
    """

    @property
    def platform(self) -> Platform:
        return Platform.CHATGPT

    @property
    def watch_paths(self) -> list[Path]:
        return []  # Import-only, no file watching

    @property
    def file_patterns(self) -> list[str]:
        return ["conversations.json"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session ID is the file stem (typically 'conversations')."""
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Return the title of the first conversation in the file."""
        return await asyncio.to_thread(self._read_session_title, file_path)

    def _read_session_title(self, file_path: Path) -> str | None:
        """Synchronous helper — reads the first conversation title."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict):
                title = first.get("title")
                if isinstance(title, str) and title:
                    return title[:100].strip()
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse a ChatGPT conversations.json into chunks.

        A single file contains multiple conversations.  Each conversation is
        processed independently, producing its own set of chunks.
        """
        conversations = await asyncio.to_thread(self._read_conversations, file_path)

        if not conversations:
            return []

        all_chunks: list[ConversationChunk] = []

        for conv in conversations:
            if not isinstance(conv, dict):
                continue
            chunks = self._process_conversation(conv)
            all_chunks.extend(chunks)

        logger.info(
            "chatgpt_import.parsed",
            file=str(file_path),
            conversations=len(conversations),
            chunks=len(all_chunks),
        )
        return all_chunks

    # --- Private helpers ---

    @staticmethod
    def _read_conversations(file_path: Path) -> list[dict]:
        """Synchronous helper — read and parse the conversations array."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("chatgpt_import.parse_error", file=str(file_path), error=str(e))
            return []

        if isinstance(data, list):
            return data
        return []

    def _process_conversation(self, conv: dict) -> list[ConversationChunk]:
        """Process a single ChatGPT conversation into chunks."""
        title = conv.get("title", "Untitled")
        mapping = conv.get("mapping", {})

        if not isinstance(mapping, dict):
            return []

        # Flatten the mapping tree into chronological turns
        turns = self._flatten_mapping(mapping)

        if not turns:
            return []

        chunks: list[ConversationChunk] = []

        # Group into user-assistant pairs
        current_exchange: list[str] = []

        for turn in turns:
            role = turn["role"]
            text = turn["text"]

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
            for i, chunk in enumerate(chunks[:5], 1):  # First 5 exchanges
                preview = chunk.content[:200]
                summary_parts.append(f"Exchange {i}: {preview}")

            summary = f"ChatGPT conversation: {title} ({len(chunks)} exchanges).\n\n" + "\n\n".join(
                summary_parts
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
    def _flatten_mapping(mapping: dict) -> list[dict[str, str]]:
        """Flatten a ChatGPT mapping tree into chronological turns.

        Each node in the mapping has an 'id', optional 'message', 'parent', and
        'children'.  We sort by create_time to get chronological order, then
        extract user/assistant turns only.

        Uses Rust native parser when available (5-8x faster).
        """
        if _USE_NATIVE_CHATGPT:
            try:
                mapping_json = json.dumps(mapping)
                return _native_flatten_mapping(mapping_json)
            except Exception:
                pass  # Fall through to Python

        nodes_with_time: list[tuple[float, str, str]] = []

        for node in mapping.values():
            if not isinstance(node, dict):
                continue

            message = node.get("message")
            if not isinstance(message, dict):
                continue

            author = message.get("author", {})
            if not isinstance(author, dict):
                continue

            role = author.get("role", "")
            if role not in ("user", "assistant"):
                continue  # Skip system/tool messages

            # Extract text from content.parts
            content = message.get("content", {})
            if not isinstance(content, dict):
                continue

            parts = content.get("parts", [])
            if not isinstance(parts, list):
                continue

            text_parts: list[str] = []
            for part in parts:
                if isinstance(part, str):
                    text_parts.append(part)
                # Skip non-string parts (images, etc.)

            text = "\n".join(text_parts).strip()
            if not text:
                continue

            create_time = message.get("create_time") or 0.0
            if not isinstance(create_time, (int, float)):
                create_time = 0.0

            nodes_with_time.append((create_time, role, text))

        # Sort by create_time for chronological order
        nodes_with_time.sort(key=lambda x: x[0])

        return [{"role": role, "text": text} for _, role, text in nodes_with_time]

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to a URL-friendly slug."""
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        return slug[:80].strip("-")
