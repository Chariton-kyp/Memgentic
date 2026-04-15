# Aider + Memgentic

Aider does not support MCP. Use the context file approach:

## 1. Enable the context file in daemon settings
In your `.env` or environment:
```bash
MEMGENTIC_ENABLE_CONTEXT_FILE_AUTO_UPDATE=true
MEMGENTIC_CONTEXT_FILE_PATH=.memgentic-context.md
```

## 2. Run the daemon
```bash
memgentic daemon
```

The daemon will write `.memgentic-context.md` in your current directory every 5 minutes (when new memories exist).

## 3. Configure Aider to read the file
Add to `.aider.conf.yml` in your project root:
```yaml
read:
  - .memgentic-context.md
```

Or pass it per-session:
```bash
aider --read .memgentic-context.md
```

## Verification
In Aider, ask "What did we decide about the database?" — if your recent memories include a database decision, Aider will see it in context.
