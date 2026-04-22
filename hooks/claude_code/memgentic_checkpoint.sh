#!/usr/bin/env bash
# Memgentic checkpoint hook — Claude Code Stop event.
#
# Invoked at the end of every assistant turn. Reads the JSON event Claude
# Code pipes on stdin, wraps it in the Watchers envelope, and posts it to
# the Memgentic daemon's Unix socket. Returns an empty JSON object so
# Claude Code does not block; all work happens asynchronously inside the
# daemon.
#
# Design goals:
#   * Complete in <50ms — anything expensive runs daemon-side.
#   * Never fail the agent turn on error. If the daemon is down we log
#     to stderr and exit 0; the next turn will retry.
#   * Portable: works on macOS, Linux, WSL, Git Bash. Uses only POSIX
#     shell, python3, and the socat OR python stdlib fallback to write
#     to the socket.

set -u

SOCKET_PATH="${MEMGENTIC_WATCHER_SOCKET:-}"
if [[ -z "${SOCKET_PATH}" ]]; then
    if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
        SOCKET_PATH="${XDG_RUNTIME_DIR}/memgentic/watcher.sock"
    else
        SOCKET_PATH="${HOME}/.memgentic/watcher.sock"
    fi
fi

EVENT_JSON="$(cat)"

python3 - <<'PY' "$SOCKET_PATH" "$EVENT_JSON"
import json
import os
import socket
import sys
from datetime import datetime, timezone

socket_path = sys.argv[1]
raw_event = sys.argv[2] if len(sys.argv) > 2 else "{}"

try:
    event = json.loads(raw_event) if raw_event else {}
except json.JSONDecodeError:
    event = {"raw": raw_event}

payload = {
    "schema": 1,
    "type": "checkpoint",
    "tool": "claude_code",
    "session_id": event.get("session_id") or event.get("sessionId"),
    "project_dir": event.get("cwd") or os.getcwd(),
    "event_data": event,
    "sent_at": datetime.now(timezone.utc).isoformat(),
}

try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.25)
    s.connect(socket_path)
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    try:
        s.recv(256)
    except Exception:
        pass
    s.close()
except Exception as exc:
    sys.stderr.write(f"memgentic checkpoint: {exc}\n")

print("{}")
PY
