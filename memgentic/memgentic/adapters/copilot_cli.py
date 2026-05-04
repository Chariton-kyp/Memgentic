"""Copilot CLI adapter — captures user prompts from ``~/.copilot/``.

GitHub's Copilot CLI deliberately does **not** persist assistant responses
locally. The only conversation data on disk is
``~/.copilot/command-history-state.json``, which contains the list of user
prompts in a ``commandHistory`` array. This adapter captures each prompt
as a (user-side-only) memory chunk so search and recall pick up "what I
asked Copilot" even though the answer side is unrecoverable from disk.

If GitHub later starts persisting full transcripts on disk, extend this
adapter to also walk those files; the user-prompts capture below stays
useful as a baseline.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# GitHub Copilot CLI keeps user prompts at this single file. Sessions /
# assistant responses are NOT stored on disk.
COPILOT_CLI_BASE = Path.home() / ".copilot"
COPILOT_CLI_HISTORY_FILE = COPILOT_CLI_BASE / "command-history-state.json"

# Skip prompts shorter than this — typically slash-commands (/usage, /resume).
_MIN_PROMPT_LENGTH = 20


class CopilotCliAdapter(BaseAdapter):
    """Parse GitHub Copilot CLI's user-prompt history.

    Storage layout on Windows / macOS / Linux is the same:
    ``~/.copilot/command-history-state.json`` — a JSON file with a top-level
    ``commandHistory`` array. Each entry is a single user prompt string.
    There is no companion file with assistant responses; GitHub
    intentionally streams those without persisting.

    Treats the whole history file as one "session" (id =
    ``copilot-history``); each individual prompt above the minimum length
    becomes one ``ConversationChunk`` with ``Human:`` framing and an
    explicit note that the assistant side is unavailable.
    """

    @property
    def platform(self) -> Platform:
        return Platform.COPILOT_CLI

    @property
    def watch_paths(self) -> list[Path]:
        # Native + WSL home dirs (Windows users may run gh copilot from a WSL shell).
        from memgentic.adapters._wsl import wsl_user_paths

        return [COPILOT_CLI_BASE, *wsl_user_paths(".copilot")]

    @property
    def file_patterns(self) -> list[str]:
        # The history file has a fixed name; we still register a glob so
        # the daemon's file watcher fires when it's rewritten.
        return ["command-history-state.json"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """All prompts share one logical session per history file."""
        return "copilot-history"

    async def get_session_title(self, file_path: Path) -> str | None:
        """First prompt in the file works as a title."""
        prompts = await asyncio.to_thread(self._read_prompts, file_path)
        for prompt in prompts:
            if len(prompt) >= _MIN_PROMPT_LENGTH:
                return prompt[:100].strip()
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Build one chunk per substantive user prompt.

        We deliberately do NOT batch prompts into "exchanges" because there
        are no assistant responses to pair them with — each prompt is its
        own atomic memory.
        """
        prompts = await asyncio.to_thread(self._read_prompts, file_path)

        if not prompts:
            return []

        chunks: list[ConversationChunk] = []

        for prompt in prompts:
            text = prompt.strip()
            if len(text) < _MIN_PROMPT_LENGTH:
                continue

            chunk_text = (
                f"Human: {text}\n\n"
                "Assistant: [GitHub Copilot CLI does not persist assistant "
                "responses on disk; only the user prompt is captured.]"
            )

            chunks.append(
                ConversationChunk(
                    content=chunk_text,
                    content_type=self._classify_content(text),
                    topics=self._extract_topics(text),
                    entities=[],
                    confidence=0.6,  # User-side only: lower confidence.
                )
            )

        if len(chunks) > 2:
            summary_parts = [
                f"Prompt {i}: {c.content.split(chr(10))[0][7:207]}"
                for i, c in enumerate(chunks[:5], 1)
            ]
            summary = (
                f"Copilot CLI history with {len(chunks)} user prompts (assistant "
                f"responses not persisted by GitHub).\n\n" + "\n\n".join(summary_parts)
            )
            chunks.insert(
                0,
                ConversationChunk(
                    content=summary,
                    content_type=ContentType.CONVERSATION_SUMMARY,
                    topics=self._merge_topics(chunks),
                    entities=[],
                    confidence=0.55,
                ),
            )

        logger.info(
            "copilot_cli.parsed",
            file=str(file_path),
            prompts=len(prompts),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    @staticmethod
    def _read_prompts(file_path: Path) -> list[str]:
        """Read the ``commandHistory`` array from the history JSON file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning("copilot_cli.parse_error", file=str(file_path), error=str(e))
            return []

        if not isinstance(data, dict):
            return []

        history = data.get("commandHistory", [])
        if not isinstance(history, list):
            return []

        return [str(p) for p in history if isinstance(p, str)]

    @staticmethod
    def _file_modified(file_path: Path) -> datetime:
        """Return file mtime as UTC datetime — used as 'session timestamp'."""
        try:
            return datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
        except OSError:
            return datetime.now(UTC)
