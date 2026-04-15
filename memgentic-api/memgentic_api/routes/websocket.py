"""WebSocket endpoint for real-time event streaming."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from memgentic.events import event_bus

logger = structlog.get_logger()

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept a WebSocket connection and stream Memgentic events as JSON.

    Each message is a JSON object with ``type``, ``timestamp``, and ``data`` fields.
    The connection stays open until the client disconnects or the server shuts down.
    """
    await websocket.accept()
    queue = event_bus.subscribe()
    logger.info("websocket.connected", subscribers=event_bus.subscriber_count)

    try:
        while True:
            event = await queue.get()
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except (WebSocketDisconnect, RuntimeError):
                break
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        event_bus.unsubscribe(queue)
        logger.info("websocket.disconnected", subscribers=event_bus.subscriber_count)
