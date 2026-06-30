"""3-arm A/B for the distilled recall surface (plan task T8).

Runs the SAME LongMemEval corpus through three arms, varying ONLY the recall
surface and the distiller, then prints R@k / MRR deltas:

    arm A  enable_distilled_recall_surface=False, distiller=local   (verbatim baseline)
    arm B  enable_distilled_recall_surface=True,  distiller=local   (distilled, local)
    arm C  enable_distilled_recall_surface=True,  distiller=Claude  (distilled, ceiling)

A→B isolates the FLAG (same distiller). B→C isolates the DISTILLER (flag on both).

Each arm gets its own isolated sqlite-vec store + collection, the same embedder,
and runs through the real ``IngestionPipeline`` (so distillation actually runs).
Arm C is skipped automatically when no Anthropic key is configured.

Example:
    uv run --no-sync python -m benchmarks.runners.distilled_ab \
        --dataset benchmarks/datasets/longmemeval_s_50.json \
        --max-questions 10 --session-concat \
        --embedder-model bge-m3 --embedder-dims 1024 \
        --local-model gemma4:e4b --claude-model claude-sonnet-4-6 \
        --arms A,B
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from memgentic.config import EmbeddingProvider, MemgenticSettings, StorageBackend

from benchmarks.lib.harness import BenchmarkHarness
from benchmarks.runners import longmemeval_bench


@dataclass
class Arm:
    name: str
    flag: bool
    llm_model: str  # "" / "local" routes to the --local-model; "claude" to --claude-model


def _resolve_model(token: str, *, local_model: str, claude_model: str) -> str:
    if token in ("local", ""):
        return local_model
    if token == "claude":
        return claude_model
    return token


def _slice_dataset(src: Path, n: int, tmp: Path) -> Path:
    """Write the first ``n`` questions of a LongMemEval JSON to a temp file."""
    data = json.loads(src.read_text(encoding="utf-8"))
    sliced = data[:n]
    out = tmp / f"{src.stem}_first{n}.json"
    out.write_text(json.dumps(sliced), encoding="utf-8")
    return out


def _summarize(records: list[dict], k: int) -> dict:
    n = len(records)
    if n == 0:
        return {"n": 0, "recall_at_k": 0.0, "mrr": 0.0}
    recall = sum(1 for r in records if r.get("recall_at_k")) / n
    mrr = sum(1.0 / r["rank_of_gold"] for r in records if r.get("rank_of_gold")) / n
    return {"n": n, "recall_at_k": recall, "mrr": mrr}


def _build_settings(arm: Arm, *, base_tmp: Path, embedder_model: str, dims: int) -> MemgenticSettings:
    data_dir = base_tmp / arm.name / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return MemgenticSettings(
        data_dir=data_dir,
        storage_backend=StorageBackend.SQLITE_VEC,
        collection_name=f"ab_{arm.name}",
        embedding_provider=EmbeddingProvider.OLLAMA,
        embedding_model=embedder_model,
        embedding_dimensions=dims,
        enable_credential_scrubbing=True,
        enable_distilled_recall_surface=arm.flag,
        enable_reranker=False,  # dense-only isolates the embedded-surface effect
        enable_local_llm=True,
    )


async def _run_arm(
    arm: Arm,
    *,
    dataset: Path,
    base_tmp: Path,
    embedder_model: str,
    dims: int,
    k: int,
    session_concat: bool,
) -> dict | None:
    settings = _build_settings(arm, base_tmp=base_tmp, embedder_model=embedder_model, dims=dims)

    # Arm C guard: a claude-* distiller with no key silently degrades to the
    # heuristic, which would be a misleading "distilled" arm. Skip loudly.
    if arm.llm_model.lower().startswith("claude-") and not settings.anthropic_api_key:
        print(f"  [skip] arm {arm.name}: distiller {arm.llm_model} needs ANTHROPIC_API_KEY (unset).")
        return None

    harness = BenchmarkHarness(
        profile="enriched",
        embedder=embedder_model,
        backend="sqlite-vec",
        settings_override=settings,
        llm_model=arm.llm_model,
    )
    await harness.setup()
    t0 = time.perf_counter()
    try:
        out_path = await longmemeval_bench.run(
            dataset,
            profile=f"ab-{arm.name}",
            k=k,
            output_dir=base_tmp / "results",
            harness=harness,
            retrieval_mode="dense",
            session_concat=session_concat,
        )
    finally:
        await harness.teardown()
    elapsed = time.perf_counter() - t0

    records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line]
    summary = _summarize(records, k)
    summary.update({"arm": arm.name, "flag": arm.flag, "distiller": arm.llm_model, "secs": elapsed})
    print(
        f"  [done] {arm.name}: R@{k}={summary['recall_at_k']:.4f}  "
        f"MRR={summary['mrr']:.4f}  (n={summary['n']}, {elapsed:.0f}s, distiller={arm.llm_model})"
    )
    return summary


async def main() -> None:
    # Force UTF-8 stdout so the arrow/delta glyphs in the report survive a
    # legacy Windows code page (e.g. cp1253) without an encode crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=Path("benchmarks/datasets/longmemeval_s_50.json"))
    ap.add_argument("--max-questions", type=int, default=0, help="0 = all questions in the dataset")
    ap.add_argument("--session-concat", action="store_true", help="1 chunk per session (faster, session-level)")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--embedder-model", default="bge-m3")
    ap.add_argument("--embedder-dims", type=int, default=1024)
    ap.add_argument("--local-model", default="gemma4:e4b", help="Ollama distiller tag for arms A/B")
    ap.add_argument("--claude-model", default="claude-sonnet-4-6", help="Anthropic distiller for arm C")
    ap.add_argument("--arms", default="A,B,C", help="comma list subset of A,B,C")
    args = ap.parse_args()

    arm_specs = {
        "A": Arm("A_verbatim_local", flag=False, llm_model="local"),
        "B": Arm("B_distilled_local", flag=True, llm_model="local"),
        "C": Arm("C_distilled_claude", flag=True, llm_model="claude"),
    }
    selected = [arm_specs[a.strip().upper()] for a in args.arms.split(",") if a.strip()]
    # Resolve the model tokens to concrete model names.
    for arm in selected:
        arm.llm_model = _resolve_model(
            arm.llm_model, local_model=args.local_model, claude_model=args.claude_model
        )

    base_tmp = Path(tempfile.mkdtemp(prefix="distilled-ab-"))
    dataset = args.dataset
    if args.max_questions and args.max_questions > 0:
        dataset = _slice_dataset(args.dataset, args.max_questions, base_tmp)

    print(
        f"Distilled-surface A/B | dataset={dataset.name} "
        f"k={args.k} session_concat={args.session_concat} "
        f"embedder={args.embedder_model}@{args.embedder_dims}"
    )
    print(f"workdir: {base_tmp}\n")

    summaries: list[dict] = []
    for arm in selected:
        print(f"[arm {arm.name}] flag={arm.flag} distiller={arm.llm_model} — ingesting + scoring…")
        s = await _run_arm(
            arm,
            dataset=dataset,
            base_tmp=base_tmp,
            embedder_model=args.embedder_model,
            dims=args.embedder_dims,
            k=args.k,
            session_concat=args.session_concat,
        )
        if s is not None:
            summaries.append(s)

    # --- Report ---------------------------------------------------------
    print("\n=== Results ===")
    by_name = {s["arm"]: s for s in summaries}
    for s in summaries:
        print(f"{s['arm']:<22} R@{args.k}={s['recall_at_k']:.4f}  MRR={s['mrr']:.4f}  (n={s['n']})")

    def _delta(a: str, b: str, label: str) -> None:
        if a in by_name and b in by_name:
            da = by_name[b]["recall_at_k"] - by_name[a]["recall_at_k"]
            dm = by_name[b]["mrr"] - by_name[a]["mrr"]
            print(f"{label:<28} ΔR@{args.k}={da:+.4f}  ΔMRR={dm:+.4f}")

    print()
    _delta("A_verbatim_local", "B_distilled_local", "A→B (flag, local distiller)")
    _delta("B_distilled_local", "C_distilled_claude", "B→C (distiller quality)")
    _delta("A_verbatim_local", "C_distilled_claude", "A→C (flag + Claude)")


if __name__ == "__main__":
    asyncio.run(main())
