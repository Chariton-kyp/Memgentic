"""LongMemEval runner.

A thin shell over :class:`benchmarks.lib.harness.BenchmarkHarness`
plus :func:`benchmarks.lib.corpus_loader.load_longmemeval`; everything
reusable lives in those modules so the same pattern drives LoCoMo,
ConvoMem, MemBench and Cross-Tool Transfer.

Usage::

    python -m benchmarks.runners.longmemeval_bench \\
        --dataset /path/to/longmemeval_s.json \\
        --profile raw \\
        --k 5

The runner does NOT auto-download the dataset. When ``--dataset`` points
at a missing file the runner prints a clear error and exits ``2`` so CI
failures are easy to distinguish from a runtime exception.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

from benchmarks.lib.corpus_loader import CorpusLoaderError, load_longmemeval
from benchmarks.lib.harness import BenchmarkHarness
from memgentic.processing.query_features import extract_features
from memgentic.processing.query_rewriter import QueryRewriter
from memgentic.retrieval.feature_boost import apply_feature_boosts


async def run(
    dataset_path: str | Path,
    profile: str = "raw",
    k: int = 5,
    output_dir: str | Path = "benchmarks/results",
    *,
    harness: BenchmarkHarness | None = None,
    retrieval_mode: str = "dense",
    dense_weight: float = 1.0,
    bm25_weight: float = 1.0,
    include_roles: frozenset[str] | None = None,
    session_concat: bool = False,
    reranker_path: str | Path | None = None,
    rerank_top_k: int = 30,
    question_aware_boosts: bool = False,
    rewrite_query_with: str | None = None,
) -> Path:
    """Run LongMemEval end-to-end and write the JSONL result file.

    Matches the LongMemEval pattern: build harness → ingest every
    haystack session → score every question → write JSONL → print the
    aggregate ``R@k`` number. Returns the path to the JSONL for the caller.

    Args:
        dataset_path: Path to the LongMemEval JSON file on disk.
        profile: Capture profile forwarded to the ingestion pipeline.
        k: Top-k cut-off for recall@k.
        output_dir: Root of the benchmark-results tree.
        harness: Optional pre-built harness (for tests). When omitted,
            the runner builds and tears down its own.
        include_roles: Optional frozenset of conversation roles to ingest.
            Defaults to None (all roles). Pass ``frozenset({"user"})`` to
            replicate the MemPalace LongMemEval pattern that drops
            assistant turns from the indexed unit.
    """
    sessions, questions = load_longmemeval(
        dataset_path,
        include_roles=include_roles,
        session_concat=session_concat,
    )

    if harness is None:
        owns_harness = True
        reranker = None
        if reranker_path is not None:
            from memgentic.retrieval.reranker import LlamaCppReranker

            reranker = LlamaCppReranker(model_path=str(reranker_path))
        active = BenchmarkHarness(
            profile=profile,
            embedder="qwen3-0.6b",
            backend="sqlite-vec",
            reranker=reranker,
        )
        await active.setup()
    else:
        owns_harness = False
        active = harness
    rewriter: QueryRewriter | None = None
    if rewrite_query_with:
        rewriter = QueryRewriter(model=rewrite_query_with)

    try:
        for session in sessions:
            await active.ingest_session(session)

        # Pre-expand all queries once so rewriter latency lives outside
        # the per-question loop and the cost is visible as a single batch.
        if rewriter is not None:
            expanded_texts = await rewriter.expand_many(
                [q.text for q in questions], mode="concat"
            )
            for question, expanded in zip(questions, expanded_texts, strict=True):
                # Replace question text in-place so downstream code uses the
                # expansion. The original .text is preserved on the JSONL
                # record so post-hoc analysis can compare.
                question._original_text = question.text  # type: ignore[attr-defined]
                question.text = expanded

        records: list[dict[str, Any]] = []
        # Over-fetch chunks so that, after collapsing duplicate session_ids,
        # we still have at least ``k`` unique sessions to score against.
        # Without this, a single session contributing many top-ranked chunks
        # eats the top-k slots and starves the recall metric — that was the
        # observed failure mode where reranker put 3 chunks of the gold
        # session at ranks 1-3 but R@5 only counted 3 unique sessions.
        chunk_fetch = max(k * 6, 30)

        for question in questions:
            if retrieval_mode == "hybrid":
                hits = await active.search_hybrid(
                    question.text,
                    n_results=chunk_fetch,
                    dense_weight=dense_weight,
                    bm25_weight=bm25_weight,
                )
            elif retrieval_mode == "rerank":
                # retrieve_k must be >= n_results for the reranker to have
                # enough candidates to fill the requested chunk_fetch slots.
                hits = await active.search_with_rerank(
                    question.text,
                    n_results=chunk_fetch,
                    retrieve_k=max(rerank_top_k, chunk_fetch),
                )
            else:
                hits = await active.search(question.text, n_results=chunk_fetch)
            # Question-aware boosts: extract regex features from the query
            # (temporal / quoted / proper-noun) and re-score candidates by
            # combining cosine with rule-based multipliers. Empty features
            # leave order intact.
            if question_aware_boosts:
                features = extract_features(question.text)
                hits = apply_feature_boosts(hits, features)
            # Collapse to first-seen unique session_ids, then truncate to k.
            seen: set[str] = set()
            retrieved_session_ids: list[str] = []
            for hit in hits:
                sid = (hit.get("payload") or {}).get("session_id")
                if sid is None or sid in seen:
                    continue
                seen.add(sid)
                retrieved_session_ids.append(sid)
                if len(retrieved_session_ids) >= k:
                    break
            recall = any(sid in question.gold for sid in retrieved_session_ids)
            rank_of_gold = next(
                (i + 1 for i, sid in enumerate(retrieved_session_ids) if sid in question.gold),
                None,
            )
            records.append(
                {
                    "question_id": question.id,
                    "question": question.text,
                    "gold_session_ids": sorted(question.gold),
                    "retrieved_session_ids": retrieved_session_ids,
                    "rank_of_gold": rank_of_gold,
                    "recall_at_k": recall,
                    "category": question.category,
                }
            )

        # Output layout: results/{dataset}/{profile}/{timestamp}.jsonl
        # so sweeps across profiles / reruns never clobber each other.
        timestamp = _dt.datetime.now(tz=_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(output_dir) / "longmemeval" / profile / f"{timestamp}.jsonl"
        active.write_jsonl(records, out_path)

        if records:
            recall_rate = sum(1 for r in records if r["recall_at_k"]) / len(records)
            print(f"R@{k} = {recall_rate:.4f}  (n={len(records)}, profile={profile})")
        else:
            print(f"R@{k} = n/a  (no questions in dataset, profile={profile})")

        return out_path
    finally:
        if owns_harness:
            await active.teardown()
        if rewriter is not None:
            await rewriter.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "LongMemEval retrieval benchmark runner. Requires the dataset "
            "to already be on disk (see benchmarks/datasets/README.md)."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/datasets/longmemeval_s.json"),
        help="Path to the LongMemEval JSON file on disk.",
    )
    parser.add_argument(
        "--profile",
        default="raw",
        choices=["raw", "enriched", "dual"],
        help="Capture profile.",
    )
    parser.add_argument("--k", type=int, default=5, help="Top-k for R@k.")
    parser.add_argument(
        "--retrieval-mode",
        default="dense",
        choices=["dense", "hybrid", "rerank"],
        help=(
            "Retrieval mode: 'dense' uses vector search only; "
            "'hybrid' fuses dense + BM25/FTS5 via reciprocal rank fusion; "
            "'rerank' over-fetches dense candidates and re-scores them "
            "with a cross-encoder. Default: dense."
        ),
    )
    parser.add_argument(
        "--reranker",
        type=Path,
        default=None,
        help=(
            "Path to a Qwen3-Reranker GGUF (e.g. ggml-org/Qwen3-Reranker-0.6B-Q8_0). "
            "Required when --retrieval-mode rerank."
        ),
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=30,
        help=(
            "How many candidates to fetch from dense before reranking. "
            "Default 30. Higher = better recall ceiling, slower."
        ),
    )
    parser.add_argument(
        "--question-aware-boosts",
        action="store_true",
        help=(
            "Apply rule-based regex boosts (temporal proximity, quoted-"
            "phrase exact match, proper-noun mentions) to retrieval "
            "candidates before truncating to top-k unique sessions. "
            "Bilingual (Greek + English). Pure regex, no extra deps."
        ),
    )
    parser.add_argument(
        "--rewrite-query-with",
        default=None,
        help=(
            "Ollama model name to use for query expansion (keyword "
            "rewriter). Example: --rewrite-query-with gemma4:e2b. "
            "When set, every benchmark question is expanded to "
            "'query\\nkeyword1, keyword2, ...' before embedding. "
            "Adds ~1-2s per query but broadens the embedder's vocabulary."
        ),
    )
    parser.add_argument(
        "--dense-weight",
        type=float,
        default=1.0,
        help="RRF weight for the dense list when --retrieval-mode hybrid.",
    )
    parser.add_argument(
        "--bm25-weight",
        type=float,
        default=1.0,
        help="RRF weight for the BM25 list when --retrieval-mode hybrid.",
    )
    parser.add_argument(
        "--user-turns-only",
        action="store_true",
        help=(
            "Ingest only user-role turns (drop assistant). Replicates the "
            "MemPalace LongMemEval pattern; assistant turns are mostly "
            "noise that pulls embedding centroids away from concise "
            "user-fact phrasing."
        ),
    )
    parser.add_argument(
        "--session-concat",
        action="store_true",
        help=(
            "Concatenate all kept turns into ONE document per session "
            "instead of one document per turn. Combine with "
            "--user-turns-only to reproduce the MemPalace 96.6% R@5 "
            "indexing unit (one user-only doc per session)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/results"),
        help="Where to write the JSONL results file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.dataset.exists():
        print(
            f"error: LongMemEval dataset not found at {args.dataset}.\n"
            "Phase-1 runners do not auto-download datasets.\n"
            "Run benchmarks/datasets/download.sh or pass --dataset explicitly.",
            file=sys.stderr,
        )
        return 2

    try:
        asyncio.run(
            run(
                args.dataset,
                profile=args.profile,
                k=args.k,
                output_dir=args.output_dir,
                retrieval_mode=args.retrieval_mode,
                dense_weight=args.dense_weight,
                bm25_weight=args.bm25_weight,
                include_roles=frozenset({"user"}) if args.user_turns_only else None,
                session_concat=args.session_concat,
                reranker_path=args.reranker,
                rerank_top_k=args.rerank_top_k,
                question_aware_boosts=args.question_aware_boosts,
                rewrite_query_with=args.rewrite_query_with,
            )
        )
    except CorpusLoaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
