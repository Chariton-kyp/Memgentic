"""File system watcher daemon — monitors CLI tool directories for new conversations."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from memgentic.adapters.base import BaseAdapter
from memgentic.config import MemgenticSettings
from memgentic.models import CaptureMethod
from memgentic.processing.pipeline import IngestionPipeline
from memgentic.skills.distributor import SkillDistributor
from memgentic.storage.metadata import MetadataStore

logger = structlog.get_logger()


class _ConversationHandler(FileSystemEventHandler):
    """Watchdog event handler that queues files for processing."""

    def __init__(
        self,
        adapter: BaseAdapter,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._adapter = adapter
        self._queue = queue
        self._loop = loop
        self._last_modified: dict[str, float] = {}

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle_event(str(event.src_path))

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle_event(str(event.src_path))

    def _enqueue(self, adapter: BaseAdapter, path: Path, src_path: str) -> None:
        """Put an item on the asyncio queue (must be called from the event loop thread)."""
        try:
            self._queue.put_nowait((adapter, path))
            logger.debug("watcher.queued", file=src_path, platform=adapter.platform.value)
        except asyncio.QueueFull:
            logger.warning("watcher.queue_full", file=src_path)

    def _handle_event(self, src_path: str) -> None:
        """Check if the file matches our patterns and queue it."""
        path = Path(src_path)

        # Check file pattern match
        matched = any(path.match(pattern) for pattern in self._adapter.file_patterns)
        if not matched:
            return

        # Debounce: only queue if not modified in last N seconds
        now = time.time()
        last = self._last_modified.get(src_path, 0)
        if now - last < 5:  # 5-second debounce
            return

        self._last_modified[src_path] = now

        # Thread-safe: schedule the put on the event loop thread
        self._loop.call_soon_threadsafe(self._enqueue, self._adapter, path, src_path)


class MemgenticDaemon:
    """Background daemon that watches for new conversations and auto-ingests them.

    Usage:
        daemon = MemgenticDaemon(settings, pipeline, adapters)
        await daemon.start()
        # ... runs until stopped
        await daemon.stop()
    """

    def __init__(
        self,
        settings: MemgenticSettings,
        pipeline: IngestionPipeline,
        adapters: list[BaseAdapter],
        *,
        metadata_store: MetadataStore | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._adapters = adapters
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._observer = Observer()
        self._running = False
        self._process_task: asyncio.Task | None = None
        self._metadata_store = metadata_store
        self._context_update_task: asyncio.Task | None = None
        self._context_dirty = False
        self._last_context_update: float = 0.0
        self._skill_sync_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start watching all adapter directories."""
        self._running = True
        loop = asyncio.get_running_loop()

        # Register file watchers for each adapter
        for adapter in self._adapters:
            handler = _ConversationHandler(adapter, self._queue, loop)
            for watch_path in adapter.watch_paths:
                if not watch_path.exists():
                    logger.info(
                        "watcher.skip_missing_path",
                        path=str(watch_path),
                        platform=adapter.platform.value,
                    )
                    continue
                self._observer.schedule(handler, str(watch_path), recursive=True)
                logger.info(
                    "watcher.watching",
                    path=str(watch_path),
                    platform=adapter.platform.value,
                )

        self._observer.start()
        self._process_task = asyncio.create_task(self._process_loop())
        if self._metadata_store and self._settings.enable_context_file_auto_update:
            self._context_update_task = asyncio.create_task(self._context_update_loop())
        if self._metadata_store and self._settings.skill_sync_interval > 0:
            self._skill_sync_task = asyncio.create_task(self._skill_sync_loop())
        logger.info("daemon.started", adapters=len(self._adapters))

    async def stop(self) -> None:
        """Stop the daemon gracefully."""
        self._running = False
        self._observer.stop()
        await asyncio.to_thread(self._observer.join)
        if self._process_task:
            self._process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._process_task
        if self._context_update_task:
            self._context_update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._context_update_task
        if self._skill_sync_task:
            self._skill_sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._skill_sync_task
        logger.info("daemon.stopped")

    async def scan_existing(self) -> int:
        """Scan and ingest all existing conversation files (initial import).

        Returns the number of files processed.
        """
        ingested = 0
        for adapter in self._adapters:
            files = adapter.discover_files()
            logger.info(
                "daemon.scan_existing",
                platform=adapter.platform.value,
                files=len(files),
            )
            for file_path in files:
                if await self._process_file(adapter, file_path):
                    ingested += 1
        return ingested

    async def _process_loop(self) -> None:
        """Main processing loop — consumes files from the queue."""
        while self._running:
            try:
                adapter, file_path = await asyncio.wait_for(
                    self._queue.get(), timeout=self._settings.idle_threshold
                )
                # Wait a bit for the file to stabilize (conversation might still be ongoing)
                await asyncio.sleep(self._settings.watch_interval)
                await self._process_file(adapter, file_path)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("daemon.process_error", error=str(e))

    async def _process_file(self, adapter: BaseAdapter, file_path: Path) -> bool:
        """Process a single conversation file through the pipeline.

        Returns ``True`` if the file was actually ingested, ``False`` otherwise.
        """
        try:
            session_id = await adapter.get_session_id(file_path)
            session_title = await adapter.get_session_title(file_path)
            chunks = await adapter.parse_file(file_path)

            if not chunks:
                return False

            memories = await self._pipeline.ingest_conversation(
                chunks=chunks,
                platform=adapter.platform,
                session_id=session_id,
                session_title=session_title,
                capture_method=CaptureMethod.AUTO_DAEMON,
                file_path=str(file_path),
            )

            # Mark context file dirty so the update loop regenerates it
            if memories:
                self._context_dirty = True

            # Emit daemon_status event on successful file processing
            if memories:
                from memgentic.events import EventType, MemgenticEvent, event_bus

                await event_bus.emit(
                    MemgenticEvent(
                        type=EventType.DAEMON_STATUS,
                        data={
                            "action": "file_processed",
                            "file_path": str(file_path),
                            "platform": adapter.platform.value,
                            "memories_created": len(memories),
                        },
                    )
                )

            return len(memories) > 0
        except Exception as e:
            logger.error(
                "daemon.file_error",
                file=str(file_path),
                platform=adapter.platform.value,
                error=str(e),
            )
            return False

    async def _context_update_loop(self) -> None:
        """Periodically regenerate the standalone .memgentic-context.md file."""
        import time as _time

        from memgentic.processing.context_generator import generate_context_file

        while self._running:
            try:
                await asyncio.sleep(self._settings.context_file_interval_seconds)
                if not self._context_dirty:
                    continue
                # Throttle: minimum 60s between writes regardless
                now = _time.monotonic()
                if now - self._last_context_update < 60.0:
                    continue
                self._context_dirty = False
                self._last_context_update = now

                output_path = Path(self._settings.context_file_path)
                ok = await generate_context_file(
                    self._metadata_store,
                    output_path,
                    hours=self._settings.context_file_hours,
                )
                if ok:
                    logger.info("daemon.context_file_updated", path=str(output_path))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("daemon.context_update_error", error=str(exc))

    async def _skill_sync_loop(self) -> None:
        """Periodically re-distribute auto-distributable skills to tool paths.

        This loop is idempotent: re-writing the same SKILL.md files is cheap
        and ensures that skills stay in sync even if a user deletes files by
        hand or installs a new AI tool after the skill was first distributed.
        """
        if self._metadata_store is None:
            return

        distributor = SkillDistributor(self._metadata_store)
        interval = max(1, int(self._settings.skill_sync_interval))

        while self._running:
            try:
                await asyncio.sleep(interval)
                skills = await self._metadata_store.get_skills()
                auto_skills = [s for s in skills if s.auto_distribute]
                if not auto_skills:
                    logger.debug("daemon.skill_sync.empty")
                    continue

                # Ensure each skill carries its files for distribution
                for skill in auto_skills:
                    if not skill.files:
                        skill.files = await self._metadata_store.get_skill_files(skill.id)

                await distributor.sync_all(auto_skills)
                logger.info(
                    "daemon.skill_sync.completed",
                    skills=len(auto_skills),
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("daemon.skill_sync_error", error=str(exc))
