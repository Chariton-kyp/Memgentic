# memgentic-api

**REST API for [Memgentic](https://pypi.org/project/memgentic/)** — memory search, management, and real-time updates. Built on FastAPI + `memgentic`'s intelligence extras.

```bash
pip install memgentic-api
memgentic-api serve            # http://localhost:8100
```

## What it exposes

| Surface | Endpoints |
|---|---|
| **Memories** | CRUD, pinned, related, semantic/keyword search, batch update, topic autocomplete |
| **Collections** | User-defined groups with CRUD + membership |
| **Skills** | Agent Skills standard — create, file management, distribute to AI tools |
| **Uploads** | Text, file (.md/.txt/.pdf/.docx), URL import |
| **Persona** | Read + patch the T0 persona card |
| **Briefing** | Recall Tiers (T0–T4) rendered server-side |
| **Watchers** | Cross-tool capture install/enable/status/logs |
| **Chronograph** | Bitemporal knowledge-graph query + mutate |
| **WebSocket** | Real-time activity feed |

Full endpoint reference: [docs/API_GUIDE.md on GitHub](https://github.com/Chariton-kyp/Memgentic/blob/main/docs/API_GUIDE.md).

## Why separate from the core package?

`memgentic` (the core) is an **extractable library** — the CLI, MCP server, ingestion pipeline, and storage layer all live there with no FastAPI dependency. Installing `memgentic-api` pulls in the REST surface + the `intelligence` extras so the dashboard and external clients can hit HTTP.

For the full architecture + MCP-vs-REST trade-off, see the [root README](https://github.com/Chariton-kyp/Memgentic).

## License

Apache 2.0. See [LICENSE](https://github.com/Chariton-kyp/Memgentic/blob/main/LICENSE).
