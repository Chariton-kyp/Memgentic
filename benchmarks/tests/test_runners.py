"""Runner-level tests for Phase 2 benchmark runners.

These tests exercise the *shape* of every runner without spinning up
Ollama or a real vector store. A fake harness subclass overrides
``setup``/``teardown``/``ingest_session``/``search`` so the rest of the
pipeline runs in pure Python and completes in milliseconds.

Parametrised across:

* LongMemEval      (phase 1, kept here for regression coverage)
* LoCoMo           (phase 2)
* ConvoMem         (phase 2)
* MemBench         (phase 2)
* Cross-Tool Transfer (phase 2, Memgentic-original)

Each case asserts:

1. The runner's ``main(["--help"])`` prints its usage without crashing
   (via ``_parse_args`` indirectly — no process fork).
2. ``run()`` with an injected fake harness loads the tiny fixture,
   writes one JSONL line per question, and puts the file at the
   expected nested path ``benchmarks/results/{dataset}/{profile}/…``.
3. Each record carries the expected scoring key (``recall_at_k`` for
   recall-based benches, ``precision_at_k`` for Cross-Tool).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from benchmarks.lib.harness import BenchmarkHarness, BenchmarkQuery, CorpusSession
from benchmarks.runners import (
    convomem_bench,
    cross_tool_transfer_bench,
    locomo_bench,
    longmemeval_bench,
    membench_bench,
)

FIXTURES = Path(__file__).parent / "fixtures"
CTT_EXAMPLE = (
    Path(__file__).resolve().parents[1] / "datasets" / "cross_tool_transfer" / "example.jsonl"
)


class _FakeHarness(BenchmarkHarness):
    """Stand-in harness that skips the real Memgentic stack.

    Records every ingested session so tests can assert the corpus was
    walked, and returns canned hits keyed by query text so scoring has
    something deterministic to score against.
    """

    def __init__(
        self,
        profile: str = "raw",
        *,
        canned: dict[str, list[dict[str, Any]]] | None = None,
        default_hit_session_ids: list[str] | None = None,
    ) -> None:
        super().__init__(profile=profile)
        self.ingested: list[CorpusSession] = []
        self._canned = canned or {}
        # When a query has no canned list, synthesise a hit list that
        # always puts the first ingested session at rank 1. Tests set
        # this so scoring is non-trivial (recall_at_k is True).
        self._default_hit_session_ids = default_hit_session_ids or []

    async def setup(self) -> None:  # pragma: no cover — deliberately a no-op
        return None

    async def teardown(self) -> None:  # pragma: no cover
        return None

    async def ingest_session(self, session: CorpusSession) -> None:
        self.ingested.append(session)

    async def search(self, text: str, n_results: int = 5) -> list[dict[str, Any]]:
        if text in self._canned:
            return self._canned[text][:n_results]
        # Build a default hit list from whichever session IDs the test
        # pinned; fall back to the IDs of the first ingested sessions.
        sids = self._default_hit_session_ids or [s.session_id for s in self.ingested]
        hits = [
            {"id": f"m-{idx}", "score": 1.0 - (idx * 0.01), "payload": {"session_id": sid}}
            for idx, sid in enumerate(sids)
        ]
        return hits[:n_results]


# ---------------------------------------------------------------------------
# Runner registry — parametrise across each Phase-2 runner
# ---------------------------------------------------------------------------
RunnerCase = dict[str, Any]

RUNNER_CASES: list[RunnerCase] = [
    {
        "id": "longmemeval",
        "module": longmemeval_bench,
        "dataset": FIXTURES / "longmemeval_tiny.json",
        "expected_dir": "longmemeval",
        "score_key": "recall_at_k",
        "expected_min_records": 2,
    },
    {
        "id": "locomo",
        "module": locomo_bench,
        "dataset": FIXTURES / "locomo_tiny.json",
        "expected_dir": "locomo",
        "score_key": "recall_at_k",
        "expected_min_records": 2,
    },
    {
        "id": "convomem",
        "module": convomem_bench,
        "dataset": FIXTURES / "convomem_tiny.json",
        "expected_dir": "convomem",
        "score_key": "recall_at_k",
        "expected_min_records": 2,
    },
    {
        "id": "membench",
        "module": membench_bench,
        "dataset": FIXTURES / "membench_tiny.jsonl",
        "expected_dir": "membench",
        "score_key": "recall_at_k",
        "expected_min_records": 2,
    },
    {
        "id": "cross_tool_transfer",
        "module": cross_tool_transfer_bench,
        "dataset": CTT_EXAMPLE,
        "expected_dir": "cross_tool_transfer",
        "score_key": "precision_at_k",
        "expected_min_records": 2,
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", RUNNER_CASES, ids=[c["id"] for c in RUNNER_CASES])
class TestRunnerShape:
    """Shared assertions every runner must satisfy."""

    def test_help_parses(self, case: RunnerCase) -> None:
        module: ModuleType = case["module"]
        with pytest.raises(SystemExit) as excinfo:
            module._parse_args(["--help"])
        # argparse exits 0 after printing help text.
        assert excinfo.value.code == 0

    def test_missing_dataset_exits_two(self, case: RunnerCase, tmp_path: Path) -> None:
        module: ModuleType = case["module"]
        missing = tmp_path / "does_not_exist.json"
        rc = module.main(["--dataset", str(missing), "--output-dir", str(tmp_path / "out")])
        assert rc == 2

    async def test_run_writes_jsonl(self, case: RunnerCase, tmp_path: Path) -> None:
        module: ModuleType = case["module"]
        dataset: Path = case["dataset"]
        assert dataset.exists(), f"Test fixture missing: {dataset}"

        harness = _FakeHarness(profile="raw")

        run_fn: Callable[..., Awaitable[Path]] = module.run
        out_path = await run_fn(
            dataset,
            profile="raw",
            k=5,
            output_dir=tmp_path,
            harness=harness,
        )

        assert out_path.exists(), f"Runner {case['id']} did not write an output file"
        # Expected nested layout: {output_dir}/{dataset}/{profile}/{timestamp}.jsonl
        expected_dir = tmp_path / case["expected_dir"] / "raw"
        assert out_path.parent == expected_dir, (
            f"Expected output under {expected_dir}, got {out_path}"
        )
        assert out_path.suffix == ".jsonl"

        lines = [line for line in out_path.read_text().splitlines() if line.strip()]
        assert len(lines) >= case["expected_min_records"], (
            f"Runner {case['id']} wrote {len(lines)} records, "
            f"expected >= {case['expected_min_records']}"
        )

        # Every line must be valid JSON with the runner's score key.
        for line in lines:
            record = json.loads(line)
            assert "question_id" in record
            assert "question" in record
            assert case["score_key"] in record, (
                f"Runner {case['id']} record missing {case['score_key']!r}: {record}"
            )
            # Scoring key type sanity.
            if case["score_key"] == "recall_at_k":
                assert isinstance(record["recall_at_k"], bool)
            elif case["score_key"] == "precision_at_k":
                assert isinstance(record["precision_at_k"], int | float)

    async def test_run_ingests_sessions(self, case: RunnerCase, tmp_path: Path) -> None:
        module: ModuleType = case["module"]
        dataset: Path = case["dataset"]

        harness = _FakeHarness(profile="raw")
        await module.run(
            dataset,
            profile="raw",
            k=5,
            output_dir=tmp_path,
            harness=harness,
        )
        assert harness.ingested, f"Runner {case['id']} did not ingest any sessions from fixture"


# ---------------------------------------------------------------------------
# Profile pass-through — lives here rather than test_harness.py because it
# only matters now that Phase 2 wires the profile through to the pipeline.
# ---------------------------------------------------------------------------
class TestProfilePassThrough:
    async def test_profile_reaches_pipeline(self) -> None:
        """``ingest_session`` must forward the harness profile as ``capture_profile``."""
        captured: dict[str, Any] = {}

        class _FakePipeline:
            async def ingest_conversation(self, **kwargs: Any) -> list[Any]:
                captured.update(kwargs)
                return []

        harness = BenchmarkHarness(profile="enriched")
        # Bypass setup() so we don't spin up real stores.
        harness._pipeline = _FakePipeline()  # type: ignore[assignment]

        from memgentic.models import ContentType, ConversationChunk

        session = CorpusSession(
            session_id="s-1",
            chunks=[
                ConversationChunk(
                    content="hello world",
                    content_type=ContentType.RAW_EXCHANGE,
                    topics=[],
                    entities=[],
                    confidence=1.0,
                )
            ],
        )
        await harness.ingest_session(session)

        assert captured.get("capture_profile") == "enriched"
        assert captured.get("session_id") == "s-1"

    async def test_search_hits_are_scored(self) -> None:
        """A runner scoring with canned hits should see a positive recall."""
        queries = [BenchmarkQuery(id="q1", text="question A", gold={"s-1"})]
        harness = _FakeHarness(
            profile="raw",
            canned={"question A": [{"id": "m1", "score": 0.9, "payload": {"session_id": "s-1"}}]},
        )

        def scorer(query: BenchmarkQuery, hits: list[dict[str, Any]]) -> dict[str, Any]:
            retrieved = [(h.get("payload") or {}).get("session_id") for h in hits]
            return {"retrieved": retrieved, "hit": any(r in query.gold for r in retrieved)}

        records = await harness.evaluate(queries, scorer=scorer, k=1)
        assert records[0]["hit"] is True
