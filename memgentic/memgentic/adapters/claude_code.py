"""Claude Code adapter — parses JSONL conversation files from ~/.claude/projects/."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Try to use the Rust-native JSONL parser (5-10x faster, less memory).
try:
    from memgentic_native.parsers import parse_jsonl_file as _native_parse_jsonl

    _USE_NATIVE = True
except ImportError:
    _USE_NATIVE = False

# Claude Code stores conversations at ~/.claude/projects/<path-hash>/<session-id>.jsonl
CLAUDE_CODE_BASE = Path.home() / ".claude" / "projects"


class ClaudeCodeAdapter(BaseAdapter):
    """Parse Claude Code conversation history.

    Claude Code stores each conversation as a JSONL file with one JSON object
    per line (one per turn). Each turn has 'type', 'role', 'content', etc.
    """

    @property
    def platform(self) -> Platform:
        return Platform.CLAUDE_CODE

    @property
    def watch_paths(self) -> list[Path]:
        return [CLAUDE_CODE_BASE]

    @property
    def file_patterns(self) -> list[str]:
        return ["*.jsonl"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session ID is the filename without extension."""
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Try to extract title from the first user message."""
        return await asyncio.to_thread(self._read_session_title, file_path)

    def _read_session_title(self, file_path: Path) -> str | None:
        """Synchronous helper — reads the first human message as title."""
        try:
            with open(file_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turn = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Look for first human/user message
                    if turn.get("type") in ("human", "user") or turn.get("role") in (
                        "human",
                        "user",
                    ):
                        content = self._extract_text(turn)
                        if content and not content.startswith("[Tool"):
                            return content[:100].strip()
        except (OSError, UnicodeDecodeError):
            pass
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse a Claude Code JSONL conversation into chunks.

        Strategy: Group human-assistant exchanges into logical chunks.
        Each exchange becomes a memory unit preserving the dialogue context.
        Skips system/infrastructure turns and trivially short content.
        """
        turns = await asyncio.to_thread(self._read_turns, file_path)

        if not turns:
            return []

        chunks: list[ConversationChunk] = []

        # Group into human-assistant pairs
        current_exchange: list[str] = []

        for turn in turns:
            role = turn.get("role", turn.get("type", ""))

            # Skip infrastructure turns
            if role in ("system", "file-history-snapshot"):
                continue

            text = self._extract_text(turn)

            # Skip turns with negligible content after cleaning
            if len(text) < 20:
                continue

            if role in ("human", "user"):
                # If we have a pending exchange, flush it
                if current_exchange and self._is_substantive_exchange(current_exchange):
                    chunk_text = "\n\n".join(current_exchange)
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
            elif role in ("assistant", "model"):
                current_exchange.append(f"Assistant: {text}")

        # Flush last exchange
        if current_exchange and self._is_substantive_exchange(current_exchange):
            chunk_text = "\n\n".join(current_exchange)
            chunks.append(
                ConversationChunk(
                    content=chunk_text,
                    content_type=self._classify_content(chunk_text),
                    topics=self._extract_topics(chunk_text),
                    entities=[],
                    confidence=0.9,
                )
            )

        # Create a structured summary for the whole conversation
        if len(chunks) > 2:
            all_topics = self._merge_topics(chunks)
            topic_line = f"Topics: {', '.join(all_topics)}" if all_topics else ""

            key_points: list[str] = []
            for chunk in chunks[:5]:
                # Take first meaningful line from each chunk as a key point
                for line in chunk.content.split("\n"):
                    line = line.strip()
                    if line and len(line) > 30:
                        key_points.append(f"- {line[:150]}")
                        break

            summary_parts = [f"Conversation with {len(chunks)} exchanges."]
            if topic_line:
                summary_parts.append(topic_line)
            if key_points:
                summary_parts.append("Key points:\n" + "\n".join(key_points))

            summary = "\n\n".join(summary_parts)
            chunks.insert(
                0,
                ConversationChunk(
                    content=summary,
                    content_type=ContentType.CONVERSATION_SUMMARY,
                    topics=all_topics,
                    entities=[],
                    confidence=0.85,
                ),
            )

        logger.info(
            "claude_code.parsed",
            file=str(file_path),
            turns=len(turns),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    # XML tags injected by Claude Code infrastructure — pure noise for memory.
    _XML_NOISE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
        re.compile(r"<task-notification>.*?</task-notification>", re.DOTALL),
        re.compile(
            r"<observed_from_primary_session>.*?</observed_from_primary_session>",
            re.DOTALL,
        ),
        re.compile(r"<command-name>.*?</command-name>", re.DOTALL),
        re.compile(r"<command-message>.*?</command-message>", re.DOTALL),
        re.compile(r"<command-args>.*?</command-args>", re.DOTALL),
        re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.DOTALL),
    ]

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip XML infrastructure noise and normalise whitespace."""
        for pattern in ClaudeCodeAdapter._XML_NOISE_PATTERNS:
            text = pattern.sub("", text)
        # Collapse 3+ consecutive newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _is_substantive_exchange(exchange: list[str]) -> bool:
        """Return True if the exchange has both human and assistant content and is long enough."""
        has_human = any(part.startswith("Human:") for part in exchange)
        has_assistant = any(part.startswith("Assistant:") for part in exchange)
        total_len = sum(len(part) for part in exchange)
        return has_human and has_assistant and total_len >= 200

    @staticmethod
    def _read_turns(file_path: Path) -> list[dict]:
        """Synchronous helper — read and parse all JSONL turns from *file_path*.

        Uses Rust native parser when available (5-10x faster, streaming I/O).
        """
        if _USE_NATIVE:
            try:
                # Native parser returns list of {"role": str, "text": str} dicts.
                # We wrap them to match the expected format for _extract_text.
                native_turns = _native_parse_jsonl(str(file_path))
                return [
                    {"role": t["role"], "message": {"content": t["text"]}} for t in native_turns
                ]
            except Exception as e:
                logger.warning(
                    "claude_code.native_parse_fallback",
                    file=str(file_path),
                    error=str(e),
                )
                # Fall through to Python implementation

        turns: list[dict] = []
        try:
            with open(file_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        turns.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("claude_code.parse_error", file=str(file_path), error=str(e))
        return turns

    @staticmethod
    def _extract_text(turn: dict) -> str:
        """Extract readable text from a Claude Code turn.

        Only keeps ``type=text`` blocks — tool_use, tool_result, and thinking
        blocks are skipped entirely to avoid polluting memories with noise.
        """
        # Try message.content first (current Claude Code format)
        message = turn.get("message")
        if isinstance(message, dict):
            content = message.get("content", "")
        elif isinstance(message, str) and message:
            return ClaudeCodeAdapter._clean_text(message)
        else:
            content = turn.get("content", "")

        if isinstance(content, str):
            return ClaudeCodeAdapter._clean_text(content)

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                # Only keep text blocks — skip tool_use, tool_result, thinking
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            result = "\n".join(parts).strip()
            return ClaudeCodeAdapter._clean_text(result) if result else ""

        return ClaudeCodeAdapter._clean_text(str(content)) if content else ""
