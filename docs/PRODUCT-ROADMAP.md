# Memgentic Product Roadmap: Your Second Brain for AI Work

**Status:** Planning
**Date:** 2026-04-10

---

## Product Vision

Your brain doesn't organize memories into kanban columns. It works through **association, importance, and context** — recent events are vivid, important moments are reinforced, related memories cluster naturally, and the right knowledge surfaces when you need it. Memgentic should work exactly like this.

Memgentic becomes **your second brain for AI-augmented work**. It silently captures everything your AI tools learn, surfaces the right knowledge at the right moment, and lets you teach it explicitly when you want. The dashboard is not a project management tool — it's a window into your mind. You open it to see what's fresh (recent captures), what matters (pinned knowledge), what's connected (knowledge graph), and to deliberately commit new knowledge (upload, write, create skills). Everything your AI tools have ever learned, organized the way your brain would organize it — by importance, recency, association, and context.

---

## How Human Memory Maps to Memgentic

| Human Brain | Memgentic Equivalent |
|------------|---------------------|
| **Recent memories** (what happened today) | Recent captures — live feed of what the daemon captured |
| **Important memories** (core beliefs, key decisions) | Pinned memories — user-marked as critical, always visible |
| **Episodic memory** (events, conversations) | Conversation summaries from AI tools |
| **Semantic memory** (facts, knowledge) | Facts, decisions, learnings (content types) |
| **Procedural memory** (how to do things) | Skills — reusable templates for how-to knowledge |
| **Associative recall** (one memory triggers another) | Knowledge graph — entity co-occurrence, related memories |
| **Memory consolidation** (brain strengthens important memories during sleep) | Importance scoring + temporal decay + corroboration |
| **Deliberate learning** (studying, taking notes) | Manual upload — text, files, URLs |
| **Context grouping** (work vs personal, project A vs B) | Collections — user-defined groups |
| **Forgetting** (noise fades, important stuff stays) | Noise filtering + write-time dedup + archiving |

---

## User Personas

### Solo Power User ("Alex")
Senior dev using 3+ AI tools daily. Wants: see what was captured, pin the important stuff, upload project docs so every AI tool starts smarter.

### AI-Native Team Lead ("Jordan")
Leads 5-person team. Wants: team workspace with shared Skills, stop repeating discoveries. **The paying customer.**

### Knowledge Curator ("Sam")
Architect/tech writer. Wants: review, tag, organize, promote memories into Skills. Uses the dashboard daily.

### Casual User ("Casey")
Zero-config passive value. Occasionally checks what was captured. Converts to paid via team features.

---

## Feature Phases

### Phase A: Second Brain Dashboard + Manual Upload (4-6 weeks)

| Feature | Description | Complexity |
|---------|-------------|------------|
| **A1: Enhanced Dashboard** | Beautiful home with sections: Pinned, Recent, By Source, Collections sidebar. Memory cards with previews, quick actions (pin, archive, edit, tag). Powerful filtering + sorting. | M |
| **A2: Manual Upload** | "Add Knowledge" button — write text (rich editor), upload files (.md/.txt/.pdf), import URLs. This is "deliberate learning" — user teaches the system explicitly. | M |
| **A3: Collections** | User-defined groups for context (like "Project X", "Coding Standards", "Deployment Notes"). Memories can belong to multiple collections. Sidebar navigation. | M |
| **A4: Memory Editing** | Click any memory to view full detail, edit content/topics/entities inline. Re-embeds on significant changes. | S |
| **A5: Command Palette** | Cmd+K global search across memories, collections, entities. Instant recall — like your brain retrieving a memory from a cue. | S |

### Phase B: Skills + Real-time (4-6 weeks after A)

| Feature | Description | Complexity |
|---------|-------------|------------|
| **B1: Skills System** | Procedural memory — reusable multi-file knowledge templates. "How we deploy", "Code review checklist", "Project conventions". Injectable into AI tools via MCP. | L |
| **B2: Real-time Feed** | Live capture indicator, activity feed, "X memories today" counter. Your brain is always on — so is Memgentic. | S |
| **B3: Smart Suggestions** | Auto-suggest related memories when viewing one. "You might also remember..." — associative recall. | M |

### Phase C: Workspaces + Teams (6-8 weeks after B)

| Feature | Description | Complexity |
|---------|-------------|------------|
| **C1: Authentication** | Email + JWT, optional (local mode works without) | L |
| **C2: Workspaces** | Shared team brain — multi-user memory sharing | XL |
| **C3: Cloud Sync** | Local memories sync to cloud for team access | XL |

### Phase D: Desktop App (3-4 weeks, overlaps C)

| Feature | Description | Complexity |
|---------|-------------|------------|
| **D1: Electron Shell** | System tray, global Cmd+Shift+M to search, native notifications | L |

---

## Dashboard Design: The Second Brain

### Home Page (`/`)
Not a flat list. A **living dashboard** with distinct sections:

**Top Bar:**
- Search (always visible, semantic)
- "Add Knowledge" button (opens upload modal)
- Live indicator ("daemon active, 3 memories today")

**Pinned Section (top):**
- Horizontally scrollable cards of pinned memories
- These are your "core beliefs" — always visible, always accessible
- Pin/unpin with a star click

**Recent Captures (main area):**
- Reverse-chronological feed of recent memories
- Each card: content preview (3 lines), source badge, topics, confidence dot, relative time
- Quick actions on hover: pin, archive, add to collection, edit
- Click to expand full detail inline (no page navigation for quick review)

**Collections Sidebar (left):**
- "All Memories" (default view)
- "Pinned" (filtered view)
- User-created collections with icons and colors
- "Create Collection" button
- Click a collection to filter the main area

**By Source (collapsible section):**
- Grouped by platform: "Claude Code (42)", "ChatGPT (18)", "Gemini (7)"
- Click to filter

**Knowledge Graph Link:**
- "Explore connections" — opens the existing graph visualization

### Memory Detail (expandable card or `/memories/{id}`)
- Full content with markdown rendering
- Edit mode toggle (inline editing)
- Topics as editable tags
- Entities as clickable links (navigate to graph neighbors)
- Source metadata (platform, session, timestamp)
- "Related memories" section (vector similarity)
- "Add to collection" dropdown
- Pin/Archive/Delete actions

### Upload Modal (triggered by "Add Knowledge" button)
Three tabs:
- **Write**: Rich text editor (TipTap) for typing knowledge directly
- **Upload File**: Drag-and-drop zone for .md, .txt, .pdf
- **Import URL**: Paste a URL, preview extracted content
All tabs: topic selector (autocomplete), collection picker, content type dropdown

### Skills Page (`/skills`)
- Master-detail layout
- Left: skill list with search
- Right: skill content editor (markdown) with supporting files
- "Create from memories" — select memories, LLM synthesizes a skill

### Settings Page (`/settings`)
- API key management
- Daemon status
- Embedding model info
- Data export/import

---

## Go-Live Checklist (MVP)

**MVP = Phase A + B1 (Skills)**

### Must-Have
- [ ] Enhanced dashboard with Pinned, Recent, By Source sections
- [ ] Collections sidebar with create/manage
- [ ] Manual upload (text, file, URL)
- [ ] Memory editing (content, topics, entities)
- [ ] Skills (create, edit, manage, MCP injection)
- [ ] Command palette (Cmd+K)
- [ ] Real-time capture indicator
- [ ] Works smoothly with 1000+ memories
- [ ] Landing page with screenshots

### Explicitly NOT in MVP
- Authentication / accounts
- Workspaces / teams
- Cloud sync
- Desktop app
- Billing

---

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| **A** | 4-6 weeks | Dashboard + Upload + Collections + Edit + Search |
| **B** | 4-6 weeks | Skills + Real-time + Smart Suggestions |
| **MVP Launch** | — | After A + B1 |
| **C** | 6-8 weeks | Auth + Workspaces + Sync |
| **D** | 3-4 weeks | Desktop App |

**Time to MVP: 8-12 weeks.**

---

## Shipped: Memory Intelligence Upgrades

The following subsystems landed on top of Phases A + B as a single wave of work focused on **how** memory is loaded, captured, personalised, and connected. They run on top of the existing storage layer — no breaking changes to the Phase A/B APIs.

### Recall Tiers (T0–T4)

**What it is.** A structured, 5-tier progressive context loader that replaces the flat `memgentic_briefing` dump with a token-budgeted stack: **T0 Persona** (identity card), **T1 Horizon** (top memories + top skills, scored by importance × recency × pinned × cluster centrality × skill-link, selected with MMR at λ=0.5), **T2 Orbit** (collection/topic-scoped memories), **T3 Deep Recall** (hybrid semantic + FTS5 search), **T4 Atlas** (knowledge-graph traversal). Each tier has its own budget, a plain-text formatter, and a clean MCP contract; adaptive resizing keys off the target model's context window (< 32k / 32k–200k / > 200k).

**Why it matters.** Every agent session opens with a cold context. Dumping "everything" wastes tokens and dilutes relevance; dumping "nothing" forces the agent to re-discover the same facts. Tiers give the agent a small, deterministic wake-up (T0 + T1 ≤ ~900 tokens by default) while leaving deeper recall one call away. The scoring formula is transparent and configurable, so users can tune the balance between "what's important" and "what's recent" without editing code. This is what makes a "second brain" feel like a single continuous session instead of isolated chats.

- Shipped: `memgentic/briefing/` package (`tiers.py`, `scorer.py`, `token_budget.py`, `formatters.py`)
- Shipped: `memgentic briefing` CLI with `--tier`, `--collection`, `--topic`, `--model-context`, `--weights`, `--status` flags
- Shipped: tier-aware `memgentic_briefing` MCP tool (backward-compatible default = T0 + T1) and new `memgentic_tier_recall` for explicit-tier calls
- Shipped: REST `GET /api/v1/briefing` + `GET /api/v1/briefing/tiers` + `POST /api/v1/briefing/weights`

### Persona

**What it is.** A structured, versioned "who is this agent" card stored at `~/.memgentic/persona.yaml`: identity (name, role, tone, optional voice sample), people the agent knows, active projects, and `remember` / `avoid` preference lists. Pydantic-validated, YAML-diffable, atomic-written with `0600` permissions, and bootstrappable via an LLM pass over the last 100 memories with a human-confirmed diff before persistence. Consumed by Recall Tier T0 and (optionally) injected at session start by Watchers.

**Why it matters.** Cross-tool memory is only half the story; cross-tool **identity** is the other half. Without a stable persona, every tool re-asks who you are, what you prefer, and how you want to be spoken to. A structured YAML beats free-text identity strings because it's diffable (you can see exactly what changed), machine-editable (CLI, REST, dashboard all write the same file), and future-proof — `workspace_inherit: true` is the seed of Phase C team personas.

- Shipped: `memgentic/persona/` package (`schema.py`, `loader.py`, `bootstrap.py`, `defaults.py`)
- Shipped: `memgentic persona init / show / edit / validate / set / add-person / add-project` CLI
- Shipped: REST `/api/v1/persona` (GET / PUT / PATCH / bootstrap) + `/api/v1/persona/schema`
- Shipped: MCP tools `memgentic_persona_get` and `memgentic_persona_update`
- Shipped: dashboard editor at `dashboard/src/app/persona/page.tsx`

### Watchers (Cross-Tool Automatic Capture)

**What it is.** An umbrella capture system that gives each AI tool the mechanism native to it: **hooks** where the tool has a hook API (Claude Code, Codex CLI), **file watchers** where the tool writes conversations to disk (Gemini CLI, Antigravity, Aider, Copilot CLI), **MCP-mode** for agent-initiated tools (Cursor, OpenCode), and **one-shot imports** for tools with no live access (ChatGPT, Claude Web / Desktop). All paths converge on the same daemon: dedup (cosine ≥ 0.92 against recent same-session vectors) → capture-profile pipeline → store. A small Unix-socket protocol at `~/.memgentic/watcher.sock` carries hook events; a separate `~/.memgentic/watcher_state.sqlite` tracks per-file offsets so restarts never re-ingest old lines. Unified CLI (`memgentic watchers install|status|disable|uninstall --tool X`) and a dashboard page expose the whole thing.

**Why it matters.** "Universal AI memory" means nothing if capture is manual. Every tool that ships without automatic capture is a tool whose knowledge silently evaporates. Watchers treat the nine mainstream AI tools uniformly while respecting their native conventions — no tool has to change, no conversation is lost, and dedup keeps the store clean without spending LLM tokens on the decision. The Unix-socket architecture means hooks complete in < 50 ms (the daemon does the real work asynchronously), so AI-tool latency is untouched.

- Shipped: `memgentic/daemon/watcher_socket.py`, `dedup.py`, `watchers.py`, `watcher_install.py`, `watcher_state.py`
- Shipped: `memgentic/daemon/file_watchers/` (Gemini CLI, Antigravity, Aider, Copilot CLI)
- Shipped: `hooks/claude_code/` + `hooks/codex/` checkpoint / compact / session shell scripts
- Shipped: REST `/api/v1/watchers` + per-tool install / uninstall / toggle / logs
- Shipped: dashboard at `dashboard/src/app/watchers/page.tsx`
- Shipped: MCP tool `memgentic_watchers_status`

### Chronograph (Bitemporal Knowledge Graph)

**What it is.** An LLM-extracted subject / predicate / object triple store with bitemporal validity (`valid_from` / `valid_to`), confidence scoring, source-memory backlinks, and a proposed / accepted / edited / rejected review lifecycle. Lives in its own SQLite database (`~/.memgentic/chronograph.sqlite`) to isolate KG churn from the main metadata DB and to ease a later PostgreSQL move. Triples are proposed automatically at `enriched` / `dual` ingestion time and gated into "accepted" state through a dashboard validation queue. Entities are alias-aware (fuzzy-matched via rapidfuzz); predicates are normalised to `snake_case` with a vocabulary tracker to curb predicate explosion.

**Why it matters.** Co-occurrence graphs tell you which entities show up together; bitemporal triples tell you **what was true, when**. That's the difference between "Kai and Orion appear in the same docs" and "Kai worked on Orion from 2025-06 to 2026-03, then moved to Helios." With validity windows, the agent can answer "what did we decide about Orion last quarter" without getting confused by current-state writes. User validation keeps hallucinated triples out of the accepted layer. This is the data Recall Tier T4 Atlas traverses on demand.

- Shipped: `memgentic/graph/temporal.py` (entities + triples stores, `invalidate`, `timeline`, `as_of` queries)
- Shipped: `memgentic/graph/extractor.py` (LLM triple proposer, wired into `processing/intelligence.py` for enriched/dual profiles)
- Shipped: migration **9** creating the separate Chronograph SQLite with `workspace_id` columns pre-seeded for Phase C
- Shipped: REST `/api/v1/chronograph` (entities, triples, proposed queue, timeline, backfill job)
- Shipped: MCP tools `memgentic_graph_query`, `memgentic_graph_add`, `memgentic_graph_invalidate`, `memgentic_graph_timeline`, `memgentic_graph_stats`
- Shipped: dashboard at `dashboard/src/app/chronograph/page.tsx` with graph viz, validation queue, and timeline view
