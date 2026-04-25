"""Cross-encoder reranking for the Plan 12 cascade (PR-E + Phase 1).

Reranking takes a query and a candidate list (typically top-20 from the
hybrid retriever) and re-scores each candidate against the query with a
cross-encoder. Cross-encoders see the query and candidate together and
attend across both, so they catch fine-grained matches that bi-encoders
(our embedder) cannot.

Why Qwen3-Reranker-0.6B specifically:
- Same family as our Qwen3-Embedding-0.6B, so vocabulary, tokenizer,
  language coverage, and instruction format are aligned.
- Apache 2.0, 1.2 GB BF16 (370 MB at Q4_K_M).
- MTEB-R 65.80 — beats BGE-reranker-v2-m3 (~9 nDCG points) at the same
  size class.
- Targets ~40-80 ms for 20 candidates × ~512 tokens on consumer GPU.

Why pin to ggml-org / Voodisss GGUFs:
Many community Qwen3-Reranker GGUF conversions silently drop the
classifier head tensors and produce score values like 4.5e-23 instead of
real relevance scores. Use ``ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`` or
``Voodisss/Qwen3-Reranker-0.6B-GGUF-llama_cpp`` only.

Provider strategy:
- Default: llama-cpp-python loading the GGUF (fastest local path, runs
  on CPU + GPU, integrates with existing Memgentic stack)
- Fallback: HuggingFace ``transformers`` + ``sentence-transformers``
  (heavier but more portable for environments without llama-cpp)
- Production may swap in Ollama once Ollama gains native reranker
  support (roadmap)

This module defines the abstract ``Reranker`` interface plus a
``LlamaCppReranker`` implementation. The harness and Phase 1 cascade
both consume the interface, so swapping implementations later is one
constructor call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

logger = structlog.get_logger()


@dataclass
class RerankCandidate:
    """A candidate to rerank — the bare minimum: an ID and the text the
    cross-encoder will read.

    Carries an optional ``payload`` so callers (the harness, MCP tools,
    cascade orchestrator) can attach session_id, content_type, etc., and
    get them back on the rerank result without a second lookup.
    """

    id: str
    text: str
    payload: dict[str, Any] | None = None


@dataclass
class RerankResult:
    """One reranked candidate with its cross-encoder score."""

    id: str
    score: float
    payload: dict[str, Any] | None = None


class Reranker(Protocol):
    """Reranker interface. Implementations: ``LlamaCppReranker``,
    ``HuggingFaceReranker`` (future), ``MockReranker`` (tests).
    """

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Re-score ``candidates`` against ``query`` and return them
        sorted descending by score. ``top_k`` truncates the output;
        ``None`` returns all candidates.
        """
        ...


class MockReranker:
    """Test/dev reranker — deterministic scoring based on substring
    overlap. Lets harness/cascade tests run without loading a real model.

    Score: number of unique whitespace-separated tokens shared between
    query and candidate text, normalised by log(1 + |query tokens|).
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
    """Qwen3-Reranker-0.6B via llama-cpp-python.

    Loads the GGUF on first ``rerank`` call (lazy) so importing the
    module does not pay model-load cost. Subsequent calls reuse the
    loaded model.

    Args:
        model_path: Path to a Qwen3-Reranker GGUF file from one of the
            verified-working sources. Default reads ``MEMGENTIC_RERANKER_GGUF``
            env var if set, else falls back to a sensible HuggingFace
            cache path.
        n_ctx: Context window the model is loaded with. 8192 is plenty
            for one query + top-20 candidates × ~512 tokens each.
        n_gpu_layers: Number of layers offloaded to GPU. -1 = all layers
            (fastest if you have VRAM); 0 = pure CPU.
        verbose: Pass-through to llama-cpp.

    Notes:
        - Uses ``Llama.create_chat_completion`` with the Qwen3-Reranker
          prompt template (chat-completion style), parses the
          yes/no logit ratio, returns it as the score.
        - The Qwen3-Reranker prompt template is documented in the model
          card; we follow it exactly to avoid the silent-broken-conversion
          trap.
    """

    def __init__(
        self,
        model_path: str | None = None,
        *,
        n_ctx: int = 8192,
        n_gpu_layers: int = -1,
        verbose: bool = False,
    ) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._llm: Any = None  # Llama instance, lazy-loaded

    def _load(self) -> None:
        if self._llm is not None:
            return
        try:
            from llama_cpp import Llama  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "LlamaCppReranker requires the llama-cpp-python optional "
                "dependency. Install with: pip install llama-cpp-python "
                "(or `uv pip install llama-cpp-python`)."
            ) from exc

        if self.model_path is None:
            import os

            self.model_path = os.environ.get(
                "MEMGENTIC_RERANKER_GGUF",
                str(_default_reranker_path()),
            )

        logger.info(
            "reranker.loading",
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
        )
        self._llm = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=self.verbose,
            logits_all=True,  # Required for token-probability extraction
        )
        logger.info("reranker.loaded")

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Score each candidate against query, return sorted descending."""
        if not candidates:
            return []
        self._load()

        scored: list[RerankResult] = []
        for candidate in candidates:
            score = self._score_one(query, candidate.text)
            scored.append(
                RerankResult(id=candidate.id, score=score, payload=candidate.payload)
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored

    def _score_one(self, query: str, candidate_text: str) -> float:
        """Run one cross-encoder pass; return the relevance probability."""
        prompt = _qwen3_reranker_prompt(query, candidate_text)
        # Qwen3-Reranker outputs a single token: "yes" (relevant) or "no".
        # Extract the logit for "yes" vs "no" and convert to probability.
        out = self._llm(
            prompt,
            max_tokens=1,
            temperature=0.0,
            logprobs=2,  # Top-2 token logprobs
            echo=False,
        )
        # llama-cpp returns logprobs of completion tokens. Find "yes" prob;
        # fall back to 0 if model emitted something unexpected.
        try:
            top_logprobs = out["choices"][0]["logprobs"]["top_logprobs"][0]
            yes_logprob = top_logprobs.get("yes", top_logprobs.get(" yes", -1e9))
            import math

            return math.exp(yes_logprob)
        except (KeyError, IndexError, TypeError):
            return 0.0


def _default_reranker_path() -> str:
    """Best-guess default path for a downloaded Qwen3-Reranker GGUF.

    Looks at the standard HuggingFace cache layout. Returns the expected
    path even if the file isn't downloaded yet — let the real load call
    raise the FileNotFoundError so the user gets a clear actionable error.
    """
    from pathlib import Path

    hf_home = Path.home() / ".cache" / "huggingface" / "hub"
    return str(
        hf_home
        / "models--ggml-org--Qwen3-Reranker-0.6B-Q8_0-GGUF"
        / "snapshots"
        / "main"
        / "qwen3-reranker-0.6b-q8_0.gguf"
    )


def _qwen3_reranker_prompt(query: str, document: str) -> str:
    """Qwen3-Reranker chat-completion prompt template per official model card.

    The reranker is trained to answer 'yes' or 'no' to whether ``document``
    is relevant to ``query``. We extract the 'yes' token probability as
    the relevance score.
    """
    instruction = (
        "Given a web search query, retrieve relevant passages that answer the query."
    )
    return (
        "<|im_start|>system\n"
        "Judge whether the Document meets the requirements based on the Query "
        'and the Instruction provided. Note that the answer can only be "yes" or "no".\n'
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"<Instruct>: {instruction}\n"
        f"<Query>: {query}\n"
        f"<Document>: {document}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
