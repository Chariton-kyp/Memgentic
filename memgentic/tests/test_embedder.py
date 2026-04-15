"""Tests for embedding generation (Embedder) — mocked HTTP layer."""

from __future__ import annotations

import httpx
import pytest

from memgentic.config import EmbeddingProvider, MemgenticSettings, StorageBackend
from memgentic.exceptions import EmbeddingError
from memgentic.processing.embedder import Embedder

DIMS = 768


def _fake_vector(seed: float = 0.1) -> list[float]:
    return [seed + i * 0.0001 for i in range(DIMS)]


# ---------------------------------------------------------------------------
# Helpers — httpx transport mocks
# ---------------------------------------------------------------------------


def _ollama_ok_handler(request: httpx.Request) -> httpx.Response:
    """Simulates a successful Ollama /api/embed response."""
    return httpx.Response(
        200,
        json={"embeddings": [_fake_vector()]},
    )


def _ollama_larger_vector_handler(request: httpx.Request) -> httpx.Response:
    """Returns a vector larger than DIMS to test MRL truncation."""
    big = [0.1 + i * 0.0001 for i in range(1024)]
    return httpx.Response(200, json={"embeddings": [big]})


class _FailThenSucceedTransport(httpx.AsyncBaseTransport):
    """Fails the first N calls with ConnectError, then succeeds."""

    def __init__(self, fail_count: int = 2):
        self._fail_count = fail_count
        self._calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._calls += 1
        if self._calls <= self._fail_count:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"embeddings": [_fake_vector()]})


class _AlwaysFailTransport(httpx.AsyncBaseTransport):
    """Always raises ConnectError."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("permanently unreachable")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(tmp_path) -> MemgenticSettings:
    return MemgenticSettings(
        data_dir=tmp_path / "data",
        storage_backend=StorageBackend.LOCAL,
        embedding_provider=EmbeddingProvider.OLLAMA,
        embedding_dimensions=DIMS,
        ollama_url="http://fake-ollama:11434",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmbed:
    async def test_embed_returns_correct_dimensions(self, tmp_path):
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        # Replace the internal client with a mock transport
        embedder._client = httpx.AsyncClient(transport=httpx.MockTransport(_ollama_ok_handler))
        try:
            result = await embedder.embed("Hello world")
            assert len(result) == DIMS
            assert all(isinstance(v, float) for v in result)
        finally:
            await embedder.close()

    async def test_embed_truncates_mrl(self, tmp_path):
        """If Ollama returns more dimensions than configured, truncate."""
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(
            transport=httpx.MockTransport(_ollama_larger_vector_handler)
        )
        try:
            result = await embedder.embed("MRL truncation test")
            assert len(result) == DIMS
        finally:
            await embedder.close()


class TestEmbedBatch:
    async def test_embed_batch_concurrent_ollama(self, tmp_path):
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=httpx.MockTransport(_ollama_ok_handler))
        try:
            texts = ["text one", "text two", "text three"]
            results = await embedder.embed_batch(texts)
            assert len(results) == 3
            assert all(len(v) == DIMS for v in results)
        finally:
            await embedder.close()

    async def test_embed_batch_empty(self, tmp_path):
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        try:
            results = await embedder.embed_batch([])
            assert results == []
        finally:
            await embedder.close()


class TestRetryBehaviour:
    async def test_retry_on_connect_error(self, tmp_path):
        """Fail twice, succeed on third attempt (within retry budget)."""
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        transport = _FailThenSucceedTransport(fail_count=2)
        embedder._client = httpx.AsyncClient(transport=transport)
        try:
            result = await embedder.embed("retry test")
            assert len(result) == DIMS
            assert transport._calls == 3  # 2 failures + 1 success
        finally:
            await embedder.close()

    async def test_permanent_failure_raises_embedding_error(self, tmp_path):
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=_AlwaysFailTransport())
        try:
            with pytest.raises(EmbeddingError, match="Cannot connect|failed"):
                await embedder.embed("doomed request")
        finally:
            await embedder.close()


class TestEmbedBatchErrors:
    async def test_embed_batch_connect_error_raises_embedding_error(self, tmp_path):
        """embed_batch wraps ConnectError in EmbeddingError."""
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=_AlwaysFailTransport())
        try:
            with pytest.raises(EmbeddingError, match="Cannot connect"):
                await embedder.embed_batch(["text one", "text two"])
        finally:
            await embedder.close()

    async def test_embed_batch_timeout_raises_embedding_error(self, tmp_path):
        """embed_batch wraps TimeoutException in EmbeddingError."""

        class _TimeoutTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.TimeoutException("read timed out")

        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=_TimeoutTransport())
        try:
            with pytest.raises(EmbeddingError, match="timed out"):
                await embedder.embed_batch(["a", "b"])
        finally:
            await embedder.close()

    async def test_embed_batch_http_status_error(self, tmp_path):
        """embed_batch wraps HTTPStatusError in EmbeddingError."""

        def _error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "model not found"})

        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=httpx.MockTransport(_error_handler))
        try:
            with pytest.raises(EmbeddingError, match="500"):
                await embedder.embed_batch(["a"])
        finally:
            await embedder.close()

    async def test_embed_batch_unexpected_error(self, tmp_path):
        """embed_batch wraps unexpected exceptions in EmbeddingError."""

        class _BadTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                raise RuntimeError("something unexpected")

        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=_BadTransport())
        try:
            with pytest.raises(EmbeddingError, match="Unexpected batch embedding"):
                await embedder.embed_batch(["x"])
        finally:
            await embedder.close()


class TestEmbedSingleErrors:
    async def test_embed_timeout_raises_embedding_error(self, tmp_path):
        """embed() wraps TimeoutException in EmbeddingError."""

        class _TimeoutTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.TimeoutException("timed out")

        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=_TimeoutTransport())
        try:
            with pytest.raises(EmbeddingError, match="timed out"):
                await embedder.embed("hello")
        finally:
            await embedder.close()

    async def test_embed_http_status_error(self, tmp_path):
        """embed() wraps HTTPStatusError in EmbeddingError."""

        def _error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "unavailable"})

        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=httpx.MockTransport(_error_handler))
        try:
            with pytest.raises(EmbeddingError, match="503"):
                await embedder.embed("test")
        finally:
            await embedder.close()

    async def test_embed_unexpected_error(self, tmp_path):
        """embed() wraps unexpected exceptions in EmbeddingError."""

        class _BadTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                raise ValueError("bad value")

        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=_BadTransport())
        try:
            with pytest.raises(EmbeddingError, match="Unexpected embedding failure"):
                await embedder.embed("test")
        finally:
            await embedder.close()


class TestOpenAIProvider:
    def _make_openai_settings(self, tmp_path) -> MemgenticSettings:
        return MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
            embedding_provider=EmbeddingProvider.OPENAI,
            embedding_dimensions=DIMS,
            openai_api_key="sk-test-key",
        )

    async def test_embed_openai_success(self, tmp_path):
        """OpenAI embed returns correct dimensions."""

        def _openai_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"data": [{"embedding": _fake_vector(), "index": 0}]},
            )

        settings = self._make_openai_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=httpx.MockTransport(_openai_handler))
        try:
            result = await embedder.embed("OpenAI test")
            assert len(result) == DIMS
        finally:
            await embedder.close()

    async def test_embed_openai_no_api_key(self, tmp_path):
        """OpenAI embed without API key raises EmbeddingError."""
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
            embedding_provider=EmbeddingProvider.OPENAI,
            embedding_dimensions=DIMS,
            openai_api_key=None,
        )
        embedder = Embedder(settings)
        try:
            with pytest.raises(EmbeddingError, match="OpenAI API key required"):
                await embedder.embed("no key")
        finally:
            await embedder.close()

    async def test_embed_batch_openai_success(self, tmp_path):
        """OpenAI batch embed returns correct results in order."""

        def _openai_batch_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"embedding": _fake_vector(0.2), "index": 1},
                        {"embedding": _fake_vector(0.1), "index": 0},
                    ]
                },
            )

        settings = self._make_openai_settings(tmp_path)
        embedder = Embedder(settings)
        embedder._client = httpx.AsyncClient(transport=httpx.MockTransport(_openai_batch_handler))
        try:
            results = await embedder.embed_batch(["text one", "text two"])
            assert len(results) == 2
            # Should be sorted by index — index 0 first
            assert results[0][0] == pytest.approx(0.1, abs=0.001)
            assert results[1][0] == pytest.approx(0.2, abs=0.001)
        finally:
            await embedder.close()

    async def test_embed_batch_openai_no_api_key(self, tmp_path):
        """OpenAI batch embed without API key raises EmbeddingError."""
        settings = MemgenticSettings(
            data_dir=tmp_path / "data",
            storage_backend=StorageBackend.LOCAL,
            embedding_provider=EmbeddingProvider.OPENAI,
            embedding_dimensions=DIMS,
            openai_api_key=None,
        )
        embedder = Embedder(settings)
        try:
            with pytest.raises(EmbeddingError, match="OpenAI API key required"):
                await embedder.embed_batch(["no key"])
        finally:
            await embedder.close()


class TestRetryBatchBehaviour:
    async def test_batch_retry_on_connect_error(self, tmp_path):
        """embed_batch retries on transient ConnectError (Ollama)."""
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        transport = _FailThenSucceedTransport(fail_count=2)
        embedder._client = httpx.AsyncClient(transport=transport)
        try:
            results = await embedder.embed_batch(["retry batch"])
            assert len(results) == 1
            assert len(results[0]) == DIMS
        finally:
            await embedder.close()


class TestClose:
    async def test_close_cleans_up_client(self, tmp_path):
        settings = _make_settings(tmp_path)
        embedder = Embedder(settings)
        assert not embedder._client.is_closed
        await embedder.close()
        assert embedder._client.is_closed
