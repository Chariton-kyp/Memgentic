# Tool Integration Guides

Memgentic generates a standalone `.memgentic-context.md` file that any AI tool can read as context. This directory contains setup guides for each supported tool.

## For MCP-capable tools (zero configuration needed)
These tools get automatic context via the MCP server:
- Claude Code — `memgentic init` registers the MCP server automatically
- Cursor — add to `~/.cursor/mcp.json` (see [cursor.md](cursor.md))
- Cline (VS Code) — add to Cline settings (see [cline.md](cline.md))

## For tools without MCP (context file approach)
- Aider — [aider.md](aider.md)
- Gemini CLI — [gemini-cli.md](gemini-cli.md)
- ChatGPT Desktop — [chatgpt.md](chatgpt.md)
- Generic fallback — [generic.md](generic.md)
