#!/usr/bin/env bash
# Memgentic SessionStart hook — injects the T0+T1 briefing as additional
# context at the top of a new Claude Code session.
#
# Composition:
#   1. Notifies the daemon a session started (for dashboard stats).
#   2. Calls ``memgentic briefing`` to fetch the T0+T1 digest. This
#      output is placed in Claude Code's ``hookSpecificOutput`` block so
#      Claude receives it silently at the beginning of the session. If
#      the Recall Tiers feature has not merged yet, ``memgentic briefing``
#      still exists and returns a helpful stub.

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
import subprocess
import sys
from datetime import datetime, timezone

socket_path = sys.argv[1]
raw_event = sys.argv[2] if len(sys.argv) > 2 else "{}"

try:
    event = json.loads(raw_event) if raw_event else {}
except json.JSONDecodeError:
    event = {"raw": raw_event}

# 1) Fire-and-forget notify the daemon
payload = {
    "schema": 1,
    "type": "session",
    "tool": "claude_code",
    "session_id": event.get("session_id") or event.get("sessionId"),
    "project_dir": event.get("cwd") or os.getcwd(),
    "event_data": event,
    "sent_at": datetime.now(timezone.utc).isoformat(),
}
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    s.connect(socket_path)
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    s.close()
except Exception:
    pass

# 2) Try to emit briefing as additionalContext
briefing_text = ""
try:
    result = subprocess.run(
        ["memgentic", "briefing"],
        capture_output=True,
        text=True,
        timeout=3.0,
        check=False,
    )
    if result.returncode == 0:
        briefing_text = (result.stdout or "").strip()
except Exception:
    briefing_text = ""

if not briefing_text:
    briefing_text = (
        "Memgentic briefing unavailable. Run `memgentic briefing` manually — "
        "SessionStart injection will light up once Recall Tiers lands."
    )

output = {
    "hookSpecificOutput": {
        "additionalContext": "## Memgentic Briefing\n\n" + briefing_text
    }
}
print(json.dumps(output))
PY
