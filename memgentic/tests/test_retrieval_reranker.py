"""Tests for memgentic.retrieval.reranker.

The real ``LlamaCppReranker`` talks to a llama-server over HTTP (``/v1/rerank``);
these tests drive it with an injected ``httpx`` transport (a FAKE rerank
endpoint) so no real server is required. Coverage:

- Interface contract (``RerankCandidate`` / ``RerankResult`` shape).
- ``MockReranker`` deterministic behaviour (harness/cascade tests).
- ``LlamaCppReranker`` HTTP client: parses scores, reorders, maps index→id,
  preserves payload; graceful ``[]`` (never raises) on unreachable / non-2xx /
  malformed body; the short-lived "down" cache short-circuits repeated calls.
- ``maybe_rerank``: reorders by absolute score, drops below
  ``reranker_min_score`` (the absolute floor), backfills recall from the tail,
  and is a graceful no-op when disabled / no reranker / server down.
"""

from __future__ import annotations

import json

import httpx
import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.retrieval.reranker import (
    LlamaCppReranker,
    MockReranker,
    RerankCandidate,
    RerankResult,
    _parse_rerank_response,
    maybe_rerank,
)

# ---------------------------------------------------------------------------
# Helpers — fake llama-server /v1/rerank transports
# ---------------------------------------------------------------------------


def _rerank_handler(scores_by_index: dict[int, float]):
    """Build a MockTransport handler that scores documents by submit index."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        docs = body["documents"]
        results = [
            {"index": i, "relevance_score": scores_by_index.get(i, 0.0)} for i in range(len(docs))
        ]
        return httpx.Response(200, json={"results": results})

    return handler


class _CountingFailTransport(httpx.AsyncBaseTransport):
    """Always raises ConnectError; counts how many requests it received."""

    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("connection refused")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(tmp_path, **overrides) -> MemgenticSettings:
    base = {
        "data_dir": tmp_path / "data",
        "storage_backend": StorageBackend.LOCAL,
        "enable_reranker": True,
        "reranker_top_k": 20,
        "reranker_min_score": 0.0,
    }
    base.update(overrides)
    return MemgenticSettings(**base)


def _fused(*ids_with_content: tuple[str, float, str]) -> list[dict]:
    """Build fused-result dicts: (id, relevance, content)."""
    return [
        {"id": mid, "score": rel, "relevance": rel, "payload": {"content": content}}
        for mid, rel, content in ids_with_content
    ]


# ---------------------------------------------------------------------------
# Scripted in-memory rerankers (for maybe_rerank wiring tests)
# ---------------------------------------------------------------------------


class _ScriptedReranker:
    """Returns predetermined absolute scores per candidate id."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls = 0

    async def rerank(self, query, candidates, top_k=None):
        self.calls += 1
        out = [
            RerankResult(id=c.id, score=self.scores.get(c.id, 0.0), payload=c.payload)
            for c in candidates
        ]
        out.sort(key=lambda r: r.score, reverse=True)
        return out


class _DownReranker:
    """Simulates an unreachable server — honours the contract by returning []."""

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, query, candidates, top_k=None):
        self.calls += 1
        return []


class _RaisingReranker:
    """A misbehaving reranker that raises — maybe_rerank must still not break."""

    async def rerank(self, query, candidates, top_k=None):
        raise RuntimeError("boom")


class _CapturingReranker:
    """Records the candidate texts it is handed; scores everything 1.0."""

    def __init__(self) -> None:
        self.seen_texts: list[str] = []

    async def rerank(self, query, candidates, top_k=None):
        self.seen_texts = [c.text for c in candidates]
        return [RerankResult(id=c.id, score=1.0, payload=c.payload) for c in candidates]


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


class TestRerankCandidateAndResult:
    def test_candidate_minimum_fields(self) -> None:
        c = RerankCandidate(id="m-1", text="hello world")
        assert c.id == "m-1"
        assert c.text == "hello world"
        assert c.payload is None

    def test_result_carries_payload_through(self) -> None:
        r = RerankResult(id="m-1", score=0.87, payload={"session_id": "s-a"})
        assert r.payload == {"session_id": "s-a"}


# ---------------------------------------------------------------------------
# MockReranker
# ---------------------------------------------------------------------------


class TestMockReranker:
    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self) -> None:
        assert await MockReranker().rerank("query", []) == []

    @pytest.mark.asyncio
    async def test_higher_overlap_ranks_higher(self) -> None:
        candidates = [
            RerankCandidate(id="m-1", text="completely unrelated content"),
            RerankCandidate(id="m-2", text="postgres database connection pool"),
            RerankCandidate(id="m-3", text="postgres connection"),
        ]
        result = await MockReranker().rerank("postgres connection pool", candidates)
        assert [r.id for r in result] == ["m-2", "m-3", "m-1"]

    @pytest.mark.asyncio
    async def test_top_k_truncates_output(self) -> None:
        candidates = [RerankCandidate(id=f"m-{i}", text=f"word{i} query") for i in range(5)]
        result = await MockReranker().rerank("query", candidates, top_k=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# LlamaCppReranker — HTTP client against a fake llama-server
# ---------------------------------------------------------------------------


class TestLlamaCppRerankerHTTP:
    @pytest.mark.asyncio
    async def test_scores_parsed_and_reordered(self) -> None:
        # Submit order m-a, m-b, m-c; server scores them 0.1 / 0.9 / 0.5.
        handler = _rerank_handler({0: 0.1, 1: 0.9, 2: 0.5})
        reranker = LlamaCppReranker(url="http://fake:8081", client=_client(handler))
        candidates = [
            RerankCandidate(id="m-a", text="alpha", payload={"k": "a"}),
            RerankCandidate(id="m-b", text="beta", payload={"k": "b"}),
            RerankCandidate(id="m-c", text="gamma", payload={"k": "c"}),
        ]
        out = await reranker.rerank("q", candidates)
        assert [r.id for r in out] == ["m-b", "m-c", "m-a"]
        assert out[0].score == pytest.approx(0.9)
        assert out[0].payload == {"k": "b"}  # payload mapped back by index

    @pytest.mark.asyncio
    async def test_zero_score_is_honoured_not_dropped(self) -> None:
        handler = _rerank_handler({0: 0.0, 1: 0.4})
        reranker = LlamaCppReranker(url="http://fake:8081", client=_client(handler))
        out = await reranker.rerank(
            "q", [RerankCandidate(id="z", text="x"), RerankCandidate(id="y", text="x")]
        )
        ids = {r.id: r.score for r in out}
        assert ids["z"] == pytest.approx(0.0)
        assert ids["y"] == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_empty_candidates_makes_no_request(self) -> None:
        transport = _CountingFailTransport()
        reranker = LlamaCppReranker(
            url="http://fake:8081", client=httpx.AsyncClient(transport=transport)
        )
        assert await reranker.rerank("q", []) == []
        assert transport.calls == 0

    @pytest.mark.asyncio
    async def test_request_body_shape(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

        reranker = LlamaCppReranker(
            url="http://fake:8081", model="Qwen3-Reranker-0.6B", client=_client(handler)
        )
        await reranker.rerank("my query", [RerankCandidate(id="m", text="doc text")])
        assert captured[0]["query"] == "my query"
        assert captured[0]["documents"] == ["doc text"]
        assert captured[0]["model"] == "Qwen3-Reranker-0.6B"

    @pytest.mark.asyncio
    async def test_unreachable_returns_empty_no_raise(self) -> None:
        transport = _CountingFailTransport()
        reranker = LlamaCppReranker(
            url="http://fake:8081", client=httpx.AsyncClient(transport=transport)
        )
        out = await reranker.rerank("q", [RerankCandidate(id="m", text="d")])
        assert out == []  # graceful, never raises

    @pytest.mark.asyncio
    async def test_non_2xx_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        reranker = LlamaCppReranker(url="http://fake:8081", client=_client(handler))
        assert await reranker.rerank("q", [RerankCandidate(id="m", text="d")]) == []

    @pytest.mark.asyncio
    async def test_malformed_body_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        reranker = LlamaCppReranker(url="http://fake:8081", client=_client(handler))
        assert await reranker.rerank("q", [RerankCandidate(id="m", text="d")]) == []

    @pytest.mark.asyncio
    async def test_down_cache_short_circuits_repeated_calls(self) -> None:
        # After one failure the server is presumed down; the next call must
        # short-circuit WITHOUT hitting the transport again (no per-query hang).
        transport = _CountingFailTransport()
        reranker = LlamaCppReranker(
            url="http://fake:8081",
            client=httpx.AsyncClient(transport=transport),
            down_cache_s=60.0,
        )
        cand = [RerankCandidate(id="m", text="d")]
        await reranker.rerank("q", cand)
        await reranker.rerank("q", cand)
        assert transport.calls == 1  # second call short-circuited by the cache

    @pytest.mark.asyncio
    async def test_down_cache_zero_retries_immediately(self) -> None:
        transport = _CountingFailTransport()
        reranker = LlamaCppReranker(
            url="http://fake:8081",
            client=httpx.AsyncClient(transport=transport),
            down_cache_s=0.0,
        )
        cand = [RerankCandidate(id="m", text="d")]
        await reranker.rerank("q", cand)
        await reranker.rerank("q", cand)
        assert transport.calls == 2  # no caching window → retried

    def test_from_settings_reads_knobs(self, tmp_path) -> None:
        settings = _settings(
            tmp_path,
            reranker_url="http://host:9000",
            reranker_model="Qwen3-Reranker-4B",
            reranker_timeout_s=3.5,
        )
        reranker = LlamaCppReranker.from_settings(settings)
        assert reranker.url == "http://host:9000"
        assert reranker.model == "Qwen3-Reranker-4B"
        assert reranker.timeout_s == 3.5


class TestParseRerankResponse:
    def test_returns_none_on_non_dict(self) -> None:
        assert _parse_rerank_response(["nope"], []) is None

    def test_returns_none_when_no_results_key(self) -> None:
        assert _parse_rerank_response({"data": []}, []) is None

    def test_skips_out_of_range_index(self) -> None:
        cands = [RerankCandidate(id="a", text="x")]
        parsed = _parse_rerank_response({"results": [{"index": 5, "relevance_score": 0.9}]}, cands)
        assert parsed is None  # nothing valid parsed → None


# ---------------------------------------------------------------------------
# maybe_rerank — the shared integration point (absolute floor + degradation)
# ---------------------------------------------------------------------------


class TestMaybeRerank:
    @pytest.mark.asyncio
    async def test_reorders_by_absolute_score(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        fused = _fused(("m1", 0.9, "alpha"), ("m2", 0.5, "beta"))
        reranker = _ScriptedReranker({"m1": 0.1, "m2": 0.8})
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m2", "m1"]  # reranker flipped order
        assert out[0]["relevance"] == pytest.approx(0.8)  # absolute score written back
        assert out[0]["reranked"] is True

    @pytest.mark.asyncio
    async def test_long_documents_truncated_before_rerank(self, tmp_path) -> None:
        from memgentic.retrieval.reranker import _RERANK_MAX_DOC_CHARS

        settings = _settings(tmp_path)
        long_content = "x" * (_RERANK_MAX_DOC_CHARS + 5000)
        fused = _fused(("m1", 0.9, long_content))
        reranker = _CapturingReranker()
        await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        # The cross-encoder must receive a bounded prefix, not the whole blob.
        assert len(reranker.seen_texts[0]) == _RERANK_MAX_DOC_CHARS

    @pytest.mark.asyncio
    async def test_min_score_drops_subthreshold(self, tmp_path) -> None:
        settings = _settings(tmp_path, reranker_min_score=0.5)
        fused = _fused(("m1", 0.9, "alpha"), ("m2", 0.5, "beta"))
        reranker = _ScriptedReranker({"m1": 0.9, "m2": 0.1})
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m1"]  # m2 (0.1 < 0.5) dropped

    @pytest.mark.asyncio
    async def test_tail_backfills_recall_after_floor_drop(self, tmp_path) -> None:
        # top_k=2 reranks the first two; m2 is floored out, but m3 from the tail
        # backfills so recall is not shrunk below what fusion already found.
        settings = _settings(tmp_path, reranker_top_k=2, reranker_min_score=0.5)
        fused = _fused(("m1", 0.9, "a"), ("m2", 0.8, "b"), ("m3", 0.7, "c"))
        reranker = _ScriptedReranker({"m1": 0.9, "m2": 0.1})
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m1", "m3"]

    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, tmp_path) -> None:
        settings = _settings(tmp_path, enable_reranker=False)
        fused = _fused(("m1", 0.9, "a"), ("m2", 0.5, "b"))
        reranker = _ScriptedReranker({"m1": 0.1, "m2": 0.8})
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m1", "m2"]  # fused order untouched
        assert reranker.calls == 0  # reranker never invoked

    @pytest.mark.asyncio
    async def test_no_reranker_is_noop(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        fused = _fused(("m1", 0.9, "a"), ("m2", 0.5, "b"))
        out = await maybe_rerank("q", fused, reranker=None, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m1", "m2"]

    @pytest.mark.asyncio
    async def test_server_down_falls_back_to_fused_order(self, tmp_path) -> None:
        # THE graceful-degradation guarantee: reranker reports down ([]),
        # recall still returns the full fused result set, in order, no error.
        settings = _settings(tmp_path)
        fused = _fused(("m1", 0.9, "a"), ("m2", 0.5, "b"), ("m3", 0.3, "c"))
        reranker = _DownReranker()
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m1", "m2", "m3"]
        assert reranker.calls == 1

    @pytest.mark.asyncio
    async def test_raising_reranker_falls_back_to_fused_order(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        fused = _fused(("m1", 0.9, "a"), ("m2", 0.5, "b"))
        out = await maybe_rerank(
            "q", fused, reranker=_RaisingReranker(), settings=settings, limit=10
        )
        assert [r["id"] for r in out] == ["m1", "m2"]  # survived the exception

    @pytest.mark.asyncio
    async def test_real_client_unreachable_graceful_fallback(self, tmp_path) -> None:
        # End-to-end: a real LlamaCppReranker pointed at an unreachable server,
        # driven through maybe_rerank, must preserve the fused order.
        settings = _settings(tmp_path)
        fused = _fused(("m1", 0.9, "a"), ("m2", 0.5, "b"))
        reranker = LlamaCppReranker(
            url="http://fake:8081", client=httpx.AsyncClient(transport=_CountingFailTransport())
        )
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=10)
        assert [r["id"] for r in out] == ["m1", "m2"]

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        out = await maybe_rerank(
            "q", [], reranker=_ScriptedReranker({}), settings=settings, limit=10
        )
        assert out == []

    @pytest.mark.asyncio
    async def test_truncates_to_limit(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        fused = _fused(*[(f"m{i}", 1.0 - i * 0.1, f"c{i}") for i in range(5)])
        reranker = _ScriptedReranker({f"m{i}": 1.0 - i * 0.1 for i in range(5)})
        out = await maybe_rerank("q", fused, reranker=reranker, settings=settings, limit=3)
        assert len(out) == 3
