# Memgentic Technical Implementation Plan v2

**Status:** Planning
**Date:** 2026-04-10
**Revision:** v2 — Universal skills + dual-mode storage

---

## Architecture Decision: SQLite vs PostgreSQL

### The Answer: Both (Dual-Mode)

| Mode | When | Stack | Users |
|------|------|-------|-------|
| **Local** (default) | Single user, zero-config | SQLite + Qdrant (file-based) | Solo devs, Phase A/B |
| **Cloud/Team** | Multi-user, shared data | PostgreSQL + pgvector | Teams, Phase C |

**Why not just PostgreSQL?**
- Memgentic's #1 promise is **local-first, zero-config**. Requiring a PostgreSQL server to get started kills the "install and forget" experience.
- SQLite + Qdrant (file-based) works with zero external services.
- For single-user, SQLite is faster than PostgreSQL (no network overhead, no connection pooling).

**Why not just SQLite?**
- SQLite can't handle concurrent multi-user writes (WAL helps but doesn't scale).
- No built-in vector search (we use separate Qdrant).
- PostgreSQL + pgvector = ONE database for metadata + vectors + FTS. Simpler team deployment.
- PostgreSQL has proper authentication, row-level security, connection pooling.

**Implementation approach:**
- Phase A/B: SQLite + Qdrant (current, unchanged)
- Phase C: Add PostgreSQL + pgvector as alternative storage backend
- Storage layer already has `MetadataStore` and `VectorStore` — add PostgreSQL implementations
- Config: `MEMGENTIC_STORAGE_BACKEND=local|qdrant|postgresql`
- Cloud deployment uses PostgreSQL by default

### What Changes in the Config

```python
class StorageBackend(StrEnum):
    LOCAL = "local"           # SQLite + Qdrant file-based (zero-config)
    QDRANT = "qdrant"         # SQLite + Qdrant server
    POSTGRESQL = "postgresql" # PostgreSQL + pgvector (Phase C)
```

```python
# New settings (Phase C only)
postgresql_url: str = Field(
    default="",
    description="PostgreSQL connection URL (only for postgresql backend)",
)
```

---

## Universal Skills Architecture

### Design Principle

Memgentic is not just a store for "Memgentic skills." It's a **universal skill manager** — a central hub where you create, import, organize, and distribute ANY skills to ALL your AI coding tools. One place to manage skills that work across 26+ platforms via the Agent Skills open standard.

### The Three Roles

```
1. STORE — Skills live in Memgentic's database
   Create in dashboard, import from ClawHub/GitHub, auto-extract from memories

2. DISTRIBUTE — Daemon writes skills to each tool's native discovery path
   ~/.claude/skills/ → Claude Code
   ~/.codex/skills/  → Codex
   .cursor/rules/    → Cursor
   (any tool that supports the Agent Skills standard)

3. SERVE — MCP server provides dynamic skill access
   memgentic_skills() → list available skills
   memgentic_skill(name) → return skill content
   (for tools that prefer API over filesystem)
```

### Skill Storage (Phase B)

The schema follows the Agent Skills open standard + Multica's multi-file pattern:

```sql
-- Skills — universal, standards-compliant
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,                    -- kebab-case, matches directory name
    description TEXT NOT NULL DEFAULT '',  -- 1-1024 chars per standard
    content TEXT NOT NULL DEFAULT '',      -- SKILL.md body (< 5000 tokens recommended)
    
    -- Metadata
    source TEXT NOT NULL DEFAULT 'manual', -- manual, imported, auto_extracted, cloned
    source_url TEXT,                       -- GitHub URL, ClawHub URL, etc.
    version TEXT NOT NULL DEFAULT '1.0.0',
    license TEXT,
    tags TEXT NOT NULL DEFAULT '[]',       -- JSON array
    
    -- Compatibility (from Agent Skills standard)
    compatibility TEXT NOT NULL DEFAULT '{}', -- JSON: environment requirements
    allowed_tools TEXT,                       -- space-delimited tool names
    
    -- Auto-extraction metadata
    source_memory_ids TEXT NOT NULL DEFAULT '[]', -- JSON array of memory IDs
    auto_extracted INTEGER NOT NULL DEFAULT 0,
    extraction_confidence REAL NOT NULL DEFAULT 0,
    
    -- Distribution config
    distribute_to TEXT NOT NULL DEFAULT '["claude","codex","cursor"]', -- JSON array
    auto_distribute INTEGER NOT NULL DEFAULT 1, -- daemon auto-writes to tool paths
    
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    
    UNIQUE(user_id, name)
);

-- Skill files — supporting files (scripts/, references/, assets/)
CREATE TABLE IF NOT EXISTS skill_files (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    path TEXT NOT NULL,           -- e.g. "scripts/deploy.sh", "references/api.md"
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(skill_id, path)
);
CREATE INDEX IF NOT EXISTS idx_skill_files_skill ON skill_files(skill_id);

-- Skill distribution log — tracks where skills have been written
CREATE TABLE IF NOT EXISTS skill_distributions (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    tool TEXT NOT NULL,           -- "claude", "codex", "cursor", "copilot"
    target_path TEXT NOT NULL,    -- actual filesystem path written to
    distributed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', -- active, removed, error
    UNIQUE(skill_id, tool)
);
```

### Skill Distribution Engine (New Daemon Capability)

```python
# memgentic/memgentic/skills/distributor.py

TOOL_SKILL_PATHS = {
    # Tool → (base_path, skill_subdir_pattern)
    "claude": {
        "global": Path.home() / ".claude" / "skills",
        "project": ".claude/skills",  # relative to project root
    },
    "codex": {
        "global": Path.home() / ".codex" / "skills",
        "project": ".agents/skills",
    },
    "cursor": {
        "project": ".cursor/rules",   # Cursor uses rules, not skills dir
    },
    "copilot": {
        "project": ".github",         # copilot-instructions.md (appended)
    },
    "opencode": {
        "global": Path.home() / ".config" / "opencode" / "skills",
    },
}

class SkillDistributor:
    """Writes skills from database to each tool's native discovery path."""
    
    async def distribute_skill(self, skill: Skill, tools: list[str]):
        """Write a skill to the specified tools' native paths."""
        for tool in tools:
            paths = TOOL_SKILL_PATHS.get(tool, {})
            target = paths.get("global")  # Default to global scope
            if not target:
                continue
            
            skill_dir = target / skill.name
            skill_dir.mkdir(parents=True, exist_ok=True)
            
            # Write SKILL.md (Agent Skills standard format)
            skill_md = self._render_skill_md(skill)
            (skill_dir / "SKILL.md").write_text(skill_md)
            
            # Write supporting files
            for f in skill.files:
                file_path = skill_dir / f.path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(f.content)
            
            # Log distribution
            await self._log_distribution(skill.id, tool, str(skill_dir))
    
    def _render_skill_md(self, skill: Skill) -> str:
        """Render SKILL.md in Agent Skills standard format."""
        frontmatter = f"""---
name: {skill.name}
description: {skill.description}
"""
        if skill.license:
            frontmatter += f"license: {skill.license}\n"
        if skill.allowed_tools:
            frontmatter += f"allowed-tools: {skill.allowed_tools}\n"
        frontmatter += "---\n\n"
        
        return frontmatter + skill.content
    
    async def remove_skill(self, skill: Skill, tools: list[str]):
        """Remove a skill from tools' native paths."""
        for tool in tools:
            paths = TOOL_SKILL_PATHS.get(tool, {})
            target = paths.get("global")
            if target:
                skill_dir = target / skill.name
                if skill_dir.exists():
                    shutil.rmtree(skill_dir)
    
    async def sync_all(self, skills: list[Skill]):
        """Full sync — ensure all skills are distributed to their target tools."""
        for skill in skills:
            tools = json.loads(skill.distribute_to)
            await self.distribute_skill(skill, tools)
```

### Skill Import Sources

Skills can come from:

| Source | How | Standard |
|--------|-----|----------|
| **Dashboard UI** | Create/edit in web editor | Any |
| **CLI** | `memgentic skill create --name X` | Any |
| **GitHub** | Import from any repo with SKILL.md | Agent Skills |
| **Auto-extraction** | LLM synthesizes from memories | Internal |
| **File system** | Import from local `.claude/skills/` | Agent Skills |
| **MCP** | `memgentic_remember` with skill flag | Internal |

### API Endpoints for Skills

```
CRUD:
  GET    /api/v1/skills                        → list all skills
  POST   /api/v1/skills                        → create skill
  GET    /api/v1/skills/{id}                   → get skill with files
  PUT    /api/v1/skills/{id}                   → update skill
  DELETE /api/v1/skills/{id}                   → delete + remove from tool paths

Files:
  POST   /api/v1/skills/{id}/files             → add file to skill
  PUT    /api/v1/skills/{id}/files/{fid}       → update file
  DELETE /api/v1/skills/{id}/files/{fid}       → delete file

Import:
  POST   /api/v1/skills/import                 → import from GitHub URL
  POST   /api/v1/skills/import-local           → import from local path
  POST   /api/v1/skills/extract                → auto-extract from memories

Distribution:
  POST   /api/v1/skills/{id}/distribute        → manual distribute to tools
  DELETE /api/v1/skills/{id}/distribute/{tool}  → remove from specific tool
  GET    /api/v1/skills/{id}/distributions     → list where skill is installed
```

### MCP Tools for Skills

```python
# memgentic_skills — list available skills with descriptions
# Response: skill names + descriptions (metadata only, < 100 tokens each)
# Usage: AI tool calls this to discover what skills exist

# memgentic_skill — get full skill content by name
# Response: complete SKILL.md content + file list
# Usage: AI tool loads a specific skill when needed

# memgentic_skill_create — create a new skill from conversation context
# Usage: "Remember this deployment process as a skill"
```

---

## Phase 1: Enhanced Dashboard + Manual Upload + Collections (4-6 weeks)

### Database Migration 5

```sql
-- Collections
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6B7280',
    icon TEXT NOT NULL DEFAULT 'folder',
    position REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Collection membership
CREATE TABLE IF NOT EXISTS collection_memories (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    position REAL NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, memory_id)
);

-- Uploads tracking
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    memory_id TEXT REFERENCES memories(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    upload_source TEXT NOT NULL DEFAULT 'manual',
    original_url TEXT,
    status TEXT NOT NULL DEFAULT 'processing',
    error_message TEXT,
    created_at TEXT NOT NULL
);

-- Pin support
ALTER TABLE memories ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN pinned_at TEXT;
```

### API Endpoints (Phase 1)

```
Collections:
  GET/POST      /api/v1/collections
  PATCH/DELETE  /api/v1/collections/{id}
  GET/POST      /api/v1/collections/{id}/memories
  DELETE        /api/v1/collections/{id}/memories/{mid}

Pin:
  POST/DELETE   /api/v1/memories/{id}/pin
  GET           /api/v1/memories/pinned

Upload:
  POST  /api/v1/upload/text
  POST  /api/v1/upload/file     (multipart)
  POST  /api/v1/upload/url
  GET   /api/v1/uploads

Topics:
  GET   /api/v1/topics          (autocomplete)

Batch:
  POST  /api/v1/memories/batch-update
  POST  /api/v1/memories/batch-delete
```

### New Models
- `Collection`, `Upload`, `UploadStatus`
- Add `MANUAL_UPLOAD`, `URL_IMPORT` to `CaptureMethod`
- Add `MANUAL` to `Platform`
- Add `is_pinned`, `pinned_at` to `Memory`

### New Files
- `memgentic/processing/file_ingest.py` — PDF/text/URL content extraction
- `memgentic-api/routes/collections.py` — collection CRUD
- `memgentic-api/routes/uploads.py` — upload endpoints

---

## Phase 2: Universal Skills + Real-time (4-6 weeks)

### Database Migration 6
(Skills schema from above — `skills`, `skill_files`, `skill_distributions`)

### New Files
- `memgentic/skills/distributor.py` — write skills to tool-native paths
- `memgentic/skills/importer.py` — import from GitHub/local paths
- `memgentic/processing/skill_extractor.py` — LLM auto-extraction
- `memgentic-api/routes/skills.py` — skill CRUD + import + distribution
- `memgentic-api/routes/ingestion.py` — ingestion job tracking

### MCP Tools
- `memgentic_skills` — list available skills
- `memgentic_skill` — get skill content by name
- `memgentic_pin` — pin/unpin memories

### Daemon Enhancement
- Skill distribution loop: watches for skill changes, syncs to tool paths
- Activity event broadcasting for real-time dashboard

---

## Phase 3: Workspaces + PostgreSQL (6-8 weeks)

### Database Migration 7
- Users, auth tokens, workspaces, workspace members
- Add `workspace_id` to memories, collections, skills, uploads
- PostgreSQL-specific: pgvector extension for vectors

### New StorageBackend
- `POSTGRESQL` — PostgreSQL + pgvector (one database for everything)
- New `PostgresMetadataStore` and `PostgresVectorStore` implementations
- Connection pooling via asyncpg

### Auth + Workspaces
- JWT + magic links (opt-in)
- `X-Workspace-ID` header scoping
- Role-based access

---

## Key Design Decisions

1. **Dual-mode storage** — SQLite+Qdrant for local, PostgreSQL+pgvector for cloud/team
2. **Universal skills** — store any skill, distribute to any tool via open standard
3. **Agent Skills standard** — SKILL.md with YAML frontmatter, 26+ tool compatibility
4. **Three injection layers** — filesystem (static), MCP (dynamic), hooks (automatic)
5. **Skills are not Memgentic-specific** — import from GitHub, export as standard files
6. **Daemon does distribution** — watches skill DB, writes to native tool paths
7. **Auth is opt-in** — local mode unchanged
8. **Core independence** — models in core, routes in API, distribution in daemon
