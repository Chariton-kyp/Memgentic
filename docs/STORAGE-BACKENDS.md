# Storage Backends

Memgentic supports three vector storage backends. The backend is selected via
`MEMGENTIC_STORAGE_BACKEND` (env var) or `storage_backend` (settings/.env).

| Backend       | Value          | Default | Extra dep                  | Multi-process safe |
|---------------|----------------|---------|----------------------------|--------------------|
| Qdrant local  | `local`        | Yes     | (built-in)                 | No (file lock)     |
| Qdrant server | `qdrant`       | No      | Docker/Qdrant Cloud        | Yes                |
| sqlite-vec    | `sqlite_vec`   | No      | `memgentic[sqlite-vec]`    | Yes (WAL)          |

## When to pick which

### `local` (default — Qdrant file mode)
- Single process, zero config, easy getting-started.
- Good for: first-time users running just the CLI or the MCP server.
- Watch out: Qdrant's embedded file backend takes an exclusive lock. If you
  run the daemon and MCP server simultaneously you will hit
  "storage folder is already accessed by another instance".

### `qdrant` (Qdrant server)
- Run Qdrant as a separate process (e.g. via `docker compose up qdrant`).
- Good for: heavier usage, parallel daemon + API + MCP, or when you want
  Qdrant's advanced features (payload indexes on the server, HNSW tuning).
- Extra moving part: one more container / process to manage.

### `sqlite_vec` (opt-in)
- Co-locates vectors in the same SQLite file as the metadata/FTS5 store.
- Good for: personal use where you want daemon + MCP + API concurrently,
  without running a separate Qdrant server. SQLite WAL mode and
  `busy_timeout=5000` make multi-writer access safe.
- Scale envelope: tuned for 10k–100k vectors × 768 dims on commodity hardware.
- Works offline, ships only pre-built wheels (MIT/Apache-2.0 dual-licensed
  `sqlite-vec` 0.1.9), no extra binary.

## Enabling sqlite-vec

```bash
# 1. Install the optional extra
uv add 'memgentic[sqlite-vec]'
# or: pip install 'memgentic[sqlite-vec]'

# 2. Point Memgentic at it (env var, .env, or settings)
export MEMGENTIC_STORAGE_BACKEND=sqlite_vec

# 3. Run anything — the vec0 virtual table is created on first start.
memgentic doctor
memgentic remember "hello sqlite-vec"
memgentic search "hello"
```

The first-ever initialization pins the active embedding provider, model, and
dimension into a `vec_embedding_pin` row. Subsequent initializations verify
the pin; changing embedding models without running `memgentic re-embed`
raises `StorageError` instead of silently corrupting similarity scores.

## Trade-offs

| Concern                  | Qdrant local | Qdrant server | sqlite-vec |
|--------------------------|--------------|---------------|------------|
| Zero extra processes     | Yes          | No            | Yes        |
| Multi-process writers    | No           | Yes           | Yes        |
| Payload indexes enforced | No           | Yes           | Yes (SQL)  |
| HNSW tuning knobs        | No           | Yes           | No         |
| Good above ~1M vectors   | No           | Yes           | No         |

### Filter handling under sqlite-vec

sqlite-vec applies its KNN ``k`` cutoff at the index layer **before** SQLite
evaluates payload predicates on the JOINed row (platform, content_type,
user_id, min_confidence). Qdrant evaluates payload filters server-side as
part of the same request. To keep behaviour compatible, the sqlite-vec
backend over-fetches a 10× candidate pool when filters are present (capped
at 1000), then applies ``LIMIT`` on the filtered result. For very selective
filters over very large corpora you may still see fewer-than-expected
results — if you hit that, Qdrant server mode is the right choice.

## TODO

- `memgentic migrate-storage` command to copy memories + embeddings between
  backends (e.g. re-ingest from Qdrant local into sqlite-vec).
- Field-test sqlite-vec for a cycle, then flip the default `storage_backend`
  from `local` to `sqlite_vec` (tracked as a separate PR).
