# memgentic-native

**Native Rust acceleration for [Memgentic](https://pypi.org/project/memgentic/).** Optional — the core package runs on pure Python and auto-detects this extension at import time.

```bash
pip install memgentic-native
# or as an extra on the core:
pip install 'memgentic[native]'
```

## What it accelerates

| Module | Replaces Python | Typical speedup |
|---|---|---|
| **`textproc`** | credential scrubbing, noise detection, content classification | 5–15× |
| **`parsers`** | JSONL / Protocol Buffers / Markdown stream parsing | 3–8× |
| **`graph`** | knowledge-graph traversal via `petgraph` | 2–4× on large graphs |

All modules register under the `memgentic_native` PyO3 namespace. The core package imports them via `try / except ImportError` so every code path has a pure-Python fallback — `memgentic-native` is a performance add-on, never a hard requirement.

## Platform coverage

Pre-built wheels ship for:

- Linux x86_64, aarch64 (manylinux) — Python 3.12, 3.13
- macOS x86_64, aarch64 — Python 3.12, 3.13
- Windows x64 — Python 3.12, 3.13

Source distribution is published for other targets. Building from source needs a stable Rust toolchain and `maturin`.

## Versioning

Linked with `memgentic` + `memgentic-api`. All three ship on the same release cadence.

## License

Apache 2.0. See [LICENSE](https://github.com/Chariton-kyp/Memgentic/blob/main/LICENSE).
