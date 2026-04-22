# Cursor + Memgentic (MCP mode)

Cursor does not (currently) expose Claude-Code-style hooks, so its entry
into the Memgentic **Watchers** umbrella is via MCP: the agent itself
calls `memgentic_remember` / `memgentic_recall` when it decides it needs
to read or write memory. Cursor is listed as `cursor` in
`memgentic watchers status` with mechanism `mcp`.

## 1. Install the Memgentic MCP server

```bash
pip install memgentic
memgentic serve --watch        # stdio transport
# or
memgentic serve --transport streamable_http --port 8200
```

## 2. Register the server with Cursor

Cursor reads MCP server configuration from
`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per-project).

Add one of the two blocks below.

### Local stdio (recommended)

```json
{
  "mcpServers": {
    "memgentic": {
      "command": "memgentic",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

### Remote HTTP

```json
{
  "mcpServers": {
    "memgentic": {
      "url": "http://localhost:8200/sse"
    }
  }
}
```

## 3. Verify

Inside Cursor's command palette, run "MCP: List servers" — `memgentic`
should appear with status "ready". You can now ask Cursor things like
"Use memgentic to recall what I decided about auth last week" and the
agent will hit the `memgentic_recall` MCP tool.

## 4. (Optional) Register with Watchers

To have Cursor show up in `memgentic watchers status` and the dashboard
with mechanism `mcp`:

```bash
# Currently MCP-mode tools are tracked by the daemon automatically as
# soon as the MCP client calls one of the tools. No install step
# required. Dashboard will display last-used time.
```

## Troubleshooting

- **"tool memgentic_recall not found"** — Check
  `memgentic watchers status`; the MCP server must be running and Cursor
  must have successfully connected. Restart Cursor after editing
  `mcp.json`.
- **Empty recalls** — Run `memgentic stats` to confirm memories exist;
  check session filters via `memgentic_configure_session`.
