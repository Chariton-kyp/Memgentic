# Cursor + Memgentic

Cursor supports MCP. Add Memgentic to your `~/.cursor/mcp.json`:

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

Restart Cursor. In any chat, the tools `memgentic_recall`, `memgentic_search`, and `memgentic_expand` are now available.

## Verification
Type "What did we decide about..." and Cursor should call `memgentic_recall` automatically if your `.cursorrules` includes the instruction (auto-injected by `memgentic init`).

## Capture
Cursor conversations are captured automatically by the Memgentic daemon if `memgentic daemon` is running. The Cursor adapter reads `~/.cursor/state.vscdb` in read-only mode (safe to run while Cursor is open).
