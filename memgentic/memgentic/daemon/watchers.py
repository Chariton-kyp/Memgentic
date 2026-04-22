"""Watchers orchestrator — brings up hook socket + file watchers.

The orchestrator is the top-level entry point for the Watchers umbrella.
It is intentionally separate from the existing :class:`MemgenticDaemon`
(``memgentic/daemon/watcher.py``) so both can co-exist during rollout.

Design
------
* Reads the Watcher registry for all tools with ``file-watcher`` mechanism
  and brings up watchdog observers for their directories.
* Starts the Unix socket server so hook-based tools (Claude Code, Codex)
  can post events.
* Tracks per-tool enable state through :class:`WatcherStateStore` and
  ignores events for disabled tools at dispatch time (keeping the install
  on disk intact — "disable keeps install but stops capturing").

The orchestrator does **not** scan existing files on startup — that's the
old daemon's job. New file watchers only pick up content appended *after*
the watcher starts, which matches the "no double capture" constraint for
tools already served by :class:`MemgenticDaemon`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Iterable
from pathlib import Path

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from memgentic.config import MemgenticSettings
from memgentic.daemon.dedup import DEFAULT_SKIP_THRESHOLD, SemanticDeduper
from memgentic.daemon.file_watchers import FILE_WATCHERS, BaseFileWatcher, WatcherContext
from memgentic.daemon.watcher_socket import HookEvent, WatcherSocketServer
from memgentic.daemon.watcher_state import WatcherStateStore
from memgentic.processing.embedder import Embedder
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.storage.vectors import VectorStore

logger = structlog.get_logger()

# Tool classification — matches the capture-mechanism matrix documented in
# hooks/README.md and the integrations/ directories.
HOOK_TOOLS: frozenset[str] = frozenset({"claude_code", "codex"})
MCP_TOOLS: frozenset[str] = frozenset({"cursor", "opencode"})
IMPORT_TOOLS: frozenset[str] = frozenset({"chatgpt", "claude_web"})
FILE_WATCHER_TOOLS: frozenset[str] = frozenset(FILE_WATCHERS.keys())

ALL_TOOLS: tuple[str, ...] = tuple(
    sorted(HOOK_TOOLS | MCP_TOOLS | IMPORT_TOOLS | FILE_WATCHER_TOOLS)
)


def classify_tool(tool: str) -> str:
    """Return the tool's capture mechanism or ``"unknown"``."""
    if tool in HOOK_TOOLS:
        return "hook"
    if tool in FILE_WATCHER_TOOLS:
        return "file_watcher"
    if tool in MCP_TOOLS:
        return "mcp"
    if tool in IMPORT_TOOLS:
        return "import"
    return "unknown"


class _FileWatchHandler(FileSystemEventHandler):
    """Debounced adapter between watchdog callbacks and the orchestrator."""

    def __init__(
        self,
        watcher: BaseFileWatcher,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[tuple[BaseFileWatcher, Path]],
    ) -> None:
        self._watcher = watcher
        self._loop = loop
        self._queue = queue
        self._last_dispatch: dict[str, float] = {}

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._maybe_enqueue(Path(str(event.src_path)))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._maybe_enqueue(Path(str(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # File rotation: re-bind by handling the destination path.
        dest = Path(str(getattr(event, "dest_path", "")))
        if dest:
            self._maybe_enqueue(dest)

    def _maybe_enqueue(self, path: Path) -> None:
        # Match against the watcher's declared patterns — watchdog delivers
        # every change under the subscribed directory.
        if not any(path.match(pattern) for pattern in self._watcher.patterns()):
            return

        now = time.monotonic()
        key = str(path)
        last = self._last_dispatch.get(key, 0.0)
        if now - last < self._watcher.debounce_seconds:
            return
        self._last_dispatch[key] = now

        self._loop.call_soon_threadsafe(self._put, path)

    def _put(self, path: Path) -> None:
        try:
            self._queue.put_nowait((self._watcher, path))
        except asyncio.QueueFull:
            logger.warning("watchers.queue_full", file=str(path))


class WatchersOrchestrator:
    """Run the hook socket + all enabled file watchers in one event loop."""

    def __init__(
        self,
        settings: MemgenticSettings,
        pipeline: IngestionPipeline,
        vector_store: VectorStore,
        embedder: Embedder,
        *,
        state_store: WatcherStateStore | None = None,
        dedup_threshold: float = DEFAULT_SKIP_THRESHOLD,
        extra_aider_paths: Iterable[Path] | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._vector_store = vector_store
        self._embedder = embedder
        self._state_store = state_store or WatcherStateStore()
        self._deduper = SemanticDeduper(embedder, vector_store, threshold=dedup_threshold)
        self._extra_aider_paths = [Path(p) for p in (extra_aider_paths or [])]

        self._observer: Observer | None = None
        self._queue: asyncio.Queue[tuple[BaseFileWatcher, Path]] = asyncio.Queue(maxsize=2000)
        self._watchers: list[BaseFileWatcher] = []
        self._socket: WatcherSocketServer | None = None
        self._process_task: asyncio.Task | None = None
        self._running = False

    @property
    def state_store(self) -> WatcherStateStore:
        return self._state_store

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_running_loop()

        self._observer = Observer()
        self._watchers = []

        ctx = WatcherContext(
            settings=self._settings,
            pipeline=self._pipeline,
            deduper=self._deduper,
            state_store=self._state_store,
            extra_watch_paths=self._extra_aider_paths,
        )

        for tool, factory in FILE_WATCHERS.items():
            status = self._state_store.get_status(tool)
            # Default-disabled: only run when the user explicitly installed.
            if status is None or not status.enabled:
                continue
            try:
                watcher = factory(ctx)
            except Exception as exc:
                logger.warning("watchers.instantiate_failed", tool=tool, error=str(exc))
                self._state_store.record_error(tool, f"init: {exc}")
                continue

            for path in watcher.watch_dirs():
                if not path.exists():
                    logger.info(
                        "watchers.skip_missing_path",
                        tool=tool,
                        path=str(path),
                    )
                    continue
                handler = _FileWatchHandler(watcher, loop, self._queue)
                self._observer.schedule(handler, str(path), recursive=True)
                logger.info("watchers.subscribed", tool=tool, path=str(path))
            self._watchers.append(watcher)

        if self._observer and self._observer.emitters:
            self._observer.start()

        self._socket = WatcherSocketServer(self._dispatch_hook_event)
        await self._socket.start()

        self._process_task = asyncio.create_task(self._process_loop())
        logger.info(
            "watchers.started",
            file_watchers=len(self._watchers),
            socket=self._socket.is_supported,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._observer is not None:
            self._observer.stop()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._observer.join)
            self._observer = None
        if self._socket is not None:
            await self._socket.stop()
            self._socket = None
        if self._process_task is not None:
            self._process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._process_task
            self._process_task = None
        logger.info("watchers.stopped")

    # -- dispatch loops ----------------------------------------------------

    async def _process_loop(self) -> None:
        while self._running:
            try:
                watcher, path = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if not watcher.should_fire(path):
                continue

            try:
                await watcher.process_file(path)
            except Exception as exc:
                logger.error(
                    "watchers.process_failed",
                    tool=watcher.tool,
                    file=str(path),
                    error=str(exc),
                )
                self._state_store.record_error(watcher.tool, f"process: {exc}")

    async def _dispatch_hook_event(self, event: HookEvent) -> None:
        """Handle an incoming hook socket event.

        For ``checkpoint`` / ``compact`` / ``delta`` we extract the message
        list from ``event_data`` and run it through dedup + pipeline. For
        ``session`` we simply record the event in the log store and let the
        installed Python hook inject the briefing.
        """
        status = self._state_store.get_status(event.tool)
        if status is None or not status.enabled:
            self._state_store.append_log(
                event.tool,
                f"ignored {event.type} event (watcher not enabled)",
                level="debug",
            )
            return

        self._state_store.append_log(
            event.tool, f"received {event.type} event (session={event.session_id})"
        )

        if event.type == "session":
            # SessionStart — nothing to ingest; the Python hook handles the
            # briefing injection. We just stamp the log so the dashboard
            # shows the session happened.
            return

        messages = event.event_data.get("last_n_messages") or []
        if not isinstance(messages, list) or not messages:
            return

        from memgentic.models import ConversationChunk

        chunks: list[ConversationChunk] = []
        buffer: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "")).lower()
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if role == "user":
                _flush_hook_buffer(buffer, chunks)
                buffer.append(f"Human: {content}")
            else:
                buffer.append(f"Assistant: {content}")
        _flush_hook_buffer(buffer, chunks)

        if not chunks:
            return

        platform = _tool_to_platform(event.tool)
        kept, _ = await self._deduper.filter_chunks(
            chunks, platform=platform, session_id=event.session_id
        )
        if not kept:
            self._state_store.append_log(event.tool, "dedup dropped all chunks from hook event")
            return

        from memgentic.models import CaptureMethod

        memories = await self._pipeline.ingest_conversation(
            chunks=kept,
            platform=platform,
            session_id=event.session_id,
            session_title=event.event_data.get("session_title"),
            capture_method=CaptureMethod.HOOK,
        )
        self._state_store.append_log(
            event.tool,
            f"ingested {len(memories)} memory/memories from {event.type} hook",
        )

        # Update captured_count so the dashboard shows throughput even
        # though hooks don't use a file-offset cursor.
        self._state_store.update_state(
            tool=event.tool,
            session_id=event.session_id or "unknown",
            file_path=f"hook:{event.type}",
            new_offset=0,
            captured_increment=len(memories),
        )


def _flush_hook_buffer(buffer: list[str], out: list) -> None:
    if not buffer:
        return
    from memgentic.models import ContentType, ConversationChunk

    text = "\n\n".join(buffer)
    if len(text) >= 50:
        out.append(
            ConversationChunk(
                content=text,
                content_type=ContentType.RAW_EXCHANGE,
                topics=[],
                entities=[],
                confidence=0.9,
            )
        )
    buffer.clear()


def _tool_to_platform(tool: str):
    from memgentic.models import Platform

    mapping = {
        "claude_code": Platform.CLAUDE_CODE,
        "codex": Platform.CODEX_CLI,
        "gemini_cli": Platform.GEMINI_CLI,
        "antigravity": Platform.ANTIGRAVITY,
        "aider": Platform.AIDER,
        "copilot_cli": Platform.COPILOT_CLI,
        "cursor": Platform.CURSOR,
        "opencode": Platform.CUSTOM,
        "chatgpt": Platform.CHATGPT,
        "claude_web": Platform.CLAUDE_WEB,
    }
    return mapping.get(tool, Platform.UNKNOWN)


__all__ = [
    "WatchersOrchestrator",
    "HOOK_TOOLS",
    "MCP_TOOLS",
    "IMPORT_TOOLS",
    "FILE_WATCHER_TOOLS",
    "ALL_TOOLS",
    "classify_tool",
]
