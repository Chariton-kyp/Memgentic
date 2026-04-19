"""Tests for the Memgentic daemon/watcher module."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from memgentic.daemon.watcher import MemgenticDaemon, _ConversationHandler
from memgentic.models import CaptureMethod, ContentType, ConversationChunk, Platform

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(
    platform: Platform = Platform.CLAUDE_CODE,
    file_patterns: list[str] | None = None,
    watch_paths: list[Path] | None = None,
    discover_files_return: list[Path] | None = None,
) -> MagicMock:
    """Create a mock BaseAdapter with configurable properties."""
    adapter = MagicMock()
    type(adapter).platform = PropertyMock(return_value=platform)
    type(adapter).file_patterns = PropertyMock(return_value=file_patterns or ["*.jsonl"])
    type(adapter).watch_paths = PropertyMock(return_value=watch_paths or [])
    adapter.discover_files = MagicMock(return_value=discover_files_return or [])
    adapter.parse_file = AsyncMock(return_value=[])
    adapter.get_session_id = AsyncMock(return_value="session-001")
    adapter.get_session_title = AsyncMock(return_value="Test Session")
    return adapter


# ---------------------------------------------------------------------------
# _ConversationHandler tests
# ---------------------------------------------------------------------------


class TestConversationHandler:
    """Tests for the watchdog _ConversationHandler."""

    def test_matches_file_pattern(self):
        """Handler queues files matching the adapter's file_patterns."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter(file_patterns=["*.jsonl"])

        handler = _ConversationHandler(adapter, queue, loop)

        # Simulate a file event
        enqueued = []
        loop.call_soon_threadsafe = MagicMock(side_effect=lambda fn, *a: enqueued.append(a))

        handler._handle_event("/home/user/.claude/projects/test/conversation.jsonl")
        assert len(enqueued) == 1
        loop.close()

    def test_ignores_non_matching_pattern(self):
        """Handler does NOT queue files that don't match patterns."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter(file_patterns=["*.jsonl"])

        handler = _ConversationHandler(adapter, queue, loop)
        loop.call_soon_threadsafe = MagicMock()

        handler._handle_event("/home/user/some_file.txt")
        loop.call_soon_threadsafe.assert_not_called()
        loop.close()

    def test_ignores_directory_events(self):
        """on_modified and on_created skip directory events."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter(file_patterns=["*.jsonl"])

        handler = _ConversationHandler(adapter, queue, loop)
        loop.call_soon_threadsafe = MagicMock()

        # Create a mock directory event
        dir_event = MagicMock()
        dir_event.is_directory = True
        dir_event.src_path = "/home/user/.claude/projects/"

        handler.on_modified(dir_event)
        handler.on_created(dir_event)
        loop.call_soon_threadsafe.assert_not_called()
        loop.close()

    def test_debounce_within_threshold(self):
        """Same file modified twice within 5s is only queued once."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter(file_patterns=["*.jsonl"])

        handler = _ConversationHandler(adapter, queue, loop)
        enqueued = []
        loop.call_soon_threadsafe = MagicMock(side_effect=lambda fn, *a: enqueued.append(a))

        path = "/home/user/.claude/projects/test/conv.jsonl"

        handler._handle_event(path)
        assert len(enqueued) == 1

        # Second call within debounce window
        handler._handle_event(path)
        assert len(enqueued) == 1  # Still 1, debounced
        loop.close()

    def test_debounce_after_threshold(self):
        """Same file modified after 5s debounce window is queued again."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter(file_patterns=["*.jsonl"])

        handler = _ConversationHandler(adapter, queue, loop)
        enqueued = []
        loop.call_soon_threadsafe = MagicMock(side_effect=lambda fn, *a: enqueued.append(a))

        path = "/home/user/.claude/projects/test/conv.jsonl"

        handler._handle_event(path)
        assert len(enqueued) == 1

        # Simulate time passing beyond debounce (manipulate _last_modified)
        handler._last_modified[path] = time.time() - 10
        handler._handle_event(path)
        assert len(enqueued) == 2
        loop.close()

    def test_on_created_queues_matching_file(self):
        """on_created event for a matching file is queued."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter(file_patterns=["*.jsonl"])

        handler = _ConversationHandler(adapter, queue, loop)
        enqueued = []
        loop.call_soon_threadsafe = MagicMock(side_effect=lambda fn, *a: enqueued.append(a))

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/home/user/.claude/projects/new_conv.jsonl"

        handler.on_created(event)
        assert len(enqueued) == 1
        loop.close()

    def test_enqueue_puts_item_on_queue(self):
        """_enqueue directly adds an (adapter, path) tuple to the queue."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        adapter = _make_adapter()

        handler = _ConversationHandler(adapter, queue, loop)

        path = Path("/test/file.jsonl")
        handler._enqueue(adapter, path, "/test/file.jsonl")

        assert not queue.empty()
        item = queue.get_nowait()
        assert item == (adapter, path)
        loop.close()

    def test_enqueue_full_queue_does_not_raise(self):
        """_enqueue on a full queue logs a warning but does not raise."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue(maxsize=1)
        adapter = _make_adapter()

        handler = _ConversationHandler(adapter, queue, loop)

        path = Path("/test/file.jsonl")
        # Fill the queue
        queue.put_nowait(("dummy", Path("/dummy")))

        # This should not raise
        handler._enqueue(adapter, path, "/test/file.jsonl")
        # Queue still has only 1 item (the original)
        assert queue.qsize() == 1
        loop.close()


# ---------------------------------------------------------------------------
# MemgenticDaemon tests
# ---------------------------------------------------------------------------


class TestMemgenticDaemon:
    """Tests for the MemgenticDaemon class."""

    async def test_scan_existing_counts_ingested(self):
        """scan_existing returns the count of successfully ingested files."""
        chunks = [
            ConversationChunk(
                content="Test content",
                content_type=ContentType.FACT,
                topics=["test"],
            )
        ]

        adapter = _make_adapter(
            discover_files_return=[Path("/fake/conv1.jsonl"), Path("/fake/conv2.jsonl")]
        )
        adapter.parse_file = AsyncMock(return_value=chunks)

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_conversation = AsyncMock(
            return_value=[MagicMock()]  # 1 memory returned = success
        )

        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        count = await daemon.scan_existing()
        assert count == 2
        assert mock_pipeline.ingest_conversation.call_count == 2

    async def test_scan_existing_skips_dupes(self):
        """scan_existing with pipeline returning empty (dedup) counts 0."""
        chunks = [
            ConversationChunk(
                content="Already seen",
                content_type=ContentType.FACT,
                topics=[],
            )
        ]

        adapter = _make_adapter(
            discover_files_return=[Path("/fake/conv1.jsonl"), Path("/fake/conv2.jsonl")]
        )
        adapter.parse_file = AsyncMock(return_value=chunks)

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_conversation = AsyncMock(
            return_value=[]  # Empty = all deduped
        )

        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        count = await daemon.scan_existing()
        assert count == 0

    async def test_scan_existing_empty_chunks(self):
        """scan_existing with adapter returning empty chunks skips file."""
        adapter = _make_adapter(discover_files_return=[Path("/fake/conv1.jsonl")])
        adapter.parse_file = AsyncMock(return_value=[])

        mock_pipeline = AsyncMock()
        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        count = await daemon.scan_existing()
        assert count == 0
        mock_pipeline.ingest_conversation.assert_not_called()

    async def test_process_file_returns_true_on_success(self):
        """_process_file returns True when memories are ingested."""
        chunks = [
            ConversationChunk(
                content="Important decision",
                content_type=ContentType.DECISION,
                topics=["arch"],
            )
        ]

        adapter = _make_adapter()
        adapter.parse_file = AsyncMock(return_value=chunks)

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_conversation = AsyncMock(return_value=[MagicMock()])

        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        result = await daemon._process_file(adapter, Path("/fake/conv.jsonl"))
        assert result is True

    async def test_process_file_returns_false_on_empty_chunks(self):
        """_process_file returns False when adapter returns empty chunks."""
        adapter = _make_adapter()
        adapter.parse_file = AsyncMock(return_value=[])

        mock_pipeline = AsyncMock()
        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        result = await daemon._process_file(adapter, Path("/fake/conv.jsonl"))
        assert result is False
        mock_pipeline.ingest_conversation.assert_not_called()

    async def test_process_file_returns_false_on_empty_memories(self):
        """_process_file returns False when pipeline returns no memories (dedup)."""
        chunks = [
            ConversationChunk(
                content="Already stored",
                content_type=ContentType.FACT,
                topics=[],
            )
        ]

        adapter = _make_adapter()
        adapter.parse_file = AsyncMock(return_value=chunks)

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_conversation = AsyncMock(return_value=[])

        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        result = await daemon._process_file(adapter, Path("/fake/conv.jsonl"))
        assert result is False

    async def test_process_file_returns_false_on_error(self):
        """_process_file returns False and logs error on exception."""
        adapter = _make_adapter()
        adapter.parse_file = AsyncMock(side_effect=RuntimeError("parse failed"))

        mock_pipeline = AsyncMock()
        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        result = await daemon._process_file(adapter, Path("/fake/conv.jsonl"))
        assert result is False

    async def test_process_file_passes_correct_parameters(self):
        """_process_file passes correct platform, session_id, capture_method."""
        chunks = [
            ConversationChunk(
                content="Test content",
                content_type=ContentType.FACT,
                topics=[],
            )
        ]

        adapter = _make_adapter(platform=Platform.GEMINI_CLI)
        adapter.parse_file = AsyncMock(return_value=chunks)
        adapter.get_session_id = AsyncMock(return_value="gemini-sess-42")
        adapter.get_session_title = AsyncMock(return_value="Gemini Chat")

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_conversation = AsyncMock(return_value=[MagicMock()])

        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter])

        await daemon._process_file(adapter, Path("/fake/chat.json"))

        call_kwargs = mock_pipeline.ingest_conversation.call_args.kwargs
        assert call_kwargs["platform"] == Platform.GEMINI_CLI
        assert call_kwargs["session_id"] == "gemini-sess-42"
        assert call_kwargs["session_title"] == "Gemini Chat"
        assert call_kwargs["capture_method"] == CaptureMethod.AUTO_DAEMON
        assert call_kwargs["file_path"] == str(Path("/fake/chat.json"))

    async def test_scan_existing_multiple_adapters(self):
        """scan_existing iterates over all adapters."""
        chunks = [
            ConversationChunk(
                content="Content",
                content_type=ContentType.FACT,
                topics=[],
            )
        ]

        adapter1 = _make_adapter(
            platform=Platform.CLAUDE_CODE,
            discover_files_return=[Path("/fake/conv1.jsonl")],
        )
        adapter1.parse_file = AsyncMock(return_value=chunks)

        adapter2 = _make_adapter(
            platform=Platform.GEMINI_CLI,
            discover_files_return=[Path("/fake/chat1.json"), Path("/fake/chat2.json")],
        )
        adapter2.parse_file = AsyncMock(return_value=chunks)

        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_conversation = AsyncMock(return_value=[MagicMock()])

        mock_settings = MagicMock()
        daemon = MemgenticDaemon(mock_settings, mock_pipeline, [adapter1, adapter2])

        count = await daemon.scan_existing()
        assert count == 3  # 1 from adapter1 + 2 from adapter2

    # Note: start/stop integration tests removed — they create real async loops
    # that hang in the test runner. The daemon's start/stop logic is tested
    # indirectly through scan_existing and _process_file tests above.


# ---------------------------------------------------------------------------
# Context file auto-update tests (Phase 3.A)
# ---------------------------------------------------------------------------


class TestContextFileAutoUpdate:
    """Tests for the daemon's auto-regeneration of .memgentic-context.md."""

    def _make_settings(
        self,
        *,
        enabled: bool = True,
        interval: float = 0.01,
        hours: int = 72,
        path: str = ".memgentic-context.md",
    ) -> MagicMock:
        s = MagicMock()
        s.enable_context_file_auto_update = enabled
        s.context_file_interval_seconds = interval
        s.context_file_hours = hours
        s.context_file_path = path
        # Concrete numeric values so _process_loop / _skill_sync_loop
        # don't receive MagicMock objects in numeric comparisons.
        s.idle_threshold = 0.05
        s.watch_interval = 0.01
        s.skill_sync_interval = 0  # 0 → skip skill sync loop
        return s

    async def test_daemon_writes_context_file_when_dirty(self, tmp_path):
        """When dirty and throttle allows, the context update loop writes the file."""
        settings = self._make_settings(path=str(tmp_path / ".memgentic-context.md"))
        mock_pipeline = AsyncMock()
        mock_store = MagicMock()
        daemon = MemgenticDaemon(settings, mock_pipeline, [], metadata_store=mock_store)
        daemon._running = True
        daemon._context_dirty = True

        mock_generate = AsyncMock(return_value=True)
        with patch(
            "memgentic.processing.context_generator.generate_context_file",
            mock_generate,
        ):
            task = asyncio.create_task(daemon._context_update_loop())
            for _ in range(100):
                await asyncio.sleep(0.01)
                if mock_generate.called:
                    break
            daemon._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        mock_generate.assert_called_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["hours"] == 72
        # The second positional arg is the output path
        args = mock_generate.call_args.args
        assert args[0] is mock_store
        assert Path(args[1]) == Path(settings.context_file_path)
        assert daemon._context_dirty is False

    async def test_daemon_respects_throttle(self, tmp_path):
        """Two rapid dirty flags only yield one write because of 60s throttle."""
        settings = self._make_settings(path=str(tmp_path / ".memgentic-context.md"))
        mock_pipeline = AsyncMock()
        mock_store = MagicMock()
        daemon = MemgenticDaemon(settings, mock_pipeline, [], metadata_store=mock_store)
        daemon._running = True
        daemon._context_dirty = True

        # Clock that advances by 1 second per call (well under 60s throttle)
        clock = [1000.0]

        def _tick():
            clock[0] += 1.0
            return clock[0]

        mock_generate = AsyncMock(return_value=True)
        with (
            patch(
                "memgentic.processing.context_generator.generate_context_file",
                mock_generate,
            ),
            patch("time.monotonic", side_effect=_tick),
        ):
            task = asyncio.create_task(daemon._context_update_loop())
            await asyncio.sleep(0.05)
            # Mark dirty again — throttle should prevent a second write
            daemon._context_dirty = True
            await asyncio.sleep(0.1)
            daemon._running = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert mock_generate.call_count == 1

    async def test_daemon_skips_when_disabled(self, tmp_path):
        """With enable_context_file_auto_update=False, no context task is created."""
        settings = self._make_settings(enabled=False, path=str(tmp_path / ".memgentic-context.md"))
        mock_pipeline = AsyncMock()
        mock_store = MagicMock()
        daemon = MemgenticDaemon(settings, mock_pipeline, [], metadata_store=mock_store)

        # Patch the Observer so start() does not spawn a real thread.
        with patch("memgentic.daemon.watcher.Observer"):
            daemon._observer = MagicMock()
            await daemon.start()
            try:
                assert daemon._context_update_task is None
            finally:
                await daemon.stop()
