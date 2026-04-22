#!/usr/bin/env bash
# Memgentic compact hook — Codex CLI PreCompact event.
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
    "type": "compact",
    "tool": "codex",
    "session_id": event.get("session_id"),
    "project_dir": event.get("cwd") or os.getcwd(),
    "event_data": event,
    "sent_at": datetime.now(timezone.utc).isoformat(),
}

ack_ok = False
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3.0)
    s.connect(socket_path)
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    response = s.recv(1024)
    if response:
        try:
            decoded = json.loads(response.decode("utf-8"))
            ack_ok = bool(decoded.get("ok"))
        except Exception:
            pass
    s.close()
except Exception as exc:
    sys.stderr.write(f"memgentic codex compact: {exc}\n")

if ack_ok:
    print(json.dumps({
        "decision": "block",
        "reason": "Memgentic captured this conversation before compaction."
    }))
else:
    print("{}")
PY
