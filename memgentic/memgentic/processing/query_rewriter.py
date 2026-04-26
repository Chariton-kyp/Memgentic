"""LLM-based query rewriting for retrieval (HyDE / query expansion).

Memory-recall queries from users are often abstract ("what did I tell
Maria about the contract") while the gold memory is concrete ("Maria
said the lawyer needs the SoW signed by Friday"). The dense embedder
sees these as semantically distant. A tiny LLM bridge — generating a
hypothetical answer ("hypothetical document") and embedding that
alongside the query — pulls the embedding centroid towards the kind of
text the gold memory actually contains.

This is the classic HyDE pattern (Hypothetical Document Embeddings,
Gao et al. 2022) trimmed for local-first use:

- Single Ollama call per query (no context, no chat history).
- Tiny default model (``gemma3:1b``, 999M params, ~1s on CPU) so the
  added latency stays within the production budget for live MCP recall.
- Returns either the hypothesis alone, the query + hypothesis joined,
  or a list of N variations (multi-query) — caller chooses.

Bilingual: the prompt explicitly instructs the model to answer in the
same language the query is in. Greek queries get Greek hypotheses,
English queries get English ones, mixed queries get mixed output.

Pure I/O — no shared state. Safe to call from async pipelines.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

logger = structlog.get_logger()

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma3:1b"
DEFAULT_TIMEOUT_SECONDS = 30.0

# HyDE prompt — terse, language-aware. Avoids long preamble that wastes
# tiny-model tokens. Instructions live in system to keep the user turn
# clean for the model to mirror in its answer.
_SYSTEM_PROMPT = (
    "You are a memory recall helper. Given a question, write ONE short "
    "factual sentence that would directly answer it if you knew the "
    "answer. Match the language of the question (English / Greek / etc). "
    "Do NOT explain, ask back, or add caveats. Output the sentence only."
)


class QueryRewriterError(RuntimeError):
    """Raised when the rewriter LLM call fails (network / timeout / parse)."""


class QueryRewriter:
    """Async HyDE-style query rewriter backed by an Ollama chat model.

    Holds a single shared :class:`httpx.AsyncClient`. Call :meth:`close`
    (or use as an async context manager) to release the connection pool.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._ollama_url = ollama_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "QueryRewriter":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def hypothesise(self, query: str) -> str:
        """Return a single hypothetical-answer sentence for the query.

        Empty / whitespace-only input returns "" without calling the LLM.
        On LLM error returns the original query so the caller never gets
        None back — degrading gracefully matches the bench harness's
        per-query try/except style.
        """
        if not query or not query.strip():
            return ""
        try:
            return await self._chat(query)
        except (httpx.HTTPError, KeyError, ValueError, QueryRewriterError) as exc:
            logger.warning("query_rewriter.failed", error=str(exc), query=query[:60])
            return query

    async def expand(self, query: str, *, mode: str = "concat") -> str:
        """Rewrite ``query`` for embedding.

        Args:
            query: Raw user query.
            mode: ``"concat"`` (default) returns ``"<query>\\n<hypothesis>"``
                so the embedder sees both signals. ``"hypothesis"`` replaces
                the query with the hypothesis (HyDE-pure). ``"query"`` is a
                no-op passthrough — useful for A/B harnesses that want to
                keep the same code path.
        """
        if mode == "query":
            return query
        hypothesis = await self.hypothesise(query)
        if not hypothesis or hypothesis.strip() == query.strip():
            return query
        if mode == "hypothesis":
            return hypothesis
        if mode == "concat":
            return f"{query}\n{hypothesis}"
        raise ValueError(f"unknown rewrite mode: {mode!r}")

    async def expand_many(self, queries: list[str], *, mode: str = "concat") -> list[str]:
        """Concurrent expansion of multiple queries (bounded parallelism)."""
        if not queries:
            return []
        sem = asyncio.Semaphore(4)

        async def _bounded(q: str) -> str:
            async with sem:
                return await self.expand(q, mode=mode)

        return list(await asyncio.gather(*[_bounded(q) for q in queries]))

    # -- Internal --------------------------------------------------------

    async def _chat(self, query: str) -> str:
        """Single Ollama /api/generate round-trip; returns assistant text.

        We use ``/api/generate`` (single prompt) over ``/api/chat`` because
        a few Gemma-family models don't honour the chat-template ``system``
        slot — they return empty messages even when the same prompt body
        sent through ``generate`` produces a real sentence. The downside is
        we lose the system-message separation; the prompt template below
        bakes the instruction into the body itself.
        """
        prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Question: {query}\n"
            f"Answer:"
        )
        response = await self._client.post(
            f"{self._ollama_url}/api/generate",
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # near-deterministic
                    "num_predict": 80,  # one sentence cap
                    "stop": ["\n\n", "Question:"],  # stop at next QA pair
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        text = (data.get("response") or "").strip()
        if not text:
            raise QueryRewriterError(f"empty response from {self._model}")
        return text
