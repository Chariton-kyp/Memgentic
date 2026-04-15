# Memgentic Dashboard v2 — Second Brain Design

**Status:** Planning
**Date:** 2026-04-10
**Philosophy:** Your memories, organized like your brain — by importance, recency, and association. Not a project management tool.

---

## Home Page (`/`) — The Living Dashboard

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  [Search bar]                    [+ Add Knowledge] [⚡3] │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│  All     │  ★ Pinned (horizontal scroll cards)          │
│  ─────── │  ───────────────────────────────             │
│  ★ Pinned│                                              │
│  ─────── │  Recent Captures                             │
│  Collect │  ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  ────────│  │ Memory  │ │ Memory  │ │ Memory  │        │
│  📁 Proj │  │ card    │ │ card    │ │ card    │        │
│  📁 Stds │  └─────────┘ └─────────┘ └─────────┘        │
│  📁 Docs │                                              │
│  ─────── │  ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  Sources │  │ Memory  │ │ Memory  │ │ Memory  │        │
│  ────────│  │ card    │ │ card    │ │ card    │        │
│  Claude  │  └─────────┘ └─────────┘ └─────────┘        │
│  ChatGPT │                                              │
│  Gemini  │  [Load more...]                              │
│          │                                              │
├──────────┴──────────────────────────────────────────────┤
│  Connected ● │ 247 memories │ Last capture: 2m ago      │
└─────────────────────────────────────────────────────────┘
```

### Sections

**Top Bar:**
- Search input (always visible, semantic search, debounced)
- "+ Add Knowledge" button → opens upload modal
- Live indicator: lightning bolt + "3 today" (memories captured today)

**Sidebar (left):**
- "All Memories" (default view)
- "Pinned" (filtered to pinned only)
- Divider
- Collections (user-created, with colored icons)
- "+ Create Collection" button
- Divider
- Sources (auto-grouped by platform with counts)
- Click any sidebar item → filters main area

**Pinned Row (top of main area):**
- Horizontal scrollable row of pinned memory cards
- Compact cards: content preview (2 lines), source icon, pin star
- Only shows when pinned memories exist

**Memory Grid (main area):**
- Responsive grid of memory cards (2-3 columns)
- Cards show: content preview (3 lines), source badge, topics (max 3), confidence dot, relative time
- Hover reveals: pin/unpin star, archive icon, "add to collection" button
- Click → expands inline to show full content + metadata + edit controls
- Infinite scroll with "Load more"

**Status Bar (bottom):**
- WebSocket connection status (green dot / reconnecting)
- Total memory count
- Last capture time

### Memory Card Component

```
┌──────────────────────────────────┐
│ ● Claude Code          2h ago   │  ← source badge + time
│                                  │
│ We decided to use FastAPI for    │  ← content preview (3 lines)
│ the REST API because of its      │
│ async support and automatic...   │
│                                  │
│ [python] [fastapi] [decision]    │  ← topic badges
│                           ☆ ⋮   │  ← pin star + more menu
└──────────────────────────────────┘
```

Expanded (click):
```
┌──────────────────────────────────┐
│ ● Claude Code          2h ago ✕ │
│                                  │
│ We decided to use FastAPI for    │
│ the REST API because of its      │
│ async support and automatic      │
│ OpenAPI documentation. This was  │
│ compared against Flask and       │
│ Django REST Framework.           │
│                                  │
│ Topics: [python ✕] [fastapi ✕]  │  ← editable tags
│         [+ add topic]            │
│                                  │
│ Entities: FastAPI, Flask, Django │  ← clickable → graph
│ Confidence: 92%                  │
│ Session: code-review-api-design  │
│                                  │
│ 📁 Add to collection ▾          │
│ Related: 3 similar memories →    │  ← associative recall
│                                  │
│ [Edit] [Archive] [Pin ★]        │
└──────────────────────────────────┘
```

---

## Upload Modal — "Add Knowledge" (Deliberate Learning)

Triggered by "+ Add Knowledge" button. Modal overlay, not a separate page.

### Three Tabs

**Tab 1: Write** (default)
- TipTap rich text editor with markdown support
- Placeholder: "What do you want to remember?"
- Below: topic input (autocomplete), content type dropdown, collection picker
- "Save" button

**Tab 2: Upload File**
- Drag-and-drop zone ("Drop .md, .txt, or .pdf here")
- Shows filename + size after drop
- Same metadata fields below
- "Import" button
- Large files auto-chunked

**Tab 3: Import URL**
- URL input field
- "Fetch" button → shows preview of extracted text
- Same metadata fields
- "Save" button

---

## Collections Page (`/collections/{id}`)

When a collection is selected in the sidebar, the main area filters to show only memories in that collection. Same card grid, same interactions.

Collection header shows: name, description, memory count, edit/delete buttons.

---

## Skills Page (`/skills`)

Master-detail split:
- Left panel: skill list with search, "+ Create" button
- Right panel: skill content editor (markdown), description, supporting files
- "Create from memories" — select memories, LLM synthesizes a skill draft

---

## New Components

```
src/components/
  dashboard/
    pinned-row.tsx              — horizontal scrollable pinned memories
    memory-grid.tsx             — responsive grid of memory cards
    memory-card.tsx             — card with preview + quick actions
    memory-card-expanded.tsx    — full detail view (inline expansion)
    filter-sidebar.tsx          — collections + sources sidebar
    search-bar.tsx              — always-visible semantic search
    status-bar.tsx              — connection + stats footer
    live-indicator.tsx          — "3 today" capture counter
  upload/
    upload-modal.tsx            — modal with 3 tabs
    write-tab.tsx               — TipTap rich text editor
    file-upload-tab.tsx         — drag-and-drop zone
    url-import-tab.tsx          — URL fetch + preview
    topic-input.tsx             — autocomplete tag input
    collection-picker.tsx       — dropdown to assign collection
  collections/
    collection-header.tsx       — name, description, actions
    create-collection-dialog.tsx
  skills/
    skills-page.tsx             — master-detail layout
    skill-list-item.tsx
    skill-detail.tsx
    skill-editor.tsx            — markdown editor
    file-tree.tsx               — supporting files browser
    create-skill-dialog.tsx
  activity/
    activity-feed.tsx           — real-time event sidebar
    activity-item.tsx
  common/
    command-palette.tsx         — Cmd+K global search
    confidence-dot.tsx          — colored confidence indicator
    source-badge.tsx            — platform badge with icon + color
    markdown-preview.tsx        — render markdown content
```

---

## State Management

### TanStack Query (server truth)
- Memories: `["memories", filters]`, `["memory", id]`, `["memories", "pinned"]`
- Collections: `["collections"]`, `["collection", id, "memories"]`
- Skills: `["skills"]`, `["skill", id]`
- Sources, stats, graph, topics: existing keys
- Related memories: `["memories", id, "related"]`

### Zustand (client state)
```typescript
// Dashboard store
interface DashboardState {
  activeCollection: string | null;  // null = "All Memories"
  activeSource: string | null;
  searchQuery: string;
  expandedMemoryId: string | null;
  uploadModalOpen: boolean;
}

// Activity store
interface ActivityState {
  events: ActivityEvent[];
  feedOpen: boolean;
}
```

### Local state
- Editor unsaved content
- Dialog open/close
- Scroll position

---

## New TypeScript Types

```typescript
interface Collection {
  id: string;
  name: string;
  description: string;
  color: string;
  icon: string;
  position: number;
  memory_count: number;
  created_at: string;
  updated_at: string;
}

interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  files: SkillFile[];
  auto_extracted: boolean;
  created_at: string;
  updated_at: string;
}

interface SkillFile {
  path: string;
  content: string;
}

interface ActivityEvent {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

// Memory gets new fields:
interface Memory {
  // ...existing...
  is_pinned: boolean;
  pinned_at: string | null;
}
```

---

## New Dependencies

```
@tiptap/react @tiptap/starter-kit @tiptap/extension-placeholder
zustand react-dropzone
```

**Removed:** `@dnd-kit/*` — no kanban drag-and-drop needed. Memories are organized by recency and collections, not by dragging between columns.

---

## WebSocket Enhancements

Handle typed events: `memory:created`, `memory:updated`, `memory:pinned`, `skill:created`, `ingestion:progress`. Each event invalidates the relevant Query cache. New captures trigger toast + live counter update.

---

## Migration Path

1. Install deps, add types, add API functions (no breaking changes)
2. Enhance home page: pinned row, memory grid with cards, sidebar
3. Build upload modal (write tab → file tab → URL tab)
4. Build collections (sidebar, CRUD, filtering)
5. Build command palette (Cmd+K)
6. Build skills page (requires backend API)
7. Add real-time enhancements (activity feed, live counter)
