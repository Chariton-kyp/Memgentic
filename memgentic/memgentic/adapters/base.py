"""Base adapter interface for conversation sources."""

from __future__ import annotations

import abc
from pathlib import Path

from memgentic.models import ContentType, ConversationChunk, Platform


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

    @staticmethod
    def _safe_mtime(p: Path) -> float:
        """Return the file modification time, or ``0.0`` if the file has been deleted."""
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def discover_files(self) -> list[Path]:
        """Find all conversation files for this adapter."""
        files: list[Path] = []
        for watch_path in self.watch_paths:
            if not watch_path.exists():
                continue
            for pattern in self.file_patterns:
                files.extend(watch_path.rglob(pattern))
        return sorted(files, key=self._safe_mtime, reverse=True)

    # --- Shared utility methods ---

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
