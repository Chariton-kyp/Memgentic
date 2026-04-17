"""Base adapter interface for conversation sources."""

from __future__ import annotations

import abc
import fnmatch
import os
from pathlib import Path

from memgentic.models import ContentType, ConversationChunk, Platform

# Directories whose *name* matches one of these glob patterns are skipped
# across all adapters. These are meta-tooling conversations (other memory
# projects, observer sessions, synthetic test fixtures) that pollute
# semantic search ranking without adding user-relevant context.
#
# Extend at runtime via `MEMGENTIC_EXCLUDE_PATHS` (comma-separated globs).
# Matching is done against any path segment, not just the leaf, so e.g.
# `*observer-sessions*` catches
# `~/.claude/projects/C--Users-harit--claude-mem-observer-sessions/foo.jsonl`.
_DEFAULT_EXCLUDE_DIR_GLOBS: tuple[str, ...] = (
    "*claude-mem-observer-sessions*",
    "*claude-mem*observer*",
    "*memgentic-observer*",
)


def _compiled_exclude_globs() -> tuple[str, ...]:
    """Return built-in excludes merged with user overrides from env."""
    extra = os.environ.get("MEMGENTIC_EXCLUDE_PATHS", "").strip()
    if not extra:
        return _DEFAULT_EXCLUDE_DIR_GLOBS
    user_globs = tuple(g.strip() for g in extra.split(",") if g.strip())
    return _DEFAULT_EXCLUDE_DIR_GLOBS + user_globs


class BaseAdapter(abc.ABC):
    """Abstract base class for conversation source adapters.

    Each adapter knows how to:
    1. Find conversation files for its platform
    2. Parse them into ConversationChunk objects
    3. Report which platform it handles
    """

    @property
    @abc.abstractmethod
    def platform(self) -> Platform:
        """The platform this adapter handles."""

    @property
    @abc.abstractmethod
    def watch_paths(self) -> list[Path]:
        """Directories to watch for new conversation files."""

    @property
    @abc.abstractmethod
    def file_patterns(self) -> list[str]:
        """Glob patterns for conversation files (e.g., '*.jsonl')."""

    @abc.abstractmethod
    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse a conversation file into chunks.

        Args:
            file_path: Path to the conversation file.

        Returns:
            List of ConversationChunk objects ready for ingestion.
        """

    @abc.abstractmethod
    async def get_session_id(self, file_path: Path) -> str | None:
        """Extract the session ID from a file path or its contents."""

    @abc.abstractmethod
    async def get_session_title(self, file_path: Path) -> str | None:
        """Extract or generate a session title."""

    # --- File discovery ---

    @staticmethod
    def _safe_mtime(p: Path) -> float:
        """Return the file modification time, or ``0.0`` if the file has been deleted."""
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def discover_files(self) -> list[Path]:
        """Find all conversation files for this adapter, honouring the
        module-level exclude list (see `_DEFAULT_EXCLUDE_DIR_GLOBS`).

        Files whose path contains a segment matching any exclude glob are
        dropped — this prevents meta-tooling conversations (memory-observer
        sessions, synthetic fixtures) from polluting semantic search.
        """
        excludes = _compiled_exclude_globs()
        files: list[Path] = []
        for watch_path in self.watch_paths:
            if not watch_path.exists():
                continue
            for pattern in self.file_patterns:
                for candidate in watch_path.rglob(pattern):
                    if _path_is_excluded(candidate, excludes):
                        continue
                    files.append(candidate)
        return sorted(files, key=self._safe_mtime, reverse=True)

    def is_excluded(self, file_path: Path) -> bool:
        """Whether this file should be skipped by the daemon watcher. The same
        policy that `discover_files` applies — exposed so watchers can drop
        incoming events without ingesting.
        """
        return _path_is_excluded(file_path, _compiled_exclude_globs())

    # --- Shared utility methods ---

    # (module-level helpers live below the class — keeps the adapter
    # contract surface cleaner for subclass authors to read.)

    @staticmethod
    def _classify_content(text: str) -> ContentType:
        """Simple heuristic classification of content type."""
        lower = text.lower()

        if any(kw in lower for kw in ["decided", "decision", "let's go with", "we'll use"]):
            return ContentType.DECISION

        if any(kw in lower for kw in ["```", "def ", "class ", "function ", "import "]):
            return ContentType.CODE_SNIPPET

        if any(kw in lower for kw in ["todo", "action item", "next step", "should do"]):
            return ContentType.ACTION_ITEM

        if any(kw in lower for kw in ["prefer", "i like", "always use", "my preference"]):
            return ContentType.PREFERENCE

        if any(kw in lower for kw in ["learned", "til ", "turns out", "i discovered"]):
            return ContentType.LEARNING

        return ContentType.RAW_EXCHANGE

    @staticmethod
    def _extract_topics(text: str) -> list[str]:
        """Simple keyword-based topic extraction.

        In Phase 2, this will be replaced by LLM-powered extraction.
        """
        topics: list[str] = []
        tech_keywords = {
            "python",
            "javascript",
            "typescript",
            "react",
            "nextjs",
            "fastapi",
            "docker",
            "kubernetes",
            "postgres",
            "redis",
            "git",
            "api",
            "rest",
            "graphql",
            "css",
            "html",
            "node",
            "rust",
            "go",
            "java",
            "aws",
            "gcp",
            "azure",
            "terraform",
            "ci/cd",
            "testing",
            "machine learning",
            "ai",
            "llm",
            "embedding",
            "rag",
            "mcp",
            "langchain",
            "langgraph",
            "ollama",
            "openai",
            "anthropic",
            "gemini",
        }

        lower = text.lower()
        for keyword in tech_keywords:
            if keyword in lower:
                topics.append(keyword)

        return topics[:10]  # Cap at 10 topics

    @staticmethod
    def _merge_topics(chunks: list[ConversationChunk]) -> list[str]:
        """Merge topics from multiple chunks, deduplicated."""
        all_topics: set[str] = set()
        for chunk in chunks:
            all_topics.update(chunk.topics)
        return sorted(all_topics)[:15]


def _path_is_excluded(file_path: Path, globs: tuple[str, ...]) -> bool:
    """True when any segment of `file_path` matches any of `globs`."""
    if not globs:
        return False
    parts = file_path.parts
    for part in parts:
        for pat in globs:
            if fnmatch.fnmatch(part, pat):
                return True
    return False
