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
