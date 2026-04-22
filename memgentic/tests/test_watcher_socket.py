"""Tests for the hook Unix socket server.

The asyncio Unix socket API is POSIX-only, so tests that bind a real
socket are skipped on Windows and rely instead on the static helpers
(``HookEvent.from_json`` and ``encode_event``).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from memgentic.daemon.watcher_socket import (
    SOCKET_SCHEMA_VERSION,
    SUPPORTED_EVENT_TYPES,
    HookEvent,
    WatcherSocketServer,
    default_socket_path,
    encode_event,
)


def test_encode_event_payload_shape() -> None:
    raw = encode_event(
        event_type="checkpoint",
        tool="claude_code",
        session_id="sess",
        project_dir="/tmp",
        event_data={"foo": "bar"},
    )
    data = json.loads(raw.decode("utf-8"))
    assert data["schema"] == SOCKET_SCHEMA_VERSION
    assert data["type"] == "checkpoint"
    assert data["tool"] == "claude_code"
    assert data["event_data"] == {"foo": "bar"}
    assert raw.endswith(b"\n")


def test_encode_event_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        encode_event(event_type="wat", tool="claude_code")


def test_hook_event_roundtrip() -> None:
    payload = {
        "schema": 1,
        "type": "compact",
        "tool": "codex",
        "session_id": "abc",
        "project_dir": "/home/user",
        "event_data": {"messages": []},
        "sent_at": "2026-04-21T00:00:00Z",
    }
    raw = (json.dumps(payload) + "\n").encode("utf-8")
    event = HookEvent.from_json(raw)
    assert event.type == "compact"
    assert event.tool == "codex"
    assert event.event_data == {"messages": []}


@pytest.mark.parametrize(
    "bad",
    [
        b"not json\n",
        b'{"schema": 999, "type": "checkpoint", "tool": "x"}\n',
        b'{"schema": 1, "type": "evil", "tool": "x"}\n',
        b'{"schema": 1, "type": "checkpoint"}\n',
        b'{"schema": 1, "type": "checkpoint", "tool": "x", "event_data": 42}\n',
    ],
)
def test_hook_event_rejects_malformed(bad: bytes) -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        HookEvent.from_json(bad)


def test_supported_event_types_is_frozen() -> None:
    # Hook scripts lean on these names; changing them is a breaking change.
    assert {"checkpoint", "compact", "session", "delta"} <= SUPPORTED_EVENT_TYPES


def test_default_socket_path_respects_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/tmp/xdg")
    assert default_socket_path() == Path("/tmp/xdg/memgentic/watcher.sock")

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    home_default = default_socket_path()
    assert home_default.name == "watcher.sock"


@pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX asyncio server is POSIX-only")
@pytest.mark.asyncio
async def test_socket_server_roundtrip(tmp_path: Path) -> None:
    received: list[HookEvent] = []

    async def handler(event: HookEvent) -> None:
        received.append(event)

    sock_path = tmp_path / "watcher.sock"
    server = WatcherSocketServer(handler, socket_path=sock_path)
    started = await server.start()
    assert started is True
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(encode_event(event_type="checkpoint", tool="claude_code", session_id="s"))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        ack = json.loads(line.decode("utf-8"))
        assert ack["ok"] is True
        writer.close()
        await writer.wait_closed()

        # Handler runs on a background task; give the loop a tick.
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.05)
    finally:
        await server.stop()

    assert received and received[0].type == "checkpoint"


@pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX asyncio server is POSIX-only")
@pytest.mark.asyncio
async def test_socket_server_rejects_bad_payload(tmp_path: Path) -> None:
    async def handler(event: HookEvent) -> None:  # pragma: no cover
        raise AssertionError("handler should not be called for bad payloads")

    sock_path = tmp_path / "watcher.sock"
    server = WatcherSocketServer(handler, socket_path=sock_path)
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(b"not json\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        ack = json.loads(line.decode("utf-8"))
        assert ack["ok"] is False
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only expectation")
@pytest.mark.asyncio
async def test_socket_server_skips_on_windows(tmp_path: Path) -> None:
    async def handler(event: HookEvent) -> None:  # pragma: no cover
        pass

    server = WatcherSocketServer(handler, socket_path=tmp_path / "watcher.sock")
    started = await server.start()
    assert started is False
    assert server.is_supported is False
