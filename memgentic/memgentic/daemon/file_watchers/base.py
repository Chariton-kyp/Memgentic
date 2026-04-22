"""Base class + shared context for Watcher-managed file watchers.

Each concrete watcher is responsible for:

1. Declaring which directories to subscribe to (``watch_dirs``) and which
   file pattern(s) to care about (``patterns``).
2. Translating a *delta* (new bytes) from a single file into a list of
   :class:`ConversationChunk` objects via :meth:`parse_delta`.
3. Telling the orchestrator the session ID + adapter to use for
   downstream ingestion.

Everything else — debouncing, offset bookkeeping, dedup, and pipeline
dispatch — lives in this base so each new tool needs only ~50 lines of
glue.
"""

from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.config import MemgenticSettings
from memgentic.models import CaptureMethod, CaptureProfile, ConversationChunk, Platform

if TYPE_CHECKING:  # pragma: no cover
    from memgentic.daemon.dedup import SemanticDeduper
    from memgentic.daemon.watcher_state import WatcherStateStore
    from memgentic.processing.pipeline import IngestionPipeline

logger = structlog.get_logger()

DEFAULT_DEBOUNCE_SECONDS = 0.5


@dataclass
class WatcherContext:
    """Injected collaborators each file watcher needs.

    Kept as a plain dataclass so the constructor signature for concrete
    watchers stays short — a single ``ctx`` argument.
    """

    settings: MemgenticSettings
    pipeline: IngestionPipeline
    deduper: SemanticDeduper
    state_store: WatcherStateStore
    capture_profile: CaptureProfile | None = None
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS
    extra_watch_paths: list[Path] = field(default_factory=list)


@dataclass
class DeltaPayload:
    """Result of parsing a file's delta.

    ``new_offset`` is the byte offset the watcher should persist so the
    next read picks up where this one ended. When ``chunks`` is empty the
    orchestrator still persists the offset (skipping trivial appends).
    """

    chunks: list[ConversationChunk]
    new_offset: int
    session_id: str | None
    session_title: str | None = None


class BaseFileWatcher(abc.ABC):
    """Abstract file watcher integrated with the Watchers state/dedup layer.

    Subclasses implement :meth:`watch_dirs`, :meth:`patterns`,
    :meth:`adapter`, and :meth:`parse_delta`. Everything else is provided:
    ``process_file`` walks the offset bookkeeping, dedup, and pipeline
    call; ``enabled`` is the toggle flag read from
    ``watcher_status.enabled``.
    """

    tool: str = "unknown"
    platform: Platform = Platform.UNKNOWN

    def __init__(self, ctx: WatcherContext) -> None:
        self._ctx = ctx
        self._adapter = self.adapter()
        self._last_fire: dict[str, float] = {}

    # -- subclass contract -------------------------------------------------

    @abc.abstractmethod
    def watch_dirs(self) -> list[Path]:
        """Directories to subscribe to for this tool."""

    @abc.abstractmethod
    def patterns(self) -> list[str]:
        """Glob patterns identifying conversation files."""

    @abc.abstractmethod
    def adapter(self) -> BaseAdapter:
        """Adapter used to parse whole files / fall back when delta parse fails."""

    @abc.abstractmethod
    async def parse_delta(
        self,
        file_path: Path,
        last_offset: int,
    ) -> DeltaPayload | None:
        """Parse new content from ``last_offset`` to EOF.

        Return ``None`` when the delta is not ready (partial write, empty
        file) so the orchestrator can retry later without advancing the
        offset.
        """

    # -- orchestrator API --------------------------------------------------

    @property
    def debounce_seconds(self) -> float:
        return self._ctx.debounce_seconds

    def should_fire(self, file_path: Path) -> bool:
        """Return ``True`` when enough time has passed since the last fire.

        The orchestrator also applies its own debouncing; this extra guard
        handles the hot-loop case where watchdog emits many ``modified``
        events within a single write.
        """
        key = str(file_path)
        now = time.monotonic()
        last = self._last_fire.get(key, 0.0)
        if now - last < self.debounce_seconds:
            return False
        self._last_fire[key] = now
        return True

    async def process_file(self, file_path: Path) -> int:
        """Process a single file change.

        Returns the number of memories created (useful for tests).
        """
        # Respect user-level excludes (e.g. MEMGENTIC_EXCLUDE_PATHS).
        if self._adapter.is_excluded(file_path):
            return 0

        session_id = await self._adapter.get_session_id(file_path) or file_path.stem
        file_key = str(file_path.resolve())
        last_offset = self._ctx.state_store.get_offset(self.tool, session_id, file_key)

        try:
            delta = await self.parse_delta(file_path, last_offset)
        except FileNotFoundError:
            # File was rotated away between events — drop the state.
            self._ctx.state_store.reset_file(self.tool, session_id, file_key)
            return 0
        except Exception as exc:
            logger.error(
                "file_watcher.parse_error",
                tool=self.tool,
                file=file_key,
                error=str(exc),
            )
            self._ctx.state_store.record_error(self.tool, f"parse: {exc}")
            return 0

        if delta is None:
            return 0

        # Honour the persisted enabled flag — watchers registered in the
        # state store with enabled=False still get file events but do
        # nothing — disable preserves the install but stops capturing.
        status = self._ctx.state_store.get_status(self.tool)
        if status is not None and not status.enabled:
            self._ctx.state_store.update_state(
                tool=self.tool,
                session_id=session_id,
                file_path=file_key,
                new_offset=delta.new_offset,
                captured_increment=0,
            )
            return 0

        memories_created = 0
        if delta.chunks:
            kept, decisions = await self._ctx.deduper.filter_chunks(
                delta.chunks,
                platform=self.platform,
                session_id=session_id,
            )
            skipped = sum(1 for d in decisions if d.skip)
            if skipped:
                self._ctx.state_store.append_log(
                    self.tool,
                    f"dedup skipped {skipped}/{len(decisions)} chunks in session {session_id}",
                )
            if kept:
                memories = await self._ctx.pipeline.ingest_conversation(
                    chunks=kept,
                    platform=self.platform,
                    session_id=session_id,
                    session_title=delta.session_title,
                    capture_method=CaptureMethod.AUTO_DAEMON,
                    file_path=file_key,
                    capture_profile=self._ctx.capture_profile,
                )
                memories_created = len(memories)
                if memories_created:
                    self._ctx.state_store.append_log(
                        self.tool,
                        f"ingested {memories_created} memory/memories from {file_path.name}",
                    )

        self._ctx.state_store.update_state(
            tool=self.tool,
            session_id=session_id,
            file_path=file_key,
            new_offset=delta.new_offset,
            captured_increment=memories_created,
        )
        return memories_created

    # -- delta helpers -----------------------------------------------------

    async def read_new_bytes(self, file_path: Path, last_offset: int) -> bytes:
        """Read ``file_path`` starting at ``last_offset``.

        Returns ``b""`` when the file shrank or does not exist (rotation).
        Callers must decide whether to reset the offset based on the
        returned length vs. ``last_offset``.
        """

        def _read() -> bytes:
            try:
                size = file_path.stat().st_size
            except OSError:
                return b""
            if size <= last_offset:
                return b""
            with open(file_path, "rb") as fh:
                fh.seek(last_offset)
                return fh.read()

        return await asyncio.to_thread(_read)


__all__ = [
    "BaseFileWatcher",
    "DeltaPayload",
    "WatcherContext",
    "DEFAULT_DEBOUNCE_SECONDS",
]
