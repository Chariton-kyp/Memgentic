# ChatGPT + Memgentic

ChatGPT has no API for automatic context injection from local tools. The integration is import-only:

## Import ChatGPT conversations
1. Export your ChatGPT conversations from https://chat.openai.com/ (Settings → Data controls → Export data)
2. Unzip the export — you will get a `conversations.json` file
3. Run:
```bash
memgentic import-existing --source chatgpt --path /path/to/conversations.json
```

## Using ChatGPT knowledge elsewhere
Once imported, your ChatGPT conversations are searchable via `memgentic search` and accessible to Claude Code, Cursor, and other MCP-enabled tools via `memgentic_recall`. This gives you cross-tool knowledge transfer from ChatGPT to any MCP tool.
