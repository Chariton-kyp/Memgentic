"""Aider adapter — parses Markdown chat history from .aider.chat.history.md files."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Try to use the Rust-native markdown parser.
try:
    from memgentic_native.parsers import split_markdown_turns as _native_split_markdown

    _USE_NATIVE_MD = True
except ImportError:
    _USE_NATIVE_MD = False


class AiderAdapter(BaseAdapter):
    """Parse Aider conversation history.

    Aider stores chat history as Markdown at ``.aider.chat.history.md`` in each
    project directory.  Turns are delimited by ``#### user`` and
    ``#### assistant`` headers.
    """

    @property
    def platform(self) -> Platform:
        return Platform.AIDER

    @property
    def watch_paths(self) -> list[Path]:
        # User must configure project paths — no single default location.
        return []

    @property
    def file_patterns(self) -> list[str]:
        return [".aider.chat.history.md"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session ID is the parent directory name (the project)."""
        return file_path.parent.name

    async def get_session_title(self, file_path: Path) -> str | None:
        """Extract the first user message as the session title."""
        return await asyncio.to_thread(self._read_session_title, file_path)

    def _read_session_title(self, file_path: Path) -> str | None:
        """Synchronous helper — reads the first user message as title."""
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        turns = self._split_turns(text)
        for role, content in turns:
            if role == "user" and content.strip():
                return content.strip()[:100]
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse an Aider Markdown chat history into chunks.

        Strategy: Group human-assistant exchanges into logical chunks.
        Each exchange becomes a memory unit preserving the dialogue context.
        """
        raw = await asyncio.to_thread(self._read_file, file_path)

        if not raw:
            return []

        turns = self._split_turns(raw)

        if not turns:
            return []

        chunks: list[ConversationChunk] = []

        # Group into human-assistant pairs
        current_exchange: list[str] = []

        for role, content in turns:
            text = content.strip()
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

        # Summary chunk for longer conversations
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
            "aider.parsed",
            file=str(file_path),
            turns=len(turns),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    @staticmethod
    def _read_file(file_path: Path) -> str:
        """Synchronous helper — read file contents."""
        try:
            return file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("aider.read_error", file=str(file_path), error=str(e))
            return ""

    @staticmethod
    def _split_turns(text: str) -> list[tuple[str, str]]:
        """Split Markdown into (role, content) pairs on ``#### `` markers.

        Uses Rust native parser when available.
        """
        if _USE_NATIVE_MD:
            try:
                return _native_split_markdown(text, "aider")
            except Exception:
                pass  # Fall through to Python

        # Python fallback
        parts = re.split(r"^####\s+", text, flags=re.MULTILINE)
        turns: list[tuple[str, str]] = []

        for part in parts:
            part = part.strip()
            if not part:
                continue

            lines = part.split("\n", 1)
            role_line = lines[0].strip().lower()
            content = lines[1].strip() if len(lines) > 1 else ""

            if role_line in ("user", "assistant"):
                turns.append((role_line, content))

        return turns
