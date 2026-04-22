# Memgentic hook scripts

These bash scripts implement the hook-based side of the **Watchers**
umbrella (the unified cross-tool automatic-capture system in Memgentic).
They are thin shims: they read the event JSON each AI tool pipes on
stdin, wrap it in the Watchers envelope, post it to the Memgentic daemon
over a Unix socket, and return a minimal JSON body so the tool keeps
moving.

## Structure

```
hooks/
├── claude_code/
│   ├── memgentic_checkpoint.sh   Stop hook (every assistant turn)
│   ├── memgentic_compact.sh      PreCompact hook (blocks ≤ 3s for capture)
│   └── memgentic_session.sh      SessionStart hook (injects briefing)
└── codex/
    ├── memgentic_checkpoint.sh   Stop hook
    └── memgentic_compact.sh      PreCompact hook
```

## Install / uninstall

These scripts are **copied** into `~/.memgentic/hooks/<tool>/` by the
unified CLI:

```bash
memgentic watchers install --tool claude_code   # idempotent
memgentic watchers install --tool codex
```

`install` also edits the tool's native settings file
(`~/.claude/settings.json`, `~/.codex/hooks.json`) to point at the
copied scripts. Running it twice is safe — the installer detects
entries containing the marker `memgentic` and skips them.

```bash
memgentic watchers uninstall --tool claude_code
```

…removes every entry the installer added and deletes
`~/.memgentic/hooks/<tool>/`.

## Socket path

Each script resolves the socket path in this order:

1. `MEMGENTIC_WATCHER_SOCKET` environment variable (absolute path)
2. `${XDG_RUNTIME_DIR}/memgentic/watcher.sock` (POSIX spec)
3. `${HOME}/.memgentic/watcher.sock` (fallback for macOS / containers)

Permissions on the socket are `0600` (owner-only read/write).

## Design

- **<50ms budget** on Stop — ack and return. The daemon does the embedding,
  dedup, and pipeline work asynchronously.
- **≤3s budget** on PreCompact — block briefly so the snapshot lands
  before compaction. Still non-fatal on error.
- **No output = no injection** for SessionStart if the daemon/briefing is
  down, so the agent's session is never broken by a memory outage.
- **Portable**: requires only `bash`, `python3`, and `socket`/`json` stdlib.
  No `curl`, no `jq`, no Node.

## Windows

Unix sockets are not used by the current bash scripts on Windows. Users on
Windows can install via Git Bash / WSL, or rely on file-watcher based
capture which runs on any platform. A native-Windows fallback
(loopback TCP + token file) is planned in a follow-up.
