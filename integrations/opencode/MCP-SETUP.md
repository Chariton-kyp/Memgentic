# OpenCode + Memgentic (MCP mode)

OpenCode is MCP-native; its entry into the Memgentic **Watchers** umbrella
is the shared `memgentic` MCP server. OpenCode is listed as `opencode` in
`memgentic watchers status` with mechanism `mcp`.

## 1. Install the Memgentic MCP server

```bash
pip install memgentic
memgentic serve --watch
```

## 2. Register the server with OpenCode

OpenCode loads MCP server configuration from
`~/.config/opencode/mcp.json` (per Agent Skills standard).

```json
{
  "mcpServers": {
    "memgentic": {
      "command": "memgentic",
      "args": ["serve"]
    }
  }
}
```

## 3. Verify

In an OpenCode session:

```text
/mcp list
```

`memgentic` should appear with its 12+ tools (`memgentic_recall`,
`memgentic_remember`, `memgentic_watchers_status`, ...).

## 4. Usage

OpenCode agents can now call memory tools directly:

```text
@memgentic_recall "yesterday's decision about deployment"
@memgentic_remember "We chose Fly.io over Railway for the backend."
```

## Notes

- Memory captured via MCP carries `capture_method = "mcp_tool"` — visible
  in `memgentic sources` and the dashboard.
- OpenCode does not have native Stop / PreCompact hooks, so there is no
  background hook-based capture; rely on the agent to call
  `memgentic_remember` at end-of-task.
