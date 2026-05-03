"""Embedding generation — Ollama (local) or OpenAI API.

Uses shared httpx connection pool, retry logic with exponential backoff,
and concurrent batch embedding with bounded parallelism.

Asymmetric encoding
-------------------
Modern instruction-tuned embedders (Qwen3-Embedding, EmbeddingGemma) are
trained with explicit query and document prefixes. Encoding a query the
same way as a document drops retrieval recall by 1-5% per the Qwen3
model card and similar amounts for Gemma. Use ``embed_query()`` for
search inputs and ``embed_document()`` for stored content. The legacy
``embed()`` / ``embed_batch()`` methods alias the document path so older
ingest call sites stay correct, but search code MUST migrate.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from memgentic.config import EmbeddingProvider, MemgenticSettings
from memgentic.exceptions import EmbeddingError
from memgentic.observability import record_histogram, trace_span

logger = structlog.get_logger()

# Retry on transient httpx errors: connection failures and timeouts.
_RETRY_DECORATOR = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    reraise=True,
)

# Default retrieval task description used by Qwen3-Embedding when the
# caller doesn't override. Kept generic so it works for memory recall,
# code search, and conversation transcript retrieval.
_QWEN3_DEFAULT_TASK = (
    "Given a search query, retrieve relevant memory passages that match the query"
)


def _model_family(model_name: str) -> str:
    """Detect the prefix dialect a given embedding model expects.

    Returns one of: ``qwen3``, ``gemma``, ``bge-m3``, ``bge``, ``unknown``.
    """
    name = model_name.lower()
    if "qwen3" in name or "qwen-3" in name:
        return "qwen3"
    if "embeddinggemma" in name or "embedding-gemma" in name or "embeddinggemma-300m" in name:
        return "gemma"
    if "bge-m3" in name or "bge_m3" in name:
        return "bge-m3"
    if "bge" in name:
        return "bge"
    return "unknown"


def format_query(model_name: str, text: str, task: str | None = None) -> str:
    """Apply the model-appropriate query prefix.

    - Qwen3-Embedding: ``Instruct: <task>\\nQuery: <text>``
    - EmbeddingGemma: ``task: search result | query: <text>``
    - bge / bge-m3 / unknown: no prefix (passthrough)
    """
    family = _model_family(model_name)
    if family == "qwen3":
        instruction = task or _QWEN3_DEFAULT_TASK
        return f"Instruct: {instruction}\nQuery: {text}"
    if family == "gemma":
        return f"task: search result | query: {text}"
    return text


def format_document(model_name: str, text: str, title: str | None = None) -> str:
    """Apply the model-appropriate document prefix.

    Only EmbeddingGemma documents an explicit document template
    (``title: <title|none> | text: <text>``). Qwen3 and BGE families
    leave documents unprefixed.
    """
    family = _model_family(model_name)
    if family == "gemma":
        return f"title: {title or 'none'} | text: {text}"
    return text


class Embedder:
    """Generate embeddings from text using Ollama or OpenAI.

    Default: Ollama with Qwen3-Embedding-0.6B (local, free, multilingual).

    Uses a shared ``httpx.AsyncClient`` with connection pooling for efficiency.
    Call :meth:`close` (or use as an async context manager) to release resources.
    """

    def __init__(self, settings: MemgenticSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._semaphore = asyncio.Semaphore(settings.embedding_batch_size)

    async def close(self) -> None:
        """Close the underlying HTTP client and release connection pool resources."""
        await self._client.aclose()

    # -- Public API -----------------------------------------------------------

    async def embed_query(self, text: str, task: str | None = None) -> list[float]:
        """Embed a search query with the model-appropriate query prefix.

        Use this for any text the user is searching with. ``task`` lets
        callers override the default retrieval instruction string for
        Qwen3-Embedding (e.g. code search vs prose recall).
        """
        formatted = format_query(self._settings.embedding_model, text, task=task)
        return await self.embed(formatted)

    async def embed_document(self, text: str, title: str | None = None) -> list[float]:
        """Embed a document/passage with the model-appropriate document prefix.

        Use this for content being stored in the vector index.
        ``title`` is consumed by EmbeddingGemma's document template;
        other model families ignore it.
        """
        formatted = format_document(self._settings.embedding_model, text, title=title)
        return await self.embed(formatted)

    async def embed_batch_documents(
        self, texts: list[str], titles: list[str | None] | None = None
    ) -> list[list[float]]:
        """Batch-embed documents with the model-appropriate prefix."""
        if not texts:
            return []
        if titles is not None and len(titles) != len(texts):
            raise EmbeddingError(
                f"titles length ({len(titles)}) must equal texts length ({len(texts)})"
            )
        model = self._settings.embedding_model
        if titles is None:
            formatted = [format_document(model, t) for t in texts]
        else:
            formatted = [
                format_document(model, t, title=ti)
                for t, ti in zip(texts, titles, strict=False)
            ]
        return await self.embed_batch(formatted)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text — raw, no prefix.

        Prefer :meth:`embed_query` or :meth:`embed_document` so the
        model-appropriate instruction prefix gets applied. ``embed``
        remains for backward compatibility with ingest call sites that
        already pass document content.
        """
        provider = self._settings.embedding_provider.value
        with trace_span("embedder.embed", provider=provider):
            _embed_start = time.perf_counter()
            try:
                if self._settings.embedding_provider == EmbeddingProvider.OLLAMA:
                    result = await self._embed_ollama(text)
                else:
                    result = await self._embed_openai(text)
                record_histogram(
                    "memgentic.embedder.duration_seconds",
                    time.perf_counter() - _embed_start,
                    provider=provider,
                )
                return result
            except httpx.ConnectError as exc:
                raise EmbeddingError(
                    f"Cannot connect to Ollama at {self._settings.ollama_url}. "
                    f"Is Ollama running? Start it with: ollama serve\n"
                    f"Or via Docker: docker compose up ollama -d\n"
                    f"Run 'memgentic doctor' to check your setup.\n"
                    f"Original error: {exc}"
                ) from exc
            except httpx.TimeoutException as exc:
                raise EmbeddingError(f"Embedding request timed out after retries: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise EmbeddingError(
                    f"Embedding API returned {exc.response.status_code}: {exc.response.text}"
                ) from exc
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError(f"Unexpected embedding failure: {exc}") from exc

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        OpenAI supports native batch embedding via a single API call.
        Ollama calls are dispatched concurrently (bounded by semaphore).
        """
        if not texts:
            return []

        t0 = time.perf_counter()

        try:
            if self._settings.embedding_provider == EmbeddingProvider.OPENAI:
                result = await self._embed_openai_batch(texts)
            else:
                result = await self._embed_ollama_batch(texts)
        except httpx.ConnectError as exc:
            raise EmbeddingError(
                f"Cannot connect to Ollama at {self._settings.ollama_url}. "
                f"Is Ollama running? Start it with: ollama serve\n"
                f"Or via Docker: docker compose up ollama -d\n"
                f"Run 'memgentic doctor' to check your setup.\n"
                f"Original error: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise EmbeddingError(f"Batch embedding timed out after retries: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(
                f"Embedding API returned {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Unexpected batch embedding failure: {exc}") from exc

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "embed_batch_complete",
            count=len(texts),
            elapsed_ms=round(elapsed_ms, 1),
            provider=self._settings.embedding_provider.value,
        )
        return result

    # -- Ollama ---------------------------------------------------------------

    @_RETRY_DECORATOR
    async def _embed_ollama(self, text: str) -> list[float]:
        """Generate embedding via Ollama API (with retry)."""
        response = await self._client.post(
            f"{self._settings.ollama_url}/api/embed",
            json={
                "model": self._settings.embedding_model,
                "input": text,
            },
        )
        response.raise_for_status()
        data = response.json()

        # Ollama returns {"embeddings": [[...]]} for /api/embed
        embedding: list[float] = data["embeddings"][0]

        # Truncate to configured dimensions (MRL support)
        if len(embedding) > self._settings.embedding_dimensions:
            embedding = embedding[: self._settings.embedding_dimensions]

        return embedding

    async def _embed_ollama_batch(self, texts: list[str]) -> list[list[float]]:
        """Concurrent Ollama embedding with bounded parallelism."""

        async def _bounded_embed(text: str) -> list[float]:
            async with self._semaphore:
                return await self._embed_ollama(text)

        return list(await asyncio.gather(*[_bounded_embed(t) for t in texts]))

    # -- OpenAI ---------------------------------------------------------------

    @_RETRY_DECORATOR
    async def _embed_openai(self, text: str) -> list[float]:
        """Generate embedding via OpenAI API (with retry)."""
        if not self._settings.openai_api_key:
            raise EmbeddingError("OpenAI API key required but not configured")

        response = await self._client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
            json={
                "model": self._settings.embedding_model,
                "input": text,
                "dimensions": self._settings.embedding_dimensions,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    @_RETRY_DECORATOR
    async def _embed_openai_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding via OpenAI API (with retry)."""
        if not self._settings.openai_api_key:
            raise EmbeddingError("OpenAI API key required but not configured")

        response = await self._client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
            json={
                "model": self._settings.embedding_model,
                "input": texts,
                "dimensions": self._settings.embedding_dimensions,
            },
        )
        response.raise_for_status()
        data = response.json()
        # Sort by index to ensure correct order
        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]
