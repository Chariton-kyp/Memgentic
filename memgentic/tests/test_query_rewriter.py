"""Tests for memgentic.processing.query_rewriter — mocked Ollama."""

from __future__ import annotations

import httpx
import pytest

from memgentic.processing.query_rewriter import QueryRewriter, QueryRewriterError


def _ok(text: str = "Maria said the SoW needs signing by Friday."):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": text})

    return handler


class TestHypothesise:
    async def test_returns_assistant_text(self):
        rw = QueryRewriter(model="gemma3:1b")
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(_ok("hello there")))
        try:
            out = await rw.hypothesise("what did Maria say")
            assert out == "hello there"
        finally:
            await rw.close()

    async def test_empty_query_returns_empty(self):
        rw = QueryRewriter()
        try:
            assert await rw.hypothesise("") == ""
            assert await rw.hypothesise("   ") == ""
        finally:
            await rw.close()

    async def test_http_error_falls_back_to_original(self):
        def fail(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "model not loaded"})

        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        try:
            out = await rw.hypothesise("a tricky query")
            assert out == "a tricky query"
        finally:
            await rw.close()

    async def test_empty_response_raises_then_falls_back(self):
        def empty(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"response": ""})

        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(empty))
        try:
            # _chat raises QueryRewriterError but hypothesise() catches and
            # returns the original query.
            out = await rw.hypothesise("orig")
            assert out == "orig"
        finally:
            await rw.close()


class TestExpand:
    async def test_concat_mode_default(self):
        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(_ok("the SoW is signed")))
        try:
            out = await rw.expand("did Maria sign the SoW")
            assert out == "did Maria sign the SoW\nthe SoW is signed"
        finally:
            await rw.close()

    async def test_hypothesis_only(self):
        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(_ok("Yes signed Friday")))
        try:
            out = await rw.expand("did Maria sign", mode="hypothesis")
            assert out == "Yes signed Friday"
        finally:
            await rw.close()

    async def test_query_mode_passthrough_no_call(self):
        # Use a transport that would explode if called.
        def bomb(_: httpx.Request) -> httpx.Response:
            raise AssertionError("LLM should not be called in 'query' mode")

        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(bomb))
        try:
            assert await rw.expand("hello", mode="query") == "hello"
        finally:
            await rw.close()

    async def test_unknown_mode_raises(self):
        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(_ok()))
        try:
            with pytest.raises(ValueError, match="unknown rewrite mode"):
                await rw.expand("hi", mode="bogus")
        finally:
            await rw.close()

    async def test_hypothesis_equals_query_skips_concat(self):
        # If the LLM literally echoes the query, concat would duplicate it;
        # the helper short-circuits and returns the original.
        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(_ok("hello world")))
        try:
            out = await rw.expand("hello world")
            assert out == "hello world"
        finally:
            await rw.close()


class TestExpandMany:
    async def test_concurrent_expansion(self):
        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(transport=httpx.MockTransport(_ok("hyp")))
        try:
            out = await rw.expand_many(["one", "two", "three"], mode="hypothesis")
            assert out == ["hyp", "hyp", "hyp"]
        finally:
            await rw.close()

    async def test_empty_list(self):
        rw = QueryRewriter()
        try:
            assert await rw.expand_many([]) == []
        finally:
            await rw.close()


class TestQueryRewriterErrorPath:
    async def test_chat_raises_on_empty_assistant_text(self):
        # Direct test of the internal _chat path — the empty branch is what
        # hypothesise() catches above; here we confirm it actually raises.
        rw = QueryRewriter()
        rw._client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"response": "   "})
            )
        )
        try:
            with pytest.raises(QueryRewriterError):
                await rw._chat("anything")
        finally:
            await rw.close()
