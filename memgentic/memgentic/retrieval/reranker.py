"""Cross-encoder reranking for the retrieval cascade.

Reranking takes a query and a candidate list (typically the top-20 from the
hybrid retriever) and re-scores each candidate against the query with a
cross-encoder. Cross-encoders see the query and candidate together and attend
across both, so they catch fine-grained matches that bi-encoders (our embedder)
cannot. Crucially for Memgentic, the rerank score is an **absolute** relevance
signal in [0, 1] — unlike the relative min-max ``relevance`` produced by RRF
fusion — so it doubles as a "drop clearly-weak results" gate.

Serving: llama-server, NOT Ollama
---------------------------------
Ollama cannot serve rerankers (llama.cpp issue #16076 — no rank pooling). The
reranker therefore runs on llama.cpp's ``llama-server``::

    llama-server -m Qwen3-Reranker-0.6B-Q4_K_M.gguf \\
        --reranking --pooling rank --embedding --port 8081

That exposes a Jina/Cohere-style ``/v1/rerank`` endpoint. ``LlamaCppReranker``
is a thin async HTTP client over that endpoint: it POSTs ``{query, documents}``
and reads back per-document ``relevance_score`` values (the Qwen3-Reranker
yes/no logit ratio, already squashed to [0, 1] by the server).

Pin to the verified-working GGUFs
---------------------------------
Many community Qwen3-Reranker GGUF conversions silently drop the classifier
head and emit garbage scores (e.g. 4.5e-23). Use the **Voodisss** repos —
``Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp`` (default, light, ~396 MB Q4_K_M)
or the 4B variant for maximum quality. See ``docs/reranker-setup.md``.

Graceful degradation
---------------------
The reranker is OFF by default and entirely optional. When it is disabled, or
the llama-server is unreachable / errors / times out, recall MUST fall back to
the fused order unchanged — it can never break because a reranker is off or
down. ``LlamaCppReranker`` enforces a short timeout and caches a "down" state
for a short window so that one outage does not make every subsequent query pay
the full connect timeout. ``maybe_rerank`` is the single integration point both
search paths call, and it is a no-op on any failure.

This module defines the abstract ``Reranker`` interface, the ``MockReranker``
(tests), the ``LlamaCppReranker`` HTTP client, and the ``maybe_rerank`` helper.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx
import structlog

if TYPE_CHECKING:
    from memgentic.config import MemgenticSettings

logger = structlog.get_logger()

# Cross-encoders score one query+document pair in a single forward pass, so the
# whole pair must fit the server's batch / context window AND a long document
# costs proportionally more compute. An untruncated memory (or an oversized
# auto-captured blob) otherwise either makes llama-server reject the *entire*
# rerank request ("input too large to process") or blows the per-request
# timeout — either way dropping every candidate to a graceful no-op. A short
# prefix is enough for the cross-encoder to judge topical relevance and keeps
# reranking fast and robust; proper semantic chunking (scoring chunks, not
# whole memories) is the longer-term quality improvement.
_RERANK_MAX_DOC_CHARS = 1500


@dataclass
class RerankCandidate:
    """A candidate to rerank — the bare minimum: an ID and the text the
    cross-encoder will read.

    Carries an optional ``payload`` so callers (the harness, MCP tools,
    cascade orchestrator) can attach session_id, content_type, the full
    fused-result dict, etc., and get them back on the rerank result without a
    second lookup.
    """

    id: str
    text: str
    payload: dict[str, Any] | None = None


@dataclass
class RerankResult:
    """One reranked candidate with its cross-encoder score (absolute, [0, 1])."""

    id: str
    score: float
    payload: dict[str, Any] | None = None


class Reranker(Protocol):
    """Reranker interface. Implementations: ``LlamaCppReranker`` (llama-server
    HTTP), ``MockReranker`` (tests).
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Re-score ``candidates`` against ``query`` and return them sorted
        descending by score. ``top_k`` truncates the output; ``None`` returns
        all candidates.

        Implementations MUST NOT raise on a transport/server failure — they
        return ``[]`` so the caller can fall back to the un-reranked order.
        """
        ...


class MockReranker:
    """Test/dev reranker — deterministic scoring based on substring overlap.
    Lets harness/cascade tests run without a real llama-server.

    Score: number of unique whitespace-separated tokens shared between query
    and candidate text, normalised by log(1 + |query tokens|).
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        import math

        query_tokens = set(query.lower().split())
        norm = math.log(1 + len(query_tokens)) or 1.0
        scored = [
            RerankResult(
                id=c.id,
                score=len(query_tokens & set(c.text.lower().split())) / norm,
                payload=c.payload,
            )
            for c in candidates
        ]
        scored.sort(key=lambda r: r.score, reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored


class LlamaCppReranker:
    """Qwen3-Reranker served by ``llama-server`` over HTTP (``/v1/rerank``).

    Thin async HTTP client. POSTs the query + candidate documents to
    ``{url}/v1/rerank`` and reads back per-document relevance scores. The server
    applies the Qwen3-Reranker prompt template and rank pooling internally, so
    no prompt construction happens here — that avoids the silent-broken-GGUF
    trap entirely (a broken conversion fails loudly at server start, not here).

    Args:
        url: Base URL of the llama-server (default ``http://localhost:8081``).
        model: Informational model name sent in the request body. Most local
            servers ignore it and use whatever GGUF they loaded.
        timeout_s: Per-request timeout. Kept short (default 2 s) so a slow or
            wedged server cannot stall recall.
        down_cache_s: After a failure the server is treated as "down" for this
            many seconds; ``rerank`` short-circuits to ``[]`` during the window
            so every query does not re-pay the connect timeout.
        client: Optional injected ``httpx.AsyncClient`` (tests pass a
            ``MockTransport`` client). When omitted, one is created lazily and
            owned by this instance.

    Graceful degradation: any transport error, non-2xx status, timeout, or
    malformed body marks the server down, logs a single throttled warning, and
    returns ``[]`` — never raises.
    """

    def __init__(
        self,
        url: str = "http://localhost:8081",
        *,
        model: str | None = None,
        timeout_s: float = 2.0,
        down_cache_s: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model or None
        self.timeout_s = timeout_s
        self.down_cache_s = down_cache_s
        self._client = client
        self._owns_client = client is None
        # monotonic deadline until which the server is presumed unreachable
        self._down_until = 0.0

    @classmethod
    def from_settings(
        cls,
        settings: MemgenticSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> LlamaCppReranker:
        """Build a reranker from ``MemgenticSettings`` (reads the W5 knobs)."""
        return cls(
            url=settings.reranker_url,
            model=settings.reranker_model,
            timeout_s=settings.reranker_timeout_s,
            client=client,
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s, connect=min(self.timeout_s, 1.0))
            )
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close the owned HTTP client (no-op for an injected client)."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _mark_down(self) -> None:
        self._down_until = time.monotonic() + self.down_cache_s

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Score each candidate via llama-server; return sorted descending.

        Returns ``[]`` (never raises) when there are no candidates, the server
        is in its cached-down window, or the request fails for any reason.
        """
        if not candidates:
            return []

        # Short-circuit while the server is known-down to avoid per-query hangs.
        if time.monotonic() < self._down_until:
            return []

        documents = [c.text for c in candidates]
        payload: dict[str, Any] = {"query": query, "documents": documents}
        if self.model:
            payload["model"] = self.model
        if top_k is not None:
            payload["top_n"] = top_k

        try:
            client = self._get_client()
            resp = await client.post(f"{self.url}/v1/rerank", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # transport / status / decode — all non-fatal
            self._mark_down()
            logger.warning("reranker.request_failed", url=self.url, error=str(exc))
            return []

        results = _parse_rerank_response(data, list(candidates))
        if results is None:
            self._mark_down()
            logger.warning("reranker.bad_response", url=self.url)
            return []

        results.sort(key=lambda r: r.score, reverse=True)
        if top_k is not None:
            results = results[:top_k]
        return results


def _parse_rerank_response(
    data: Any, candidates: list[RerankCandidate]
) -> list[RerankResult] | None:
    """Parse a Jina/Cohere/llama-server ``/v1/rerank`` body into results.

    Expected shape::

        {"results": [{"index": 0, "relevance_score": 0.98}, ...]}

    Returns ``None`` when the body is unparseable (so the caller can mark the
    server down). ``index`` maps back to the submitted candidate order.
    """
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    out: list[RerankResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row["index"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_score = row.get("relevance_score", row.get("score"))
        if raw_score is None:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(candidates):
            cand = candidates[idx]
            out.append(RerankResult(id=cand.id, score=score, payload=cand.payload))
    return out or None


async def maybe_rerank(
    query: str,
    results: list[dict],
    *,
    reranker: Reranker | None,
    settings: MemgenticSettings | None,
    limit: int | None = None,
) -> list[dict]:
    """Optionally re-score fused search results with a cross-encoder reranker.

    This is the single integration point both search paths (hybrid + basic)
    call AFTER fusion / weighting / boosts. When reranking is enabled and the
    server is reachable it acts as an **absolute relevance gate**:

    - the top ``reranker_top_k`` fused candidates are re-scored,
    - they are REORDERED by the rerank score,
    - that score is written back as each result's ``relevance`` (now an
      absolute [0, 1] value, not the relative min-max from RRF),
    - any candidate whose rerank score is below ``reranker_min_score`` is
      DROPPED.

    Candidates beyond the rerank window keep their fused order and relevance,
    appended after the reranked head so recall to ``limit`` is never lost.

    Graceful no-op — returns ``results`` (truncated to ``limit``) unchanged
    when: reranking is disabled, no reranker is wired, there are no results, or
    the reranker reports a failure (``rerank`` returns ``[]`` / raises). Recall
    NEVER breaks because the reranker is off or the server is down.
    """

    def _truncated() -> list[dict]:
        return results[:limit] if limit is not None else results

    if settings is None or not settings.enable_reranker or reranker is None or not results:
        return _truncated()

    top_k = max(1, settings.reranker_top_k)
    head = results[:top_k]
    tail = results[top_k:]

    candidates = [
        RerankCandidate(
            id=str(r.get("id", "")),
            text=str((r.get("payload") or {}).get("content", ""))[:_RERANK_MAX_DOC_CHARS],
            payload=r,
        )
        for r in head
    ]

    try:
        reranked = await reranker.rerank(query, candidates)
    except Exception as exc:  # defensive — a conformant reranker returns []
        logger.warning("reranker.fallback_fused_order", error=str(exc))
        return _truncated()

    # Empty result ⇒ disabled/down/no-candidates ⇒ keep the fused order intact.
    if not reranked:
        return _truncated()

    min_score = settings.reranker_min_score
    out: list[dict] = []
    for rr in reranked:
        if rr.score < min_score:
            continue
        item: dict[str, Any] = dict(rr.payload) if isinstance(rr.payload, dict) else {"id": rr.id}
        item["relevance"] = round(float(rr.score), 4)
        item["rerank_score"] = round(float(rr.score), 4)
        item["reranked"] = True
        out.append(item)

    # Backfill from the un-reranked tail so dropping sub-threshold head items
    # (the absolute floor) never shrinks recall below what fusion already found.
    out.extend(tail)
    return out[:limit] if limit is not None else out
