# Rust Integration Research for Memgentic

**Date:** 2026-04-10
**Status:** Research / Proposal

---

## Executive Summary

After a deep analysis of the entire Memgentic codebase — core library (2,700+ lines of processing code), 9 adapters, ingestion pipeline, storage layer, knowledge graph, MCP server, REST API, and dashboard — this document identifies **where Rust can deliver real, measurable improvements** and where it would be wasted effort.

**The verdict:** Rust is not needed everywhere, but it can transform 3-4 specific bottlenecks into high-performance native modules. The recommended approach is **PyO3-based Python extensions** — write performance-critical code in Rust, expose it as a normal Python package. Zero disruption to the existing architecture.

---

## Table of Contents

1. [Bottleneck Analysis](#1-bottleneck-analysis)
2. [Where Rust Helps (High Impact)](#2-where-rust-helps-high-impact)
3. [Where Rust Does NOT Help](#3-where-rust-does-not-help)
4. [Recommended Architecture](#4-recommended-architecture)
5. [Implementation Roadmap](#5-implementation-roadmap)
6. [Effort vs. Impact Matrix](#6-effort-vs-impact-matrix)
7. [Rust Learning Path](#7-rust-learning-path)

---

## 1. Bottleneck Analysis

### Current Performance Profile

| Component | Bound By | Current Tech | Hot Path? |
|-----------|----------|-------------|-----------|
| File parsing (adapters) | CPU + Memory | Python JSON/regex | Yes — every ingestion |
| Credential scrubbing | CPU | 14 compiled regex patterns | Yes — every memory |
| Noise detection | CPU | Regex + heuristics | Yes — every memory |
| Embedding generation | Network I/O | HTTP to Ollama/OpenAI | Yes, but I/O-bound |
| Vector search (Qdrant) | Network I/O | Async HTTP client | Yes, but I/O-bound |
| SQLite operations | Disk I/O | aiosqlite (C-backed) | Moderate |
| Knowledge graph | CPU + Memory | NetworkX (pure Python) | Yes — grows with data |
| Text overlap (Jaccard) | CPU | Python set operations | Yes — dedup + contradiction |
| RRF ranking + decay | CPU | Python math | Moderate |
| MCP server | Network I/O | FastMCP | Low |
| REST API | Network I/O | FastAPI | Low |

### Key Insight

Memgentic's hottest paths are the **ingestion pipeline** (parsing → scrubbing → noise filter → classify → embed → dedup → store) and **search** (embed query → vector search → keyword search → RRF merge). Within these:

- **Network I/O** (embedding calls, Qdrant queries) dominates wall-clock time — Rust cannot help here.
- **CPU-bound text processing** (parsing, regex, similarity) is where Python is genuinely slow — Rust excels here.
- **Memory pressure** from loading entire conversation files into Python objects — Rust's zero-cost abstractions and streaming parsers eliminate this.

---

## 2. Where Rust Helps (High Impact)

### 2.1 Conversation File Parsing (Adapters)

**Problem:** All JSON/Markdown adapters load the entire file into memory before parsing. A 50MB ChatGPT export creates ~200MB of Python objects (dicts, lists, strings). The Claude Code adapter runs 7 compiled regex patterns on every turn's content.

**Rust solution:** A streaming parser library exposed via PyO3.

```
Current (Python):
  1. Read entire file → Python string (50MB)
  2. json.loads() → Python dicts (150MB+)
  3. Walk tree, extract text → more allocations
  4. Run 7 regex patterns per turn

With Rust (PyO3):
  1. Memory-mapped file read (zero-copy)
  2. Streaming JSON parse (serde_json::StreamDeserializer)
  3. Extract text + clean XML in single pass
  4. Return only ConversationChunk data to Python
  Peak memory: ~2x the useful text, not 4x the file size
```

**Estimated improvement:**
- 5-10x faster parsing for large files
- 3-5x less memory usage
- Claude Code adapter XML cleaning: 10-20x faster (Rust regex crate vs Python re)

**Affected adapters:**
- Claude Code (JSONL + XML regex) — highest impact
- ChatGPT Import (JSON tree flattening + sorting) — high impact
- Antigravity (Protobuf wire-format parsing) — high impact, Rust is ideal for binary formats
- All others benefit from faster JSON/text handling

### 2.2 Text Processing Pipeline

**Problem:** Every memory passes through credential scrubbing (14 regex patterns), noise detection (multiple regex + heuristics), content classification (keyword matching), and text overlap computation (Jaccard similarity). For bulk imports of thousands of memories, this is CPU-bound.

**Rust solution:** A single `memgentic-textproc` native module.

```rust
// Exposed to Python via PyO3
#[pyfunction]
fn process_text(text: &str) -> TextResult {
    // All in one pass through the text:
    // 1. Credential scrubbing (aho-corasick for fixed patterns + regex for dynamic)
    // 2. Noise detection (character counting, pattern matching)
    // 3. Basic content classification (keyword presence)
    // 4. Entity extraction (URLs, file paths, identifiers)
    TextResult { cleaned, is_noise, content_type, entities, redaction_count }
}

#[pyfunction]
fn text_overlap(a: &str, b: &str) -> f64 {
    // Word-level Jaccard with HashSet<&str> (zero-copy slices)
}

#[pyfunction]
fn batch_process(texts: Vec<&str>) -> Vec<TextResult> {
    // Rayon parallel processing across all texts
    texts.par_iter().map(|t| process_text(t)).collect()
}
```

**Estimated improvement:**
- Credential scrubbing: 20-50x faster (Aho-Corasick multi-pattern matching vs 14 sequential regex)
- Noise detection: 5-10x faster
- Text overlap: 10-20x faster (Rust HashSet vs Python set)
- Batch processing with Rayon parallelism: linear scaling across CPU cores

### 2.3 Knowledge Graph Engine

**Problem:** NetworkX is pure Python. As the memory count grows (10K+ memories, each with 5-10 entities/topics), the graph becomes a bottleneck:
- `add_memory()` creates O(N²) edges for N entities (complete subgraph per memory)
- BFS queries traverse pure-Python dicts
- JSON serialization/deserialization of the full graph on every save/load
- No concurrent access (Python GIL)

**Rust solution:** Replace NetworkX with a Rust graph engine.

```rust
// petgraph or custom adjacency list
struct KnowledgeGraph {
    graph: UnGraph<NodeData, EdgeData>,
    name_index: HashMap<String, NodeIndex>,  // O(1) lookup by name
}

// Exposed via PyO3
#[pymethods]
impl KnowledgeGraph {
    fn add_memory(&mut self, topics: Vec<String>, entities: Vec<String>, memory_id: String);
    fn query_neighbors(&self, entity: &str, depth: usize, limit: usize) -> Vec<NodeInfo>;
    fn get_graph_data(&self, min_weight: usize) -> GraphExport;
    fn save(&self, path: &str);  // MessagePack or bincode, not JSON
    fn load(path: &str) -> Self;
}
```

**Estimated improvement:**
- Graph operations: 10-50x faster
- Serialization: 5-10x faster (binary format vs JSON)
- Memory usage: 3-5x less (no Python object overhead per node/edge)
- Concurrent reads: possible with Rust (no GIL)

### 2.4 Protobuf Parsing (Antigravity Adapter)

**Problem:** The current Antigravity adapter manually walks Protocol Buffer wire format in Python — reading varints, handling wire types, recursive descent into nested messages. This is exactly what Rust excels at: binary format parsing with zero-copy slices.

**Rust solution:** Use the `prost` or `bytes` crate for wire-format walking, or even better, if the protobuf schema becomes available, full typed deserialization.

**Estimated improvement:** 10-50x faster, especially for large `.pb` files with deep nesting.

---

## 3. Where Rust Does NOT Help

### 3.1 Embedding Generation (Network I/O)
The embedder spends 95%+ of time waiting for HTTP responses from Ollama or OpenAI. Python's async HTTP (httpx) is already optimal. Rust would save microseconds on request construction — irrelevant compared to milliseconds of network latency.

### 3.2 Vector Search (Qdrant Client)
Same reasoning — network I/O dominates. The Qdrant Python client is a thin async HTTP wrapper. No CPU work to optimize.

### 3.3 SQLite Storage
SQLite is already written in C. Python's `aiosqlite` is a thin async wrapper around the C library. The bottleneck is disk I/O and query planning, not the Python layer.

### 3.4 LLM Intelligence Pipeline
LangChain/LangGraph orchestration is network-bound (LLM API calls). The Python orchestration overhead is negligible compared to LLM inference time.

### 3.5 MCP Server & REST API
Both are I/O-bound network services. FastAPI and FastMCP are already high-performance for this workload. Rewriting in Rust (e.g., Axum) would add complexity without meaningful throughput gains for a local-first tool.

### 3.6 Dashboard
JavaScript/React — not relevant to Rust.

### 3.7 File Watching Daemon
The watchdog library uses OS-native file system events (inotify on Linux, FSEvents on macOS). The Python overhead is negligible — the daemon mostly sleeps waiting for events.

---

## 4. Recommended Architecture

### Approach: PyO3 Native Extensions

Keep the entire Python codebase. Add Rust as **native extensions** that drop into the existing architecture:

```
memgentic/                    ← Existing Python package (unchanged)
├── memgentic/
│   ├── ...                   ← All existing code stays
│   └── _native/              ← Rust-backed modules (auto-imported)
│       ├── __init__.py       ← "from memgentic._native import ..."
│       └── (compiled .so)    ← Built by maturin

memgentic-native/             ← New Rust crate (PyO3 + maturin)
├── Cargo.toml
├── pyproject.toml            ← maturin build backend
└── src/
    ├── lib.rs                ← PyO3 module registration
    ├── parsers/
    │   ├── mod.rs
    │   ├── jsonl.rs          ← Claude Code JSONL streaming parser
    │   ├── chatgpt.rs        ← ChatGPT JSON tree flattener
    │   ├── protobuf.rs       ← Antigravity wire-format parser
    │   └── markdown.rs       ← Aider/Codex markdown splitter
    ├── textproc/
    │   ├── mod.rs
    │   ├── scrubber.rs       ← Credential scrubbing (Aho-Corasick)
    │   ├── noise.rs          ← Noise detection
    │   ├── classify.rs       ← Content type classification
    │   ├── overlap.rs        ← Text overlap (Jaccard)
    │   └── entities.rs       ← Entity extraction (URLs, paths, etc.)
    └── graph/
        ├── mod.rs
        └── knowledge.rs      ← petgraph-based knowledge graph
```

### Integration Pattern

```python
# memgentic/processing/scrubber.py (existing file)
try:
    from memgentic._native.textproc import scrub_text as _native_scrub
    def scrub_text(text: str) -> ScrubResult:
        result = _native_scrub(text)
        return ScrubResult(**result)
except ImportError:
    # Fallback to pure Python (existing code)
    def scrub_text(text: str) -> ScrubResult:
        ...  # current implementation unchanged
```

This pattern means:
- **Zero breaking changes** — if Rust module isn't installed, pure Python works
- **Gradual adoption** — add Rust modules one at a time
- **Easy testing** — compare Rust vs Python outputs
- **Optional dependency** — users without Rust toolchain still use Memgentic normally

### Build Integration

```toml
# memgentic-native/pyproject.toml
[build-system]
requires = ["maturin>=1.0"]
build-backend = "maturin"

[project]
name = "memgentic-native"
requires-python = ">=3.12"

[tool.maturin]
features = ["pyo3/extension-module"]
```

```toml
# memgentic/pyproject.toml (add optional dependency)
[project.optional-dependencies]
native = ["memgentic-native"]
```

### Key Rust Crates

| Purpose | Crate | Why |
|---------|-------|-----|
| Python bindings | `pyo3` + `maturin` | Industry standard for Rust→Python |
| JSON streaming | `serde_json` (StreamDeserializer) | Zero-copy streaming parse |
| Regex | `regex` | 5-20x faster than Python re |
| Multi-pattern matching | `aho-corasick` | Credential scrubbing (14 patterns in one pass) |
| Parallelism | `rayon` | Batch text processing across cores |
| Graph | `petgraph` | Efficient graph data structures |
| Binary serialization | `bincode` or `rmp-serde` | Fast graph persistence |
| Protobuf wire format | `prost` or `bytes` | Antigravity adapter parsing |
| Unicode | `unicode-segmentation` | Word boundary detection for Jaccard |

---

## 5. Implementation Roadmap

### Phase 1: Text Processing (Highest ROI, Lowest Risk)

**Scope:** Credential scrubbing + noise detection + text overlap

**Why first:**
- Self-contained functions with clear inputs/outputs
- Easy to test: compare Rust output vs Python output
- Immediate benefit on every ingestion
- Lowest integration complexity

**Deliverables:**
- `memgentic-native` crate with `textproc` module
- `scrub_text()`, `is_noise()`, `text_overlap()`, `batch_process()`
- Python fallback wrappers
- Benchmark suite comparing Rust vs Python

### Phase 2: Conversation Parsers

**Scope:** Claude Code JSONL + ChatGPT JSON + Antigravity Protobuf parsers

**Why second:**
- Directly addresses the memory usage problem (streaming vs load-all)
- Claude Code is the primary adapter (most users)
- Protobuf parsing is a natural Rust fit

**Deliverables:**
- Streaming JSONL parser with XML tag cleaning
- ChatGPT tree flattener with chronological sort
- Protobuf wire-format parser
- Memory benchmarks (peak RSS comparison)

### Phase 3: Knowledge Graph Engine

**Scope:** Replace NetworkX with Rust-backed graph

**Why third:**
- Requires more complex PyO3 (stateful object, not just functions)
- Impact grows with user's memory count (matters more over time)
- Binary serialization eliminates JSON load/save overhead

**Deliverables:**
- `KnowledgeGraph` Python class backed by Rust
- Binary persistence (bincode/MessagePack)
- Graph query operations (BFS, neighbor lookup)
- Migration script from existing JSON graph

### Phase 4 (Optional): Search Ranking

**Scope:** RRF scoring + temporal decay + result merging

**Why optional:**
- Current Python implementation is fast enough for typical result sets (10-50 items)
- Only matters at scale (10K+ results to rank)
- Could be worth it if combined with batch re-ranking

---

## 6. Effort vs. Impact Matrix

```
                        HIGH IMPACT
                            │
     Phase 3                │  Phase 1          Phase 2
     Knowledge Graph        │  Text Processing  Parsers
     ┌──────────────┐       │  ┌──────────────┐ ┌──────────────┐
     │ 10-50x graph │       │  │ 20-50x scrub │ │ 5-10x parse  │
     │ 3-5x memory  │       │  │ 10-20x dedup │ │ 3-5x memory  │
     │              │       │  │              │ │              │
     │ ~3 weeks     │       │  │ ~1-2 weeks   │ │ ~2-3 weeks   │
     └──────────────┘       │  └──────────────┘ └──────────────┘
                            │
  HIGH EFFORT ──────────────┼────────────────── LOW EFFORT
                            │
                            │  Phase 4
                            │  Search Ranking
                            │  ┌──────────────┐
                            │  │ 2-3x ranking │
                            │  │ ~1 week      │
                            │  └──────────────┘
                            │
                        LOW IMPACT
```

**Recommendation:** Start with Phase 1 (best ROI), then Phase 2 (biggest user-visible improvement), then Phase 3 (scales with growth).

---

## 7. Rust Learning Path

Since you have zero Rust knowledge, here's a focused path for this project:

### Week 1-2: Foundations
- **The Rust Book** (chapters 1-10): ownership, borrowing, structs, enums, pattern matching
- **Rustlings** exercises: hands-on practice
- Focus: understand ownership model (this is 80% of Rust)

### Week 3: PyO3 Basics
- Build a "hello world" PyO3 module with maturin
- Expose a simple function to Python
- Learn `#[pyfunction]`, `#[pyclass]`, `#[pymethods]`

### Week 4: First Real Module
- Implement `text_overlap()` in Rust (simple, testable)
- Benchmark against Python version
- This builds confidence and teaches the workflow

### Ongoing: Learn by Building
- Each phase of the roadmap teaches new Rust concepts:
  - Phase 1: strings, regex, iterators, HashMap
  - Phase 2: serde, streaming I/O, error handling
  - Phase 3: structs, traits, graph algorithms, serialization

### Key Resources
- **The Rust Book**: https://doc.rust-lang.org/book/
- **PyO3 User Guide**: https://pyo3.rs/
- **Maturin docs**: https://www.maturin.rs/
- **Rust by Example**: https://doc.rust-lang.org/rust-by-example/

---

## Appendix A: What NOT to Rewrite

To be explicit about scope — these should remain Python:

| Component | Why Keep Python |
|-----------|----------------|
| MCP Server (FastMCP) | I/O-bound, great library ecosystem |
| REST API (FastAPI) | I/O-bound, excellent for this use case |
| Embedding client | Network I/O, thin HTTP wrapper |
| Qdrant client | Network I/O, official Python SDK |
| LLM pipeline (LangChain) | Network I/O, Python-only ecosystem |
| CLI (Click + Rich) | UX library, not performance-sensitive |
| Config (Pydantic) | Validation library, not performance-sensitive |
| File watcher (watchdog) | OS-native events, Python overhead negligible |
| SQLite operations | C-backed library, Python layer is thin |
| Dashboard (Next.js) | JavaScript ecosystem, unrelated |

---

## Appendix B: Alternative Approaches Considered

### Full Rust Rewrite
**Rejected.** The Python ecosystem for LLM/ML tooling (LangChain, FastMCP, Qdrant client, Ollama integration) is irreplaceable. A full rewrite would mean reimplementing dozens of libraries. The 80/20 rule applies: Rust for the CPU-bound 20%, Python for the I/O-bound 80%.

### Rust Microservice (Separate Process)
**Rejected.** Adding IPC overhead (HTTP/gRPC between Python and Rust) would negate the performance gains for small operations like text scrubbing. PyO3 in-process calls have nanosecond overhead.

### C Extensions Instead of Rust
**Rejected.** Rust provides memory safety guarantees that C doesn't. PyO3/maturin has better developer experience than CPython C API. Rust's package ecosystem (crates.io) is more modern.

### WASM for Cross-Platform
**Considered but deferred.** Could be useful if Memgentic adds browser-based processing. Not needed for the current local-first architecture.

---

## Appendix C: Expected Performance Gains Summary

| Operation | Current (Python) | With Rust | Improvement |
|-----------|-----------------|-----------|-------------|
| Credential scrub (per text) | ~500μs | ~10-25μs | 20-50x |
| Noise detection (per text) | ~200μs | ~20-40μs | 5-10x |
| Text overlap (per pair) | ~100μs | ~5-10μs | 10-20x |
| Claude Code parse (10MB file) | ~3-5s | ~0.3-0.5s | 10x |
| ChatGPT import (50MB export) | ~8-15s | ~1-2s | 5-8x |
| Protobuf parse (5MB .pb) | ~2-4s | ~0.1-0.2s | 15-30x |
| Graph add_memory (10K nodes) | ~50ms | ~1-2ms | 25-50x |
| Graph BFS query (depth=3) | ~20ms | ~0.5-1ms | 20-40x |
| Graph save/load (10K nodes) | ~500ms | ~20-50ms | 10-25x |
| Bulk import 1000 memories | ~45min* | ~15min* | ~3x |

*Bulk import dominated by embedding I/O; Rust speeds up the CPU portions between I/O calls.

**Note:** These are estimates based on typical Rust-vs-Python benchmarks for similar workloads. Actual gains depend on data characteristics and hardware. The estimates are conservative.
