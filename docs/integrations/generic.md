# Generic Tool Integration

If your AI tool isn't in the list above, you have two options:

## Option 1: Standalone context file (universal)
Enable auto-generation:
```bash
MEMGENTIC_ENABLE_CONTEXT_FILE_AUTO_UPDATE=true
memgentic daemon
```

Then configure your tool to read `.memgentic-context.md` as part of its system prompt or context.

## Option 2: MCP server (if your tool supports it)
Run the Memgentic MCP server over stdio:
```bash
memgentic serve
```

Then register the server with your tool's MCP configuration. The exact steps depend on your tool — refer to its MCP documentation.

## Adding a new adapter
To contribute capture support for a new tool, see [CONTRIBUTING.md](../../CONTRIBUTING.md#adding-an-adapter).
