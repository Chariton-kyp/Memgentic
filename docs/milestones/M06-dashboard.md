# M6: Web Dashboard

> Full-featured Next.js dashboard for browsing, searching, and managing memories.

**Prerequisites:** M3 (REST API), M5 (Intelligence — for graph and analytics data)
**Estimated complexity:** High
**Exit criteria:** Dashboard fully functional, connected to REST API, all pages working with real data.

---

## Phase 6.1: Project Setup

**Goal:** Initialize Next.js 16 project with full toolchain.

### Tasks

1. **Create Next.js 16 project in `dashboard/`:**
   ```bash
   npx create-next-app@latest dashboard \
     --typescript --tailwind --eslint --app --src-dir \
     --import-alias "@/*" --turbopack
   ```
   This gives us: Next.js 16.2+, React 19.2+, Tailwind CSS 4.2+, Turbopack (default stable bundler).

2. **Install core dependencies:**
   ```bash
   npm install @tanstack/react-query@latest @tanstack/react-query-devtools@latest
   npm install react-hook-form@latest @hookform/resolvers@latest zod@latest
   npm install date-fns@latest lucide-react@latest recharts@latest
   npm install react-force-graph-2d@latest next-themes@latest
   ```
   Target versions: TanStack Query 5.95+, Recharts 3.8+, Zod 4.3+, Lucide 1.6+, date-fns 4.1+.

3. **Initialize shadcn/ui:**
   ```bash
   npx shadcn@latest init
   npx shadcn@latest add button card input table badge tabs
   npx shadcn@latest add dialog dropdown-menu select separator
   npx shadcn@latest add sheet sidebar skeleton toast command
   ```

4. **Create project structure:**
   ```
   dashboard/src/
   ├── app/
   │   ├── layout.tsx         # Root layout with providers
   │   ├── page.tsx           # Home → Memory Browser
   │   ├── memories/[id]/page.tsx
   │   ├── sources/page.tsx
   │   ├── graph/page.tsx
   │   ├── timeline/page.tsx
   │   ├── analytics/page.tsx
   │   └── settings/page.tsx
   ├── components/
   │   ├── ui/                # shadcn components
   │   ├── layout/
   │   │   ├── app-sidebar.tsx
   │   │   ├── header.tsx
   │   │   └── nav-user.tsx
   │   ├── memory/
   │   │   ├── memory-card.tsx
   │   │   ├── memory-list.tsx
   │   │   ├── memory-detail.tsx
   │   │   ├── search-bar.tsx
   │   │   └── filter-panel.tsx
   │   ├── graph/
   │   │   └── knowledge-graph.tsx
   │   └── charts/
   │       ├── timeline-chart.tsx
   │       └── source-chart.tsx
   ├── lib/
   │   ├── api.ts             # API client (fetch wrapper)
   │   ├── types.ts           # TypeScript types matching API schemas
   │   ├── utils.ts           # Utility functions
   │   └── constants.ts       # Platform colors, icons, etc.
   └── hooks/
       ├── use-memories.ts    # TanStack Query hooks
       ├── use-sources.ts
       └── use-search.ts
   ```

5. **Configure API client:**
   ```typescript
   // lib/api.ts
   const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100/api/v1";

   export const api = {
     memories: {
       list: (params) => fetch(`${API_BASE}/memories?${qs}`),
       get: (id) => fetch(`${API_BASE}/memories/${id}`),
       search: (body) => fetch(`${API_BASE}/memories/search`, { method: 'POST', body }),
       // ...
     },
     sources: { ... },
     stats: { ... },
   };
   ```

6. **Set up TanStack Query provider in root layout**

### Acceptance Criteria
- [ ] `npm run dev` starts the dashboard
- [ ] shadcn/ui components available
- [ ] API client configured and typed
- [ ] TanStack Query provider set up

---

## Phase 6.2: Layout & Navigation

**Goal:** App shell with sidebar navigation, responsive design.

### Tasks

1. **Create sidebar navigation using shadcn Sidebar component:**
   - Logo + app name at top
   - Nav items: Memories, Sources, Graph, Timeline, Analytics, Settings
   - Platform icons for each nav item (Lucide icons)
   - Collapsible on mobile

2. **Create header:**
   - Global search bar (command palette style — shadcn Command)
   - Notification bell (future)
   - User menu (future, for cloud)

3. **Set up dark mode:**
   - next-themes for theme toggling
   - Toggle in header

4. **Design system:**
   - Platform color mapping (Claude=orange, ChatGPT=green, Gemini=blue, etc.)
   - Consistent spacing and typography

### Acceptance Criteria
- [ ] Sidebar navigation works
- [ ] Responsive on mobile
- [ ] Dark mode toggle
- [ ] All routes accessible from nav

---

## Phase 6.3: Memory Browser (Home Page)

**Goal:** Main memory browsing experience with search, filters, and results.

### Tasks

1. **Search bar** (prominent, at top):
   - Semantic search by default
   - Toggle to keyword search
   - Debounced input (300ms)

2. **Filter panel** (sidebar or dropdown):
   - Source platform multi-select (with platform icons/colors)
   - Content type filter (decision, code, fact, etc.)
   - Date range picker
   - Confidence slider
   - Status filter (active, archived)

3. **Results list:**
   - Memory cards showing: content preview, platform badge, type badge, topics, date, score
   - Infinite scroll or pagination
   - Sort: relevance, date (newest/oldest), access count

4. **Empty states:**
   - No memories yet → "Import your first conversations"
   - No search results → "Try a different query"

5. **Quick actions on each card:**
   - View detail, archive, copy content

### Acceptance Criteria
- [ ] Can search and get results
- [ ] Filters work and combine
- [ ] Results paginate smoothly
- [ ] Platform badges show correct colors/icons

---

## Phase 6.4: Memory Detail View

**Goal:** Full memory view with metadata and related content.

### Tasks

1. **Full content display** with syntax highlighting for code blocks
2. **Metadata panel:** platform, capture method, session, date, confidence, topics, entities
3. **Related memories** section (semantic similarity)
4. **Actions:** archive, delete, edit topics/entities, copy
5. **Breadcrumb navigation** back to search results

### Acceptance Criteria
- [ ] Full content rendered with markdown/code highlighting
- [ ] All metadata displayed
- [ ] Related memories shown
- [ ] Actions work

---

## Phase 6.5: Source Overview

**Goal:** Per-platform statistics and health dashboard.

### Tasks

1. **Source cards** for each platform:
   - Platform icon and name
   - Memory count + percentage of total
   - Last ingestion timestamp
   - Adapter health status (watching/not watching/error)

2. **Source detail** (click a card):
   - Memory count over time chart
   - Top topics from this source
   - Recent memories from this source
   - Connection health / file paths being watched

3. **Overall source distribution** pie/donut chart

### Acceptance Criteria
- [ ] All active sources shown with stats
- [ ] Charts render with real data
- [ ] Source detail view works

---

## Phase 6.6: Knowledge Graph Visualization

**Goal:** Interactive force-directed graph of entities and relationships.

### Tasks

1. **Use react-force-graph-2d:**
   - Nodes = entities (colored by type: person, technology, project, topic)
   - Edges = co-occurrence relationships (weighted by strength)
   - Node size = number of connected memories

2. **Interactions:**
   - Click node → show related memories
   - Hover node → highlight connections
   - Search/filter nodes
   - Zoom and pan

3. **Graph controls:**
   - Filter by entity type
   - Minimum edge weight slider
   - Layout algorithm selection

4. **Data source:** `GET /api/v1/graph` endpoint (needs to be added to M3)

### Acceptance Criteria
- [ ] Graph renders with real entity data
- [ ] Interactive (click, hover, zoom, pan)
- [ ] Node filtering works
- [ ] Performance acceptable with 1000+ nodes

---

## Phase 6.7: Session Timeline

**Goal:** Chronological view of conversations across all tools.

### Tasks

1. **Timeline view:**
   - Vertical timeline with conversation cards
   - Grouped by date
   - Platform badge on each card
   - Session title + memory count + preview

2. **Filters:**
   - Platform filter
   - Date range
   - Search within timeline

3. **Click to expand** → show conversation memories

### Acceptance Criteria
- [ ] Timeline shows conversations chronologically
- [ ] Platform badges correct
- [ ] Can expand to see conversation details

---

## Phase 6.8: Analytics

**Goal:** Insights about your AI knowledge.

### Tasks

1. **Activity chart:** memories ingested per day/week/month (Recharts area chart)
2. **Top topics:** bar chart of most common topics over time
3. **Source distribution:** trends over time (stacked area)
4. **Most accessed memories:** frequently recalled knowledge
5. **Knowledge gaps:** topics with few memories or old data

### Acceptance Criteria
- [ ] All charts render with real data
- [ ] Date range selector works
- [ ] Responsive layout

---

## Phase 6.9: Settings

**Goal:** Configuration UI for Memgentic.

### Tasks

1. **General settings:**
   - Data directory path
   - Storage backend (local/qdrant)
   - Ollama URL

2. **Adapter status:**
   - List of all adapters with on/off toggle
   - Watch paths for each adapter
   - Last scan time + files processed

3. **Import/Export:**
   - File upload for bulk import
   - Export button (JSON, Markdown)
   - Import history

4. **Daemon status:**
   - Running/stopped indicator
   - Start/stop button
   - Recent processing log

### Acceptance Criteria
- [ ] Settings display current configuration
- [ ] Adapter status shows real data
- [ ] Import/export functions work

---

## Phase 6.10: Polish

**Goal:** Visual polish and responsive design.

### Tasks

1. **Responsive design:** test and fix on mobile, tablet, desktop
2. **Loading states:** skeleton screens for all data-loading pages
3. **Error states:** error boundaries with retry buttons
4. **Toast notifications:** for actions (remembered, archived, imported)
5. **Keyboard shortcuts:** `/` for search, `Esc` to close modals
6. **Performance:** lazy loading routes, image optimization

### Acceptance Criteria
- [ ] Works well on mobile
- [ ] All loading states show skeletons
- [ ] Error handling doesn't crash the app
- [ ] Toast notifications for actions
