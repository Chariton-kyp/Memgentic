"""Fallback hook dispatcher for Windows (and anywhere bash isn't an option).

Usage::

    python -m memgentic.hooks.socket_post <event_type> <tool>

Reads the tool's event JSON from stdin, wraps it in the Watchers socket
envelope, and posts it to the daemon socket. Emits ``{}`` on stdout so
the hosting tool does not block.

On Windows the Memgentic daemon does not yet bind a Unix socket (see
``watcher_socket.py``), so this helper silently records the attempt and
returns success. Once a TCP-loopback fallback lands this module will
switch to that transport without the hook invocation changing.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path


def _socket_path() -> Path:
    override = os.environ.get("MEMGENTIC_WATCHER_SOCKET")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "memgentic" / "watcher.sock"
    return Path.home() / ".memgentic" / "watcher.sock"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print("{}")
        return 0
    event_type, tool = args[0], args[1]

    try:
        raw = sys.stdin.read() or "{}"
        data = json.loads(raw)
    except Exception:
        data = {}

    payload = {
        "schema": 1,
        "type": event_type,
        "tool": tool,
        "session_id": data.get("session_id") or data.get("sessionId"),
        "project_dir": data.get("cwd") or os.getcwd(),
        "event_data": data,
        "sent_at": datetime.now(UTC).isoformat(),
    }

    if sys.platform == "win32":
        # No Unix socket server on Windows yet — acknowledge and return.
        sys.stderr.write("memgentic: watcher socket not available on Windows\n")
        print("{}")
        return 0

    import contextlib as _ctx

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(str(_socket_path()))
        s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        with _ctx.suppress(Exception):
            s.recv(512)
        s.close()
    except Exception as exc:
        sys.stderr.write(f"memgentic {event_type} {tool}: {exc}\n")

    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
