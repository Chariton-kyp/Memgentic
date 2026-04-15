# M3: REST API

> FastAPI REST API for the dashboard, browser extension, and external integrations.

**Prerequisites:** M2 (Production Core)
**Estimated complexity:** Medium
**Exit criteria:** Full CRUD API working, OpenAPI spec auto-generated, tests passing, can be called from browser.

---

## Phase 3.1: API Package Setup

**Goal:** Create the memgentic-api UV workspace package with FastAPI boilerplate.

### Tasks

1. **Create `memgentic-api/` directory structure:**
   ```
   memgentic-api/
   ├── memgentic_api/
   │   ├── __init__.py
   │   ├── main.py          # FastAPI app + lifespan
   │   ├── deps.py           # Dependency injection (stores, embedder)
   │   ├── schemas.py        # API request/response Pydantic models
   │   └── routes/
   │       ├── __init__.py
   │       ├── memories.py
   │       ├── sources.py
   │       └── stats.py
   ├── tests/
   │   ├── __init__.py
   │   └── test_api.py
   └── pyproject.toml
   ```

2. **Create `memgentic-api/pyproject.toml`:**
   ```toml
   [project]
   name = "memgentic-api"
   version = "0.1.0"
   dependencies = [
       "memgentic",
       "fastapi>=0.130",
       "uvicorn[standard]>=0.34",
   ]

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"
   ```

3. **Add to workspace root `pyproject.toml`:**
   ```toml
   [tool.uv.workspace]
   members = ["memgentic", "memgentic-api"]
   ```

4. **Create `main.py` with lifespan:**
   - Initialize MetadataStore, VectorStore, Embedder, Pipeline on startup
   - Share via `app.state` or FastAPI dependency injection
   - CORS middleware allowing dashboard origin
   - Health check endpoint at `/api/v1/health`

5. **Create `deps.py`:**
   - Dependency functions for accessing stores from routes
   - `get_metadata_store()`, `get_vector_store()`, `get_embedder()`, `get_pipeline()`

6. **Add CLI command to start API:**
   - `memgentic api` — starts uvicorn with the FastAPI app
   - Add to `memgentic/memgentic/cli.py`

### Files to Create
- Full `memgentic-api/` directory structure
- Route files, schemas, deps, main

### Acceptance Criteria
- [ ] `uv sync` resolves with new package
- [ ] FastAPI app starts: `uv run uvicorn memgentic_api.main:app`
- [ ] Health check returns 200 at `/api/v1/health`
- [ ] OpenAPI docs at `/docs`

---

## Phase 3.2: Core Memory Endpoints

**Goal:** CRUD + search endpoints for memories.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/memories` | List memories (paginated, filtered) |
| GET | `/api/v1/memories/{id}` | Get single memory |
| POST | `/api/v1/memories` | Create a new memory |
| PATCH | `/api/v1/memories/{id}` | Update memory metadata |
| DELETE | `/api/v1/memories/{id}` | Delete (archive) a memory |
| POST | `/api/v1/memories/search` | Semantic search |
| POST | `/api/v1/memories/keyword-search` | Full-text keyword search |
| POST | `/api/v1/memories/recall` | MCP-style recall with source filtering |

### Request/Response Models (in `schemas.py`)

```python
class MemoryResponse(BaseModel):
    id: str
    content: str
    content_type: str
    platform: str
    topics: list[str]
    entities: list[str]
    confidence: float
    status: str
    created_at: datetime
    source: SourceResponse

class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]
    total: int
    page: int
    page_size: int

class SearchRequest(BaseModel):
    query: str
    sources: list[str] | None = None
    exclude_sources: list[str] | None = None
    content_types: list[str] | None = None
    limit: int = 10

class SearchResultResponse(BaseModel):
    memories: list[MemoryResponse]
    scores: list[float]
    query: str
    total: int

class CreateMemoryRequest(BaseModel):
    content: str
    content_type: str = "fact"
    topics: list[str] = []
    entities: list[str] = []
    source: str = "unknown"
```

### Acceptance Criteria
- [ ] All CRUD endpoints working
- [ ] Semantic search returns scored results
- [ ] Keyword search works
- [ ] Pagination works (page, page_size query params)
- [ ] Filtering by source, content_type, date range

---

## Phase 3.3: Source & Stats Endpoints

**Goal:** Analytics and source management endpoints.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/sources` | List all platforms with counts |
| GET | `/api/v1/sources/{platform}` | Detailed stats for one platform |
| GET | `/api/v1/stats` | Overall memory statistics |
| GET | `/api/v1/stats/timeline` | Memory count over time |
| GET | `/api/v1/stats/topics` | Top topics with counts |

### Acceptance Criteria
- [ ] Sources endpoint returns per-platform stats
- [ ] Stats endpoint returns total counts, vector info
- [ ] Timeline endpoint returns date-bucketed counts

---

## Phase 3.4: Import/Export Endpoints

**Goal:** Endpoints for bulk data operations.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/import/file` | Upload and import a conversation file |
| POST | `/api/v1/import/json` | Import memories from JSON array |
| GET | `/api/v1/export` | Export all memories as JSON |
| GET | `/api/v1/export/markdown` | Export as Markdown |

### Acceptance Criteria
- [ ] Can upload a JSONL file and have it processed
- [ ] Can export all memories as JSON
- [ ] Export respects source filters

---

## Phase 3.5: WebSocket Real-Time Updates

**Goal:** WebSocket endpoint for live dashboard updates.

### Tasks

1. **Create WebSocket endpoint at `/api/v1/ws`:**
   - Emit events when new memories are ingested
   - Emit events when daemon processes a file
   - Client can subscribe to specific event types

2. **Event format:**
   ```json
   {
     "type": "memory_created",
     "data": {"id": "...", "content_preview": "...", "platform": "claude_code"}
   }
   ```

### Acceptance Criteria
- [ ] WebSocket connects and receives events
- [ ] Events emitted on memory creation
- [ ] Clean disconnect handling

---

## Phase 3.6: API Tests

**Goal:** Comprehensive API test suite.

### Tasks

1. **Use FastAPI's `TestClient` for synchronous tests**
2. **Test all endpoints:**
   - CRUD operations
   - Search with various filters
   - Error cases (404, validation errors)
   - Pagination
3. **Integration test with real stores (SQLite in temp dir, Qdrant local)**

### Files to Create
- `memgentic-api/tests/test_memories.py`
- `memgentic-api/tests/test_sources.py`
- `memgentic-api/tests/test_import_export.py`
- `memgentic-api/tests/conftest.py`

### Acceptance Criteria
- [ ] All endpoints have tests
- [ ] Tests pass in CI
- [ ] Coverage >80% for API code

---

## Phase 3.7: Schema Migration Framework

**Goal:** Versioned SQL migrations for SQLite schema evolution.

### Tasks

1. **Create `memgentic/memgentic/storage/migrations.py`:**
   - Version table: `CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)`
   - Numbered migration scripts as Python functions
   - `migrate()` function that applies pending migrations in order
   - Called automatically on `MetadataStore.initialize()`

2. **Initial migration (v1):** current schema (the CREATE_TABLE_SQL already in metadata.py)

3. **Pattern for future migrations:**
   ```python
   MIGRATIONS = {
       1: "-- initial schema (already applied via CREATE IF NOT EXISTS)",
       2: "ALTER TABLE memories ADD COLUMN sync_version INTEGER DEFAULT 0;",
       3: "ALTER TABLE memories ADD COLUMN importance_score REAL DEFAULT 1.0;",
   }
   ```

### Acceptance Criteria
- [ ] Schema version tracked in database
- [ ] Migrations run automatically on startup
- [ ] Future schema changes are easy to add

---

## Phase 3.8: Backup/Restore & Data Export

**Goal:** CLI commands for data safety and GDPR compliance.

### Tasks

1. **`memgentic backup [--output PATH]`:**
   - Copies SQLite database to backup location
   - Exports Qdrant vectors as JSON
   - Creates a single `.mneme-backup.tar.gz` archive

2. **`memgentic restore <backup-file>`:**
   - Validates backup integrity
   - Restores SQLite + Qdrant data

3. **`memgentic export --gdpr`:**
   - Exports ALL user data as JSON (memories, metadata, settings)
   - Includes provenance information
   - GDPR Article 20 compliant (data portability)

4. **`memgentic re-embed [--model MODEL]`:**
   - Re-generates embeddings for all memories with a new model
   - Progress bar for large collections
   - Atomic: only updates Qdrant after all embeddings generated

### Acceptance Criteria
- [ ] Backup creates a restorable archive
- [ ] Restore works from backup
- [ ] GDPR export includes all personal data
- [ ] Re-embed works with different models

---

## Phase 3.9: Rate Limiting

**Goal:** Protect API from abuse.

### Tasks

1. **Add `slowapi` or custom middleware:**
   - Per-IP: 60 requests/minute for unauthenticated
   - Per-user: 300 requests/minute for authenticated (Pro+)
   - Per-user: 1000 requests/minute for Enterprise

2. **Rate limit headers:** `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

3. **429 Too Many Requests response** with retry-after header

### Acceptance Criteria
- [ ] Rate limiting active on all endpoints
- [ ] Correct headers returned
- [ ] Different limits per auth tier

---

## Phase 3.10: Makefile & Docker Updates

**Goal:** Update development commands for the API.

### Tasks

1. **Add to Makefile:**
   ```makefile
   api:  ## Start REST API locally
   	uv run uvicorn memgentic_api.main:app --reload --port 8100

   api-prod:  ## Start REST API (production)
   	uv run uvicorn memgentic_api.main:app --host 0.0.0.0 --port 8100
   ```

2. **Update docker-compose.yml:**
   - Add `memgentic-api` service on port 8100
   - Or combine MCP + API in same service with different entry points

3. **Update CI to test API package too**

### Acceptance Criteria
- [ ] `make api` starts the API server
- [ ] Docker Compose includes API service
- [ ] CI tests both core and API
