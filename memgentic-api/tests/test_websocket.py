"""Tests for the WebSocket real-time event streaming endpoint."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.events import EventBus, EventType, MemgenticEvent, event_bus
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore
from starlette.testclient import TestClient

from memgentic_api.routes import websocket


def _create_ws_app(
    metadata_store: MetadataStore,
    vector_store: VectorStore,
) -> FastAPI:
    """Build a minimal FastAPI app with the WebSocket route."""
    app = FastAPI()
    app.state.metadata_store = metadata_store
    app.state.vector_store = vector_store
    app.include_router(websocket.router, prefix="/api/v1")
    return app


@pytest.fixture
async def ws_app(tmp_path: Path):
    """Yield a FastAPI app with the WebSocket route registered."""
    settings = MemgenticSettings(
        data_dir=tmp_path / "mneme_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        embedding_dimensions=768,
    )
    metadata_store = MetadataStore(settings.sqlite_path)
    vector_store = VectorStore(settings)
    await metadata_store.initialize()
    await vector_store.initialize()

    app = _create_ws_app(metadata_store, vector_store)
    yield app

    await metadata_store.close()
    await vector_store.close()


def test_websocket_connect_and_receive(ws_app: FastAPI):
    """WebSocket client connects and receives an emitted event."""
    client = TestClient(ws_app)

    with client.websocket_connect("/api/v1/ws") as ws:
        # Emit an event on the global bus from a background thread
        import threading

        def _emit():
            import asyncio as _asyncio

            loop = _asyncio.new_event_loop()
            loop.run_until_complete(
                event_bus.emit(
                    MemgenticEvent(
                        type=EventType.MEMORY_CREATED,
                        data={"id": "test-123", "platform": "claude_code"},
                    )
                )
            )
            loop.close()

        t = threading.Thread(target=_emit)
        t.start()
        t.join()

        msg = ws.receive_json()
        assert msg["type"] == "memory_created"
        assert msg["data"]["id"] == "test-123"
        assert "timestamp" in msg


def test_websocket_disconnect_cleans_up(ws_app: FastAPI):
    """After disconnect, the subscriber is removed from the event bus."""
    client = TestClient(ws_app)
    before = event_bus.subscriber_count

    with client.websocket_connect("/api/v1/ws"):
        assert event_bus.subscriber_count == before + 1

    # After disconnect, count should be back to before
    assert event_bus.subscriber_count == before


class TestEventBus:
    """Unit tests for the EventBus."""

    @pytest.fixture
    def bus(self) -> EventBus:
        return EventBus()

    async def test_subscribe_and_emit(self, bus: EventBus):
        """Subscriber receives events that are emitted."""
        queue = bus.subscribe()
        event = MemgenticEvent(type=EventType.MEMORY_CREATED, data={"id": "mem-1"})
        await bus.emit(event)

        received = queue.get_nowait()
        assert received.type == EventType.MEMORY_CREATED
        assert received.data["id"] == "mem-1"

    async def test_unsubscribe(self, bus: EventBus):
        """After unsubscribe, the queue no longer receives events."""
        queue = bus.subscribe()
        assert bus.subscriber_count == 1
        bus.unsubscribe(queue)
        assert bus.subscriber_count == 0

    async def test_multiple_subscribers(self, bus: EventBus):
        """Multiple subscribers each receive the same event."""
        q1 = bus.subscribe()
        q2 = bus.subscribe()

        event = MemgenticEvent(type=EventType.DAEMON_STATUS, data={"action": "started"})
        await bus.emit(event)

        assert q1.get_nowait().type == EventType.DAEMON_STATUS
        assert q2.get_nowait().type == EventType.DAEMON_STATUS

    async def test_full_queue_does_not_block(self, bus: EventBus):
        """Emitting to a full queue logs warning but does not raise."""
        queue = bus.subscribe()
        # Fill the queue
        for i in range(256):
            await bus.emit(MemgenticEvent(type=EventType.MEMORY_CREATED, data={"i": i}))

        # One more should not raise
        await bus.emit(MemgenticEvent(type=EventType.MEMORY_CREATED, data={"overflow": True}))
        # Queue should still have 256 items (the overflow was dropped)
        assert queue.qsize() == 256

    async def test_unsubscribe_nonexistent(self, bus: EventBus):
        """Unsubscribing a queue that was never subscribed does not raise."""
        fake_queue: asyncio.Queue[MemgenticEvent] = asyncio.Queue()
        bus.unsubscribe(fake_queue)  # should not raise
