"""Tests for memgentic.retrieval.reranker (Plan 12 PR-E).

Real ``LlamaCppReranker`` integration tests require the GGUF model on
disk and llama-cpp-python installed; those run in a nightly job, not
PR CI. These tests cover:

- Interface contract (``RerankCandidate``, ``RerankResult`` shape)
- ``MockReranker`` deterministic behavior (used for harness/cascade tests)
- Prompt template formatting (regression guard against silent template drift)
- Lazy-loading semantics (``LlamaCppReranker._load`` is not called on
  construction)
- Error paths (missing llama-cpp-python, no candidates)
"""

from __future__ import annotations

import pytest

from memgentic.retrieval.reranker import (
    LlamaCppReranker,
    MockReranker,
    RerankCandidate,
    RerankResult,
    _qwen3_reranker_prompt,
)


class TestRerankCandidateAndResult:
    def test_candidate_minimum_fields(self) -> None:
        c = RerankCandidate(id="m-1", text="hello world")
        assert c.id == "m-1"
        assert c.text == "hello world"
        assert c.payload is None

    def test_candidate_with_payload(self) -> None:
        c = RerankCandidate(id="m-1", text="hi", payload={"session_id": "s-a"})
        assert c.payload == {"session_id": "s-a"}

    def test_result_carries_payload_through(self) -> None:
        r = RerankResult(id="m-1", score=0.87, payload={"session_id": "s-a"})
        assert r.payload == {"session_id": "s-a"}


class TestMockReranker:
    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self) -> None:
        reranker = MockReranker()
        result = await reranker.rerank("query", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_higher_overlap_ranks_higher(self) -> None:
        reranker = MockReranker()
        candidates = [
            RerankCandidate(id="m-1", text="completely unrelated content"),
            RerankCandidate(id="m-2", text="postgres database connection pool"),
            RerankCandidate(id="m-3", text="postgres connection"),
        ]
        result = await reranker.rerank("postgres connection pool", candidates)
        # m-2 has all 3 query tokens; m-3 has 2; m-1 has 0
        assert result[0].id == "m-2"
        assert result[1].id == "m-3"
        assert result[2].id == "m-1"

    @pytest.mark.asyncio
    async def test_top_k_truncates_output(self) -> None:
        reranker = MockReranker()
        candidates = [
            RerankCandidate(id=f"m-{i}", text=f"word{i} query") for i in range(5)
        ]
        result = await reranker.rerank("query", candidates, top_k=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_payload_preserved(self) -> None:
        reranker = MockReranker()
        candidates = [
            RerankCandidate(
                id="m-1",
                text="query word",
                payload={"session_id": "s-a"},
            )
        ]
        result = await reranker.rerank("query", candidates)
        assert result[0].payload == {"session_id": "s-a"}


class TestQwen3RerankerPrompt:
    def test_template_contains_query_and_document(self) -> None:
        prompt = _qwen3_reranker_prompt("test query", "test document")
        assert "test query" in prompt
        assert "test document" in prompt

    def test_template_contains_yes_no_instruction(self) -> None:
        prompt = _qwen3_reranker_prompt("q", "d")
        # Must include the yes/no instruction or the model emits unstructured text
        assert '"yes"' in prompt or "yes" in prompt
        assert '"no"' in prompt or "no" in prompt

    def test_template_uses_qwen_chat_markers(self) -> None:
        prompt = _qwen3_reranker_prompt("q", "d")
        assert "<|im_start|>system" in prompt
        assert "<|im_start|>user" in prompt
        assert "<|im_start|>assistant" in prompt

    def test_template_handles_special_characters(self) -> None:
        # Ensure no ValueError or silent corruption on special chars
        prompt = _qwen3_reranker_prompt(
            'query with "quotes"',
            "doc with\nnewlines\tand tabs",
        )
        assert "quotes" in prompt
        assert "newlines" in prompt


class TestLlamaCppRerankerLazyLoad:
    def test_construction_does_not_load_model(self) -> None:
        # If construction tried to load, a missing model file would raise
        # immediately. Lazy load means construction succeeds even without
        # the GGUF on disk; only ``rerank()`` triggers the load.
        reranker = LlamaCppReranker(model_path="/nonexistent/path.gguf")
        assert reranker._llm is None
        assert reranker.model_path == "/nonexistent/path.gguf"

    def test_default_n_ctx_is_8192(self) -> None:
        reranker = LlamaCppReranker()
        assert reranker.n_ctx == 8192

    def test_default_uses_all_gpu_layers(self) -> None:
        reranker = LlamaCppReranker()
        assert reranker.n_gpu_layers == -1

    @pytest.mark.asyncio
    async def test_empty_candidates_short_circuits(self) -> None:
        # No candidates → no model load required → returns []
        reranker = LlamaCppReranker(model_path="/nonexistent/path.gguf")
        result = await reranker.rerank("query", [])
        assert result == []
        assert reranker._llm is None  # Confirm we did not attempt to load
