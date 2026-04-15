# M2: Production Core

> Make the core engine production-quality with proper async, error handling, performance, and CI/CD.

**Prerequisites:** M1 (Bootstrap & Verify)
**Estimated complexity:** Medium
**Exit criteria:** AsyncQdrantClient working, all errors handled gracefully, test coverage >80%, CI pipeline green.

---

## Phase 2.1: Async Qdrant Client

**Goal:** Switch from synchronous to async Qdrant client for non-blocking operations.

### Tasks

1. **Update `memgentic/memgentic/storage/vectors.py`:**
   - Replace `QdrantClient` with `AsyncQdrantClient` from `qdrant_client`
   - Update all methods to use `await` on Qdrant operations
   - `AsyncQdrantClient` uses `path=` for local and `url=` for remote, same as sync

2. **Key changes:**
   ```python
   from qdrant_client import AsyncQdrantClient, models

   class VectorStore:
       async def initialize(self):
           if local:
               self._client = AsyncQdrantClient(path=str(path))
           else:
               self._client = AsyncQdrantClient(url=..., api_key=...)

           # All operations now truly async
           collections = await self._client.get_collections()
           await self._client.create_collection(...)
           await self._client.upsert(...)
           results = await self._client.query_points(...)
   ```

3. **Update all callers** — should be transparent since methods were already `async`

### Files to Modify
- `memgentic/memgentic/storage/vectors.py` — async client

### Acceptance Criteria
- [ ] All vector operations use AsyncQdrantClient
- [ ] Existing tests still pass
- [ ] No blocking calls in async context

---

## Phase 2.2: Error Handling & Resilience

**Goal:** Graceful degradation, proper error types, structured logging.

### Tasks

1. **Create `memgentic/memgentic/exceptions.py`:**
   ```python
   class MemgenticError(Exception): ...
   class EmbeddingError(MemgenticError): ...
   class StorageError(MemgenticError): ...
   class AdapterError(MemgenticError): ...
   class PipelineError(MemgenticError): ...
   ```

2. **Add retry logic to embedder:**
   - Retry on connection errors (Ollama might be starting up)
   - 3 retries with exponential backoff (1s, 2s, 4s)
   - Use `tenacity` library or manual retry loop
   - Raise `EmbeddingError` on final failure

3. **Add error handling to pipeline:**
   - Catch embedding failures — log and skip, don't crash the whole import
   - Catch storage failures — retry once, then log and continue
   - Return partial results with error count

4. **Add error handling to MCP tools:**
   - Return user-friendly error messages, not stack traces
   - Log full error for debugging

5. **Add error handling to daemon:**
   - File watcher errors — log and continue watching
   - Processing errors — log and skip file, retry on next modification

6. **Improve structured logging throughout:**
   - Add timing information to key operations
   - Log batch sizes, success/failure counts
   - Use `structlog.contextvars` for request-scoped context

### Files to Create
- `memgentic/memgentic/exceptions.py`

### Files to Modify
- `memgentic/memgentic/processing/embedder.py` — retry logic
- `memgentic/memgentic/processing/pipeline.py` — error handling
- `memgentic/memgentic/mcp/server.py` — user-friendly errors
- `memgentic/memgentic/daemon/watcher.py` — resilient watching

### Acceptance Criteria
- [ ] Custom exception hierarchy exists
- [ ] Embedder retries on transient failures
- [ ] Pipeline doesn't crash on individual file errors
- [ ] MCP tools return friendly error messages
- [ ] Structured logs include timing and counts

---

## Phase 2.3: Performance Optimization

**Goal:** Faster imports, better resource usage.

### Tasks

1. **Concurrent embedding generation:**
   - Use `asyncio.Semaphore` to limit concurrent Ollama calls (e.g., 4)
   - Process batch embeddings with `asyncio.gather`
   - This is safe since each embedding is independent

2. **HTTP connection reuse:**
   - Create a shared `httpx.AsyncClient` with connection pooling
   - Pass it through the pipeline instead of creating per-call
   - Set appropriate timeouts and limits

3. **Fix duplicate file_hash computation:**
   - In `pipeline.py`, `_compute_file_hash()` is called at line 74 (dedup check) and line 121 (mark processed)
   - Cache the first computation and reuse

4. **Batch SQLite operations:**
   - Wrap full file processing in a single transaction
   - Reduce commit frequency (commit per file, not per memory)

5. **Add progress reporting for large imports:**
   - Emit progress logs every N files
   - In CLI, show Rich progress bar during import

### Files to Modify
- `memgentic/memgentic/processing/embedder.py` — concurrent + connection pooling
- `memgentic/memgentic/processing/pipeline.py` — cache hash, batch commits
- `memgentic/memgentic/cli.py` — progress bars

### Acceptance Criteria
- [ ] Embedding batch uses concurrency (measurably faster)
- [ ] httpx client reused across calls
- [ ] file_hash computed once per file
- [ ] Import shows progress for large batches

---

## Phase 2.4: Session Config Scoping

**Goal:** Fix the global session config issue for multi-client support.

### Tasks

1. **Problem:** `_session_config` is a module-level global in `server.py`. If the MCP server runs with `streamable_http` transport, multiple clients share session config.

2. **Solution:** Use FastMCP's context system or request-scoped storage:
   - Store session config per-connection using MCP session ID
   - Use a dict keyed by session/connection ID
   - Clean up on session close

3. **Implementation:**
   ```python
   _session_configs: dict[str, SessionConfig] = {}

   def _get_session_id(ctx: Context) -> str:
       # Extract session ID from MCP context
       return ctx.request_context.session.session_id or "default"

   @mcp.tool(name="mneme_configure_session", ...)
   async def mneme_configure_session(params, ctx):
       session_id = _get_session_id(ctx)
       _session_configs[session_id] = SessionConfig(...)
   ```

### Files to Modify
- `memgentic/memgentic/mcp/server.py` — session-scoped config

### Acceptance Criteria
- [ ] Session config is per-connection, not global
- [ ] Multiple clients can have different filters
- [ ] Default (stdio, single client) still works

---

## Phase 2.5: Comprehensive Test Suite

**Goal:** Unit + integration tests for all modules, >80% coverage.

### Tasks

1. **Add tests for `storage/metadata.py`:**
   - Test CRUD operations
   - Test FTS5 search
   - Test source stats
   - Test deduplication tracking
   - Test filter building

2. **Add tests for `storage/vectors.py`:**
   - Test initialization (local mode)
   - Test upsert + search
   - Test filter building (source, content type, confidence)
   - Test collection creation

3. **Add tests for `processing/embedder.py`:**
   - Mock Ollama responses
   - Test dimension truncation
   - Test error handling / retries

4. **Add tests for `processing/pipeline.py`:**
   - Test full ingestion flow (with mocked stores)
   - Test deduplication
   - Test single memory ingestion

5. **Add tests for `mcp/server.py`:**
   - Test each MCP tool function
   - Mock the storage/embedder dependencies

6. **Add tests for `daemon/watcher.py`:**
   - Test file event handling
   - Test debouncing
   - Test scan_existing

7. **Add tests for `cli.py`:**
   - Test Click commands with CliRunner
   - Test output formatting

### Files to Create
- `memgentic/tests/test_metadata_store.py`
- `memgentic/tests/test_vector_store.py`
- `memgentic/tests/test_embedder.py`
- `memgentic/tests/test_pipeline.py`
- `memgentic/tests/test_mcp_server.py`
- `memgentic/tests/test_daemon.py`
- `memgentic/tests/test_cli.py`
- `memgentic/tests/conftest.py` — shared fixtures

### Acceptance Criteria
- [ ] Tests exist for every module
- [ ] Coverage >80%
- [ ] All tests pass
- [ ] Tests run in <30 seconds (mocked external deps)

---

## Phase 2.6: CI/CD Pipeline

**Goal:** Automated testing and linting on every push/PR.

### Tasks

1. **Create `.github/workflows/ci.yml`:**
   ```yaml
   name: CI
   on: [push, pull_request]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v4
         - run: uv sync --dev
         - run: uv run pytest memgentic/tests/ -v --cov=memgentic
     lint:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v4
         - run: uv sync --dev
         - run: uv run ruff check memgentic/
         - run: uv run ruff format --check memgentic/
   ```

2. **Add pre-commit hook (optional):**
   - Ruff check + format on staged files

### Files to Create
- `.github/workflows/ci.yml`

### Acceptance Criteria
- [ ] CI runs on push and PR
- [ ] Tests and lint both pass in CI
- [ ] Badge can be added to README
