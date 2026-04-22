"""Unix-socket receiver for Claude Code / Codex hook events.

Hooks are thin bash scripts that POST a JSON envelope to
``$XDG_RUNTIME_DIR/memgentic/watcher.sock`` (POSIX) or
``~/.memgentic/watcher.sock`` (fallback). The daemon side runs this
:class:`WatcherSocketServer` which ack's in <50ms and then dispatches the
payload asynchronously to the ingestion pipeline.

Protocol — JSON objects, newline-delimited::

    {
      "schema": 1,
      "type": "checkpoint" | "compact" | "session" | "delta",
      "tool": "claude_code" | "codex" | ...,
      "session_id": "...",
      "project_dir": "...",
      "event_data": { ... },
      "sent_at": "..."
    }

The server responds with a single JSON line::

    {"ok": true, "received_at": "...", "type": "..."}

or, on protocol error::

    {"ok": false, "error": "..."}

Windows
-------
AF_UNIX on Windows is not supported by the asyncio start_unix_server helper
across all Python versions, so on win32 we do not start the socket server
and instead log that hook-based capture is disabled. Windows users rely on
file watchers + MCP until a follow-up TCP-loopback fallback lands.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import structlog

logger = structlog.get_logger()

SOCKET_SCHEMA_VERSION = 1
SUPPORTED_EVENT_TYPES: frozenset[str] = frozenset({"checkpoint", "compact", "session", "delta"})


def default_socket_path() -> Path:
    """Return the preferred socket path.

    Prefers ``$XDG_RUNTIME_DIR/memgentic/watcher.sock`` (per XDG spec) and
    falls back to ``~/.memgentic/watcher.sock`` when the runtime dir is not
    set (macOS, minimal Linux containers, Windows).
    """
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "memgentic" / "watcher.sock"
    return Path.home() / ".memgentic" / "watcher.sock"


@dataclass(frozen=True)
class HookEvent:
    """Decoded hook payload (one per client request)."""

    schema: int
    type: str
    tool: str
    session_id: str | None
    project_dir: str | None
    event_data: dict
    sent_at: str | None

    @classmethod
    def from_json(cls, raw: bytes) -> HookEvent:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("payload must be a JSON object")
        schema = int(data.get("schema", SOCKET_SCHEMA_VERSION))
        if schema != SOCKET_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema {schema}")
        event_type = data.get("type")
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        tool = data.get("tool")
        if not isinstance(tool, str) or not tool:
            raise ValueError("missing tool")
        ev_data = data.get("event_data") or {}
        if not isinstance(ev_data, dict):
            raise ValueError("event_data must be an object")
        return cls(
            schema=schema,
            type=event_type,
            tool=tool,
            session_id=data.get("session_id"),
            project_dir=data.get("project_dir"),
            event_data=ev_data,
            sent_at=data.get("sent_at"),
        )


class EventHandler(Protocol):
    """Callback protocol for dispatching a decoded event."""

    async def __call__(self, event: HookEvent) -> None: ...


class WatcherSocketServer:
    """Asyncio Unix socket server for hook events.

    The server reads newline-delimited JSON, dispatches valid envelopes to
    the supplied handler (which typically schedules the ingestion work on a
    background task so the client can return quickly), and writes a tiny
    JSON acknowledgement.
    """

    def __init__(
        self,
        handler: EventHandler,
        *,
        socket_path: Path | None = None,
        ack_only: bool = True,
        max_bytes: int = 1_000_000,
    ) -> None:
        self._handler = handler
        self._socket_path = Path(socket_path) if socket_path else default_socket_path()
        self._ack_only = ack_only
        self._max_bytes = max_bytes
        self._server: asyncio.AbstractServer | None = None

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def is_supported(self) -> bool:
        """Unix sockets only — Windows is not supported in this version."""
        return sys.platform != "win32"

    async def start(self) -> bool:
        """Start the server.

        Returns ``True`` when the socket is bound, ``False`` on unsupported
        platforms (Windows) where we skip quietly so the daemon can still
        serve file watchers.
        """
        if not self.is_supported:
            logger.info(
                "watcher_socket.skipped_platform",
                platform=sys.platform,
                reason="AF_UNIX asyncio server not available on Windows",
            )
            return False

        # Ensure parent dir exists and stale socket is cleared.
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError as exc:
                logger.warning("watcher_socket.stale_unlink_failed", error=str(exc))

        self._server = await asyncio.start_unix_server(  # type: ignore[attr-defined]
            self._handle_client,
            path=str(self._socket_path),
        )
        # Tighten permissions (owner-only read/write) per Memgentic socket policy.
        try:
            os.chmod(self._socket_path, 0o600)
        except OSError as exc:
            logger.warning("watcher_socket.chmod_failed", error=str(exc))

        logger.info("watcher_socket.started", path=str(self._socket_path))
        return True

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._socket_path.exists():
            import contextlib as _ctx

            with _ctx.suppress(OSError):
                self._socket_path.unlink()
        logger.info("watcher_socket.stopped")

    # -- client handler ----------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readuntil(b"\n")
        except asyncio.IncompleteReadError as exc:
            raw = exc.partial
        except Exception as exc:
            logger.warning("watcher_socket.read_error", error=str(exc))
            writer.close()
            return

        if not raw:
            writer.close()
            return

        if len(raw) > self._max_bytes:
            await self._reply_error(writer, "payload too large")
            return

        try:
            event = HookEvent.from_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            await self._reply_error(writer, f"bad request: {exc}")
            return

        ack = {
            "ok": True,
            "received_at": datetime.now(UTC).isoformat(),
            "type": event.type,
            "tool": event.tool,
        }

        try:
            writer.write((json.dumps(ack) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()

        # Fire-and-forget: hook should not block on ingestion.
        try:
            if self._ack_only:
                asyncio.create_task(self._safe_handle(event))
            else:
                await self._safe_handle(event)
        except Exception as exc:  # defensive: never crash the server loop
            logger.error("watcher_socket.handler_schedule_failed", error=str(exc))

    async def _safe_handle(self, event: HookEvent) -> None:
        try:
            await self._handler(event)
        except Exception as exc:
            logger.error(
                "watcher_socket.handler_error",
                tool=event.tool,
                type=event.type,
                error=str(exc),
            )

    async def _reply_error(self, writer: asyncio.StreamWriter, message: str) -> None:
        import contextlib as _ctx

        payload = json.dumps({"ok": False, "error": message}) + "\n"
        try:
            with _ctx.suppress(Exception):
                writer.write(payload.encode("utf-8"))
                await writer.drain()
        finally:
            writer.close()


# -- helper for tests and hook scripts ------------------------------------


def encode_event(
    *,
    event_type: str,
    tool: str,
    session_id: str | None = None,
    project_dir: str | None = None,
    event_data: dict | None = None,
) -> bytes:
    """Encode a HookEvent-compatible payload. Used by tests and clients."""
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    payload = {
        "schema": SOCKET_SCHEMA_VERSION,
        "type": event_type,
        "tool": tool,
        "session_id": session_id,
        "project_dir": project_dir,
        "event_data": event_data or {},
        "sent_at": datetime.now(UTC).isoformat(),
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


HandlerFactory = Callable[[], Awaitable[None]]

__all__ = [
    "HookEvent",
    "WatcherSocketServer",
    "SOCKET_SCHEMA_VERSION",
    "SUPPORTED_EVENT_TYPES",
    "default_socket_path",
    "encode_event",
]
