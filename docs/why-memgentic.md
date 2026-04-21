# Why Memgentic?

This document is for people deciding whether Memgentic is the right
tool for their problem, or comparing it against alternatives. It
leans into honesty over marketing — if Memgentic isn't the right
pick, we want you to find that out before you install it.

## The problem we set out to solve

Every AI conversation is ephemeral. Close the tab and that architecture
decision, that debugging insight, that "here's how to actually use this
library" exchange — gone. Worse, knowledge is siloed per tool: what
Claude Code figured out yesterday, ChatGPT doesn't know today. What you
wrote in a long Claude Web thread stays locked there, unreadable to
your editor. Aider saves its own markdown log; Codex saves something
different; Copilot doesn't save at all.

The result is a developer who uses 3–5 AI tools per week and ends up
re-explaining context, re-discovering solutions, and re-debating the
same architectural tradeoffs, month after month.

Memgentic is a single **universal memory layer** that captures from
every AI tool you use, distills signal from noise, and exposes the
result via MCP, a REST API, and a web dashboard — so the next time
you open any AI tool, the tool can pull your prior knowledge back in.

## Who Memgentic is for

### Strong fit

- You use **2 or more AI tools regularly** (common combinations: Claude Code + ChatGPT; Cursor + Gemini CLI; Claude Desktop + Aider).
- You want your ChatGPT conversation history to become queryable alongside your Claude Code sessions.
- You care about **local-first**: code and conversations stay on your machine, no cloud required.
- You need **Apache 2.0** for enterprise / team adoption (AGPL would be a blocker).
- You want a real **web dashboard** for browsing, curating, and tagging memories — not just a search CLI.
- You care about **Skills distribution**: one well-maintained SKILL.md deployed to all 26+ AI tools that speak the Agent Skills open standard, automatically.
- You want your hot paths accelerated (credential scrubbing, noise detection, graph queries) by an **optional Rust module**.

### Weak fit

- Your workflow is predominantly **Claude Code** (optionally with Gemini CLI or OpenCode). `claude-mem` is mature in that lane, has strong momentum, and a one-line `npx claude-mem install` is hard to beat. Use it.
- You want **verbatim storage** of your conversations — every turn kept as you wrote it, retrieved semantically but never paraphrased — plus published retrieval benchmarks you can reproduce locally. That is **MemPalace**'s explicit design, not ours. Memgentic distills and deduplicates by default (different tradeoff, not necessarily better).
- You're building **AI agent backends** and need an API-first memory service with SOC 2 and managed cloud. That's Mem0, Letta, or Zep's market — not ours. Memgentic isn't intended to be a production agent memory layer for third-party apps.
- You want **hosted cloud memory** with cross-device sync today. Memgentic is local-first in v0.6.0. Cloud sync is on the conditional roadmap.

## The competitive map

### End-user cross-tool memory (Memgentic's lane)

Feature comparison verified against each project's public README in April 2026. Star counts change weekly; directional comparison only.

| Name | License | Tool scope (active capture) | Storage model | Notable strength | Notable gap (from our POV) |
|---|---|---|---|---|---|
| **Memgentic** | Apache 2.0 | 10 adapters (Claude Code, Cursor, Gemini CLI, Codex CLI, Copilot CLI, Aider, Antigravity, OpenCode) + JSON import (ChatGPT, Claude Web) | LLM-distilled summaries + dedup + noise filter | Adapter breadth, Agent-Skills-standard distribution to 26+ tools, Rust acceleration, Next.js dashboard, FastAPI REST | Pre-launch; zero stars relative to the others |
| **claude-mem** | AGPL-3.0 (+ PolyForm NC for `ragtime/`) | Claude Code (primary), Gemini CLI, OpenCode | Semantic summaries (compression) | Mature, large community, one-line install (`npx claude-mem install`), multi-language README | Copyleft license limits corporate/SaaS integration; no documented ChatGPT history import |
| **MemPalace** | MIT | Claude Code, Gemini CLI, MCP-compatible tools, local models | **Verbatim** (no summarization / paraphrase) | Temporal entity-relationship knowledge graph, 29 MCP tools, published reproducible benchmarks (96.6% R@5 raw on LongMemEval, no LLM) | No documented filesystem-based Skills distribution to 26+ tools; no documented ChatGPT history import |

### AI agent infrastructure (not our lane, different market)

| Name | License | Target | Why not a Memgentic competitor |
|---|---|---|---|
| **Mem0** | Apache 2.0 | Devs building AI agents | API memory layer for agent authors; $24M YC funding; 48K stars. Their users are different people solving a different problem. |
| **Letta (MemGPT)** | Apache 2.0 | AI agent runtime | OS-inspired 3-tier memory inside a stateful agent runtime, not a cross-tool user memory. |
| **Zep** | Apache 2.0 | Enterprise chatbots | Knowledge graph for customer-facing AI agents; $1M ARR with 5-person team — a model for what "lean AI memory business" looks like, but B2B. |

## Architectural choices and their tradeoffs

### Why a file-system watcher

The capture path is a file-system watcher over each tool's session storage directory (`~/.claude/projects/`, `~/.codex/sessions/`, `~/.gemini/tmp/*/chats/`, etc.). Some projects integrate via lifecycle hooks (installed into the host tool) or via explicit MCP writes. We picked the watcher because:

- **Adding a new tool = a new adapter class parsing that tool's log format.** No coordination with upstream tool maintainers, no lifecycle API compatibility to track.
- **Import paths are the same as live paths.** JSON export from ChatGPT or Claude Web, or an Aider markdown history file, are handled by the same adapter logic — import-time or realtime.
- **Tradeoff:** slightly more latency between a turn happening and it appearing in memory (seconds, not milliseconds). Immaterial for "I want to ask about this later"; material only if you want to inject context into the very next prompt of the same session (for that, use the Claude Code SessionStart hook + MCP).

### Why linked-versions across three packages

Memgentic ships as three PyPI packages (`memgentic`, `memgentic-api`, `memgentic-native`). They are tightly coupled — the core depends on the api surface, the api depends on the core, the native module is a drop-in accelerator for core's hot paths. Shipping them with independent versions would confuse users (`memgentic==0.4.5` + `memgentic-native==0.5.0` was our state until April 2026 and did cause issues).

release-please with `linked-versions: true` keeps all three at the same version forever. Pick a Memgentic version and all three are that version. The [release automation architecture](architecture/release-automation.md) walks through the full decision.

### Why Apache 2.0 instead of AGPL

Both are valid open-source licenses. AGPL triggers network-use copyleft: if you embed the code in a server and your users interact over the network, the AGPL requires you to provide source. That's a reasonable social contract, but it's a deal-breaker for many corporate deployments and for SaaS products wanting to build on top.

Apache 2.0 is permissive: use Memgentic in a closed-source product, modify it, redistribute — the only obligations are notice preservation and patent grant. This unlocks corporate adoption (including teams behind walls where AGPL would require legal review) without compromising open availability.

If you're picking a memory layer to embed in a commercial product, Apache is the cleaner lane.

### Why SQLite + sqlite-vec by default (zero-config)

We started with Qdrant, then added sqlite-vec, then made sqlite-vec the default in v0.6.0. Reasoning:

- Qdrant requires either running the server (extra ops) or using its embedded file mode (which has known multi-process concurrency issues).
- sqlite-vec is single-file, zero-config, multi-process safe (WAL), and has first-class Python bindings via `aiosqlite`.
- For most single-user local installs, sqlite-vec is strictly better.
- Qdrant is still fully supported for users who need server-mode scale or want to share a vector store across machines.

## Security & privacy posture

- **No telemetry.** Memgentic does not phone home. Period.
- **Local-first by default.** All data lives in `~/.memgentic/`.
- **Credential scrubbing before storage.** 15+ patterns — API keys, tokens, PEM, JWT, Stripe-style keys — redacted in the ingestion pipeline so they never hit the database even if they appear in your AI conversations.
- **Locked-down network surface.** The CLI and daemon expose no HTTP endpoint by default — the MCP server runs over stdio. The REST API and dashboard are opt-in and run only when you explicitly start them (`make api`, `make dashboard`). If you do run them, they bind to `127.0.0.1` and the schema is designed to accept token-based auth in the Phase C workspaces release.
- **OIDC Trusted Publishing.** PyPI releases use GitHub Actions OIDC, not long-lived API tokens. Every published artifact carries SLSA build provenance attestation and a CycloneDX SBOM (see [release-automation.md](architecture/release-automation.md)).

## What Memgentic is NOT

- **Not an agent runtime.** It doesn't execute actions, doesn't call tools, doesn't reason about a goal. It remembers.
- **Not a cloud product today.** v0.6.0 is local-first. Cloud sync is conditional on OSS traction.
- **Not a claude-mem or MemPalace replacement.** Both are mature, well-engineered projects with strong traction. We overlap partially but bet on different priorities — adapter breadth and Agent-Skills-standard distribution on one side, compression (claude-mem) or verbatim storage with benchmarks (MemPalace) on the other. Pick the tool whose bet matches what you need.
- **Not a silver bullet for "context length".** It is a persistent memory over conversations, not a magic way to fit 200K tokens of context into a 16K window. Recall is semantic search; it retrieves the 3–10 most relevant chunks and your AI tool decides what to do with them.

## Getting started

Return to [README.md](../README.md) for install + quick start.

## Feedback

File an issue on [GitHub](https://github.com/Chariton-kyp/Memgentic/issues) — especially if this page gave you the wrong impression about something, or if you used Memgentic for a week and want to tell us where it fell short. That signal is how this doc gets better.
