# memgentic

**Universal AI memory layer** — zero-effort knowledge capture across every AI tool you use. Source-aware memory with semantic search, filtering, and knowledge graphs.

`memgentic` is the **core engine**. Install it to get the CLI, the MCP server, the ingestion pipeline, and the storage layer.

```bash
pip install memgentic
# or with the REST API:
pip install 'memgentic-api'
# or with native Rust acceleration:
pip install 'memgentic[native]'
```

## What it does

Every AI conversation is ephemeral — knowledge is lost when the session ends. Worse, it's siloed: what Claude knows, ChatGPT doesn't. `memgentic` captures knowledge automatically from every AI tool you use and makes it available everywhere via MCP.

- **Local-first.** Data stays on your machine. Works offline.
- **Source-aware.** Every memory carries provenance: which tool, which session, which timestamp.
- **Semantic search.** Qwen3-Embedding-0.6B via Ollama, 768-dim, Apache 2.0.
- **Recall Tiers (T0–T4).** Progressive context loader — persona, horizon, orbit, deep, atlas.
- **Watchers.** Auto-capture from Claude Code, Codex CLI, Gemini CLI, Copilot CLI, Aider, Antigravity, ChatGPT/Claude web imports, Cursor, Windsurf.
- **Chronograph.** Bitemporal knowledge graph — entities, relationships, validity windows.
- **27 MCP tools.** Full surface exposed via the MCP protocol for any compatible client.

## Quick start

```bash
# One-shot setup (detects installed AI tools, configures models, installs hooks)
memgentic init

# Run the MCP server + the file watcher in one process
memgentic serve --watch

# Semantic search from the CLI
memgentic search "react performance tips"

# Manual store
memgentic remember "Fixed JWT expiry bug: iat claim was missing"
```

See the [project README on GitHub](https://github.com/Chariton-kyp/Memgentic) for architecture, full feature matrix, MCP tool reference, and benchmarks.

## License

Apache 2.0. See [LICENSE](https://github.com/Chariton-kyp/Memgentic/blob/main/LICENSE).
