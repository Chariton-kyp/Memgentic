"""Async event bus for Memgentic — broadcasts lifecycle events to subscribers."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class EventType(StrEnum):
    """Types of events emitted by the Memgentic system."""

    MEMORY_CREATED = "memory_created"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_DELETED = "memory_deleted"
    MEMORY_PINNED = "memory_pinned"
    IMPORT_PROGRESS = "import_progress"
    DAEMON_STATUS = "daemon_status"
    SKILL_CREATED = "skill_created"
    SKILL_UPDATED = "skill_updated"
    SKILL_DELETED = "skill_deleted"
    INGESTION_STARTED = "ingestion_started"
    INGESTION_PROGRESS = "ingestion_progress"
    INGESTION_COMPLETED = "ingestion_completed"
    COLLECTION_CREATED = "collection_created"
    COLLECTION_UPDATED = "collection_updated"
    COLLECTION_DELETED = "collection_deleted"


class MemgenticEvent(BaseModel):
    """A single event emitted by the Memgentic system."""

    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class EventBus:
    """In-process async event bus using asyncio.Queue per subscriber.

    Usage::

        bus = EventBus()

        # Producer side
        await bus.emit(MemgenticEvent(type=EventType.MEMORY_CREATED, data={"id": "..."}))

        # Consumer side (e.g. WebSocket handler)
        queue = bus.subscribe()
        try:
            event = await queue.get()
            ...
        finally:
            bus.unsubscribe(queue)
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[MemgenticEvent]] = []
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue[MemgenticEvent]:
        """Create and return a new subscriber queue."""
        queue: asyncio.Queue[MemgenticEvent] = asyncio.Queue(maxsize=256)
        self._subscribers.append(queue)
        logger.debug("event_bus.subscribe", total_subscribers=len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[MemgenticEvent]) -> None:
        """Remove a subscriber queue."""
        with contextlib.suppress(ValueError):
            self._subscribers.remove(queue)
        logger.debug("event_bus.unsubscribe", total_subscribers=len(self._subscribers))

    async def emit(self, event: MemgenticEvent) -> None:
        """Broadcast an event to all current subscribers."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("event_bus.queue_full", event_type=event.type.value)

    @property
    def subscriber_count(self) -> int:
        """Return the number of active subscribers."""
        return len(self._subscribers)


# Module-level singleton so both core and API can share the same bus.
event_bus = EventBus()
