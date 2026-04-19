# Storage Backends

Memgentic supports three vector storage backends. The backend is selected via
`MEMGENTIC_STORAGE_BACKEND` (env var) or `storage_backend` (settings/.env).

| Backend       | Value          | Default | Extra dep                  | Multi-process safe |
|---------------|----------------|---------|----------------------------|--------------------|
| sqlite-vec    | `sqlite_vec`   | **Yes** | (built-in since 0.6.0)     | Yes (WAL)          |
| Qdrant local  | `local`        | No      | (built-in)                 | No (file lock)     |
| Qdrant server | `qdrant`       | No      | Docker/Qdrant Cloud        | Yes                |

## When to pick which

### `sqlite_vec` (default)
- Co-locates vectors in the same SQLite file as the metadata/FTS5 store.
- Good for: all personal use — single process or daemon + MCP + API concurrently.
  SQLite WAL mode and `busy_timeout=5000` make multi-writer access safe.
- Scale envelope: tuned for 10k–100k vectors × 768 dims on commodity hardware.
- Works offline, ships pre-built wheels (MIT/Apache-2.0 dual-licensed), no extra binary.
- No extra dep required since 0.6.0 — `sqlite-vec` is a core dependency.

### `local` (Qdrant file mode — legacy)
- Single process, easy rollback if you have existing 0.4.x/0.5.0 Qdrant data.
- Watch out: takes an exclusive file lock. If you run the daemon and MCP server
  simultaneously you will hit "storage folder is already accessed by another instance".
- To opt in: `export MEMGENTIC_STORAGE_BACKEND=local`.

### `qdrant` (Qdrant server)
- Run Qdrant as a separate process (e.g. via `docker compose up qdrant`).
- Good for: heavier usage, parallel daemon + API + MCP, or when you want
  Qdrant's advanced features (payload indexes on the server, HNSW tuning).
- Extra moving part: one more container / process to manage.

## sqlite-vec is now the default

Since 0.6.0, `sqlite-vec>=0.1.9` is a **core dependency** — no extra install step
needed. A plain `pip install memgentic` gives you a fully working zero-config
vector store out of the box.

The `[sqlite-vec]` extra is kept as a no-op alias for back-compat:

```bash
# Both of these work identically now:
pip install memgentic
pip install 'memgentic[sqlite-vec]'
```

To confirm sqlite-vec is active:

```bash
memgentic doctor
memgentic remember "hello sqlite-vec"
memgentic search "hello"
```

## Migrating from 0.4.x / 0.5.0 Qdrant data

If you have existing memories in Qdrant local file mode, Memgentic will print a
warning on first start pointing at the migration command:

```bash
memgentic migrate-storage --from qdrant_local --to sqlite_vec
```

Do **not** auto-migrate — always review your data first. The command is safe to
re-run (idempotent).

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
  backends (e.g. re-ingest from Qdrant local into sqlite-vec). The migration
  detection warning already fires on first start to guide users there.
