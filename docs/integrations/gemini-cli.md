# Gemini CLI + Memgentic

Gemini CLI supports MCP. `memgentic init` configures it automatically by writing to `~/.gemini/settings.json`.

## Manual configuration
If `memgentic init` didn't work, add to `~/.gemini/settings.json`:
```json
{
  "mcpServers": {
    "memgentic": {
      "command": "uvx",
      "args": ["memgentic", "serve"]
    }
  }
}
```

## Session start context
Gemini CLI reads `~/.gemini/GEMINI.md` as a system prompt. `memgentic init` injects a memory-instructions block there so Gemini calls `memgentic_briefing()` and `memgentic_recall()` automatically.

If you prefer a standalone file, also enable:
```bash
MEMGENTIC_ENABLE_CONTEXT_FILE_AUTO_UPDATE=true
MEMGENTIC_CONTEXT_FILE_PATH=~/.gemini/memgentic-context.md
```
Then reference it from `GEMINI.md`.
