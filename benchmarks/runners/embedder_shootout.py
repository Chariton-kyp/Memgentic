"""Embedder shootout — compare candidate text embedders on memory recall.

Pure-embedder evaluation: no LLM enrichment, no BM25 hybrid, no reranker.
Each model is loaded fresh; documents and queries go through the
asymmetric ``embed_document`` / ``embed_query`` API so model-specific
prefixes are applied. Cosine similarity ranks the corpus per query and
the harness reports R@1, R@5, and MRR per model.

The corpus deliberately mixes Greek, English, and short technical text
to expose the failure mode that surfaced on v0.7.0: cosine ~0.05 on
relevant Greek/technical queries with the previous Qwen3-only default.

Usage::

    python -m benchmarks.runners.embedder_shootout
    python -m benchmarks.runners.embedder_shootout --models bge-m3,embeddinggemma:300m
    python -m benchmarks.runners.embedder_shootout --json results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memgentic.config import EmbeddingProvider, MemgenticSettings, StorageBackend
from memgentic.processing.embedder import Embedder

# Native dimensions per model — used so each model is evaluated at its
# strongest configuration (no MRL truncation that would penalise it).
_NATIVE_DIMS: dict[str, int] = {
    "qwen3-embedding:0.6b": 1024,
    "embeddinggemma:300m": 768,
    "bge-m3": 1024,
    "all-minilm:latest": 384,
    "granite-embedding:30m": 384,
}

DEFAULT_MODELS = ["qwen3-embedding:0.6b", "embeddinggemma:300m", "bge-m3"]


@dataclass(frozen=True)
class Doc:
    """One indexable document in the shootout corpus."""

    id: str
    text: str
    lang: str  # "el" | "en" | "code"


@dataclass(frozen=True)
class Query:
    """One evaluation query and its gold-relevant document IDs."""

    text: str
    gold: tuple[str, ...]
    lang: str


# Mini corpus: 12 docs across Greek prose, English prose, and technical text.
# Each doc has at least one query that should retrieve it.
CORPUS: tuple[Doc, ...] = (
    # --- Greek prose ---
    Doc(
        "el-cooking",
        "Η μουσακάς φτιάχνεται με μελιτζάνες, κιμά και μπεσαμέλ. "
        "Είναι παραδοσιακό ελληνικό φαγητό.",
        "el",
    ),
    Doc(
        "el-tech",
        "Το PostgreSQL υποστηρίζει JSONB column type για ευέλικτη "
        "αποθήκευση δεδομένων χωρίς αυστηρό schema.",
        "el",
    ),
    Doc(
        "el-history",
        "Ο Μέγας Αλέξανδρος γεννήθηκε στην Πέλλα το 356 π.Χ. και έγινε "
        "βασιλιάς της Μακεδονίας στα 20 του χρόνια.",
        "el",
    ),
    Doc(
        "el-product",
        "Σχεδιάζουμε ένα memory layer που ακολουθεί τον χρήστη από το "
        "Claude Code στον Cursor χωρίς να χρειάζεται επανάληψη του context.",
        "el",
    ),
    # --- English prose ---
    Doc(
        "en-cooking",
        "Pasta carbonara is made with eggs, guanciale, pecorino romano "
        "cheese and freshly ground black pepper. No cream is used.",
        "en",
    ),
    Doc(
        "en-tech",
        "SQLite supports full-text search via the FTS5 virtual table "
        "module. It uses BM25 ranking by default since version 3.20.",
        "en",
    ),
    Doc(
        "en-history",
        "Alan Turing proposed a test for machine intelligence in 1950 "
        "in his paper 'Computing Machinery and Intelligence'.",
        "en",
    ),
    Doc(
        "en-product",
        "We design a memory layer that follows the user from Claude Code "
        "to Cursor without needing to repeat context.",
        "en",
    ),
    # --- Technical / code ---
    Doc(
        "code-rrf",
        "Reciprocal Rank Fusion (RRF) combines multiple ranked lists. "
        "Score formula is sum of 1/(k+rank) per list, with k=60 default.",
        "code",
    ),
    Doc(
        "code-vec",
        "sqlite-vec is a SQLite extension that adds vector storage and "
        "k-nearest-neighbor search via the vec0 virtual table.",
        "code",
    ),
    Doc(
        "code-mcp",
        "The Model Context Protocol (MCP) lets LLM clients discover and "
        "call tools exposed by a server, transported over stdio or HTTP.",
        "code",
    ),
    Doc(
        "code-asyncio",
        "asyncio.gather runs multiple awaitables concurrently and returns "
        "results in input order. Exceptions surface unless return_exceptions=True.",
        "code",
    ),
)


# 18 queries — multilingual, with deliberate paraphrases (no exact keyword
# overlap) to test semantic recall, not lexical match.
QUERIES: tuple[Query, ...] = (
    # Greek paraphrases of Greek docs
    Query("πώς φτιάχνω παραδοσιακό ελληνικό φαγητό", ("el-cooking",), "el"),
    Query("βάση δεδομένων χωρίς σταθερή δομή για ευέλικτη αποθήκευση", ("el-tech",), "el"),
    Query("πότε γεννήθηκε ο μεγάλος βασιλιάς της αρχαίας Μακεδονίας", ("el-history",), "el"),
    Query("εργαλείο μνήμης για μετάβαση μεταξύ AI editors", ("el-product", "en-product"), "el"),
    # Greek query → English doc (cross-lingual)
    Query("τι είναι το reciprocal rank fusion", ("code-rrf",), "el"),
    Query("τι κάνει το sqlite-vec extension", ("code-vec",), "el"),
    # English paraphrases of English docs
    Query("traditional Italian pasta dish without cream", ("en-cooking",), "en"),
    Query("how does sqlite do keyword search ranking", ("en-tech",), "en"),
    Query("who proposed the imitation game for machine intelligence", ("en-history",), "en"),
    Query("memory tool that carries context across AI coding assistants", ("en-product", "el-product"), "en"),
    # English query → Greek doc (cross-lingual)
    Query("ancient Greek king of Macedonia born in Pella", ("el-history",), "en"),
    Query("traditional Greek dish with eggplant minced meat and bechamel", ("el-cooking",), "en"),
    # Technical queries → technical docs
    Query("score combining strategy across multiple ranking lists", ("code-rrf",), "code"),
    Query("vector search inside SQLite", ("code-vec",), "code"),
    Query("protocol for LLM clients to call server-side tools", ("code-mcp",), "code"),
    Query("python concurrent task execution helper", ("code-asyncio",), "code"),
    # Hard cases — short keyword query
    Query("RRF k=60", ("code-rrf",), "code"),
    Query("ΜΟΥΣΑΚΑΣ", ("el-cooking",), "el"),
)


@dataclass
class ModelResult:
    model: str
    dim: int
    corpus_embed_seconds: float
    query_embed_seconds: float
    r_at_1: float
    r_at_5: float
    mrr: float
    per_query_top_score: list[float] = field(default_factory=list)
    per_query_gold_rank: list[int | None] = field(default_factory=list)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. No deps so this script stands alone."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _rank_of_first_gold(ranked_doc_ids: list[str], gold: tuple[str, ...]) -> int | None:
    """1-indexed rank of the first gold ID, or None if no gold appears."""
    gold_set = set(gold)
    for i, doc_id in enumerate(ranked_doc_ids, start=1):
        if doc_id in gold_set:
            return i
    return None


async def evaluate_model(model: str, dim: int) -> ModelResult:
    """Embed corpus + queries, score, return ModelResult."""
    settings = MemgenticSettings(
        data_dir=Path("/tmp/memgentic-shootout-noop"),
        storage_backend=StorageBackend.SQLITE_VEC,
        embedding_provider=EmbeddingProvider.OLLAMA,
        embedding_model=model,
        embedding_dimensions=dim,
    )
    embedder = Embedder(settings)

    try:
        # --- Embed corpus ---
        t0 = time.perf_counter()
        doc_vectors: dict[str, list[float]] = {}
        for doc in CORPUS:
            doc_vectors[doc.id] = await embedder.embed_document(doc.text)
        corpus_secs = time.perf_counter() - t0

        # --- Embed queries + score ---
        t1 = time.perf_counter()
        per_query_top_score: list[float] = []
        per_query_gold_rank: list[int | None] = []

        for query in QUERIES:
            qvec = await embedder.embed_query(query.text)
            scored = sorted(
                ((doc_id, _cosine(qvec, dvec)) for doc_id, dvec in doc_vectors.items()),
                key=lambda kv: kv[1],
                reverse=True,
            )
            ranked_ids = [doc_id for doc_id, _ in scored]
            top_score = scored[0][1]
            gold_rank = _rank_of_first_gold(ranked_ids, query.gold)
            per_query_top_score.append(top_score)
            per_query_gold_rank.append(gold_rank)
        query_secs = time.perf_counter() - t1
    finally:
        await embedder.close()

    n = len(QUERIES)
    r_at_1 = sum(1 for r in per_query_gold_rank if r == 1) / n
    r_at_5 = sum(1 for r in per_query_gold_rank if r is not None and r <= 5) / n
    mrr = sum(1.0 / r for r in per_query_gold_rank if r is not None) / n

    return ModelResult(
        model=model,
        dim=dim,
        corpus_embed_seconds=corpus_secs,
        query_embed_seconds=query_secs,
        r_at_1=r_at_1,
        r_at_5=r_at_5,
        mrr=mrr,
        per_query_top_score=per_query_top_score,
        per_query_gold_rank=per_query_gold_rank,
    )


def _print_summary(results: list[ModelResult]) -> None:
    """Render the per-model aggregate table to stdout."""
    print()
    print(f"Corpus: {len(CORPUS)} docs   Queries: {len(QUERIES)}")
    print()
    header = f"{'model':<28} {'dim':>5} {'R@1':>6} {'R@5':>6} {'MRR':>6} {'corpus_s':>10} {'query_s':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.model:<28} {r.dim:>5} "
            f"{r.r_at_1:>6.3f} {r.r_at_5:>6.3f} {r.mrr:>6.3f} "
            f"{r.corpus_embed_seconds:>10.2f} {r.query_embed_seconds:>10.2f}"
        )
    print()


def _print_per_query_breakdown(results: list[ModelResult]) -> None:
    """Show, per query, the gold rank under each model — useful when one
    model wins on aggregate but loses on a critical category."""
    print("Per-query gold rank (lower is better, '-' means missed entirely):")
    print()
    width = 5
    head = f"{'#':>3} {'lang':>4} " + "".join(f"{r.model[:14]:>{width + 9}}" for r in results) + "  query"
    print(head)
    for i, query in enumerate(QUERIES):
        ranks = []
        for r in results:
            rk = r.per_query_gold_rank[i]
            top = r.per_query_top_score[i]
            cell = f"r={rk if rk is not None else '-':>2} ({top:>4.2f})"
            ranks.append(f"{cell:>{width + 9}}")
        print(f"{i + 1:>3} {query.lang:>4} " + "".join(ranks) + f"  {query.text[:60]}")
    print()


def _summary_top_score_distribution(results: list[ModelResult]) -> None:
    """Quick view of how confidently each model ranks its top candidate.

    Top scores stuck near 0 indicate the model can't separate any candidate
    from the noise — that's the failure mode the v0.7.0 recall test hit."""
    print("Top-1 cosine distribution (median / p10 / p90 across queries):")
    for r in results:
        scores = r.per_query_top_score
        med = statistics.median(scores)
        p10 = statistics.quantiles(scores, n=10)[0]
        p90 = statistics.quantiles(scores, n=10)[8]
        print(f"  {r.model:<28} median={med:>5.3f}  p10={p10:>5.3f}  p90={p90:>5.3f}")
    print()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare embedding models on a multilingual mini corpus. "
            "Pulls each model from Ollama on demand."
        )
    )
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Comma-separated Ollama model names (default: bge-m3 vs gemma vs qwen3-0.6b).",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional path to write the full results JSON for later diffing.",
    )
    parser.add_argument(
        "--no-breakdown",
        action="store_true",
        help="Skip the per-query breakdown table (just print the summary).",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("error: --models is empty", file=sys.stderr)
        return 2

    results: list[ModelResult] = []
    for model in models:
        dim = _NATIVE_DIMS.get(model)
        if dim is None:
            print(
                f"warn: unknown model '{model}' — defaulting to embedding_dimensions=1024",
                file=sys.stderr,
            )
            dim = 1024
        print(f"[shootout] evaluating {model} (dim={dim})...", file=sys.stderr)
        try:
            result = await evaluate_model(model, dim)
        except Exception as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            continue
        results.append(result)

    if not results:
        print("error: no models produced results", file=sys.stderr)
        return 1

    _print_summary(results)
    _summary_top_score_distribution(results)
    if not args.no_breakdown:
        _print_per_query_breakdown(results)

    if args.json:
        payload = [
            {
                "model": r.model,
                "dim": r.dim,
                "corpus_embed_seconds": r.corpus_embed_seconds,
                "query_embed_seconds": r.query_embed_seconds,
                "r_at_1": r.r_at_1,
                "r_at_5": r.r_at_5,
                "mrr": r.mrr,
                "per_query_top_score": r.per_query_top_score,
                "per_query_gold_rank": r.per_query_gold_rank,
            }
            for r in results
        ]
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"results written → {args.json}", file=sys.stderr)

    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
