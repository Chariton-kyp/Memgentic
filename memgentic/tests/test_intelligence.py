"""Tests for the LangGraph intelligence pipeline."""

from unittest.mock import AsyncMock, MagicMock

from memgentic.processing.intelligence import (
    ClassificationResult,
    ExtractionResult,
    IntelligenceState,
    SummaryResult,
    build_intelligence_graph,
    classify_node,
    extract_node,
    summarize_node,
)


def _mock_llm(available: bool = False):
    """Create a mock LLMClient."""
    llm = MagicMock()
    llm.available = available
    llm.generate = AsyncMock(return_value="")
    llm.generate_structured = AsyncMock(return_value=None)
    return llm


def _sample_chunks():
    return [
        {
            "content": "We decided to use FastAPI for the REST API because it's fast and async.",
            "content_type": "raw_exchange",
            "confidence": 0.5,
            "topics": ["fastapi"],
        },
        {
            "content": "Here's the code: def hello(): return 'world'",
            "content_type": "raw_exchange",
            "confidence": 0.5,
            "topics": ["python"],
        },
    ]


# --- classify_node ---


async def test_classify_heuristic_mode():
    """Without LLM, classify uses heuristics."""
    llm = _mock_llm(available=False)
    state: IntelligenceState = {
        "chunks": _sample_chunks(),
        "llm_client": llm,
        "errors": [],
    }
    result = await classify_node(state)
    classified = result["classified_chunks"]
    assert len(classified) == 2
    # "decided" keyword should trigger "decision" classification
    assert classified[0]["content_type"] == "decision"
    # "def " keyword should trigger "code_snippet"
    assert classified[1]["content_type"] == "code_snippet"


async def test_classify_with_llm():
    """With LLM, classify uses structured output."""
    llm = _mock_llm(available=True)
    llm.generate_structured.return_value = ClassificationResult(
        content_type="decision", confidence=0.95
    )
    state: IntelligenceState = {
        "chunks": [
            {
                "content": "Let's go with React",
                "content_type": "raw_exchange",
                "confidence": 0.5,
                "topics": [],
            }
        ],
        "llm_client": llm,
        "errors": [],
    }
    result = await classify_node(state)
    assert result["classified_chunks"][0]["content_type"] == "decision"
    assert result["classified_chunks"][0]["confidence"] == 0.95


# --- extract_node ---


async def test_extract_heuristic_mode():
    """Without LLM, extract uses keyword matching."""
    llm = _mock_llm(available=False)
    state: IntelligenceState = {
        "chunks": _sample_chunks(),
        "classified_chunks": _sample_chunks(),
        "llm_client": llm,
        "errors": [],
    }
    result = await extract_node(state)
    assert "fastapi" in result["all_topics"]


async def test_extract_with_llm():
    """With LLM, extract uses structured output and merges with heuristics."""
    llm = _mock_llm(available=True)
    llm.generate_structured.return_value = ExtractionResult(
        topics=["architecture", "REST"], entities=["FastAPI"]
    )
    state: IntelligenceState = {
        "chunks": _sample_chunks(),
        "classified_chunks": _sample_chunks(),
        "llm_client": llm,
        "errors": [],
    }
    result = await extract_node(state)
    assert "architecture" in result["all_topics"]
    assert "FastAPI" in result["all_entities"]
    # Heuristic topics should be merged in
    assert "fastapi" in result["all_topics"]


# --- summarize_node ---


async def test_summarize_heuristic_mode():
    """Without LLM, summarize uses extractive summarization."""
    llm = _mock_llm(available=False)
    state: IntelligenceState = {
        "chunks": _sample_chunks(),
        "classified_chunks": _sample_chunks(),
        "llm_client": llm,
        "errors": [],
    }
    result = await summarize_node(state)
    # Extractive summarization produces "Key points:" or falls back to preview
    assert result["summary"]  # Non-empty summary


async def test_summarize_with_llm():
    """With LLM, summarize uses structured output."""
    llm = _mock_llm(available=True)
    llm.generate_structured.return_value = SummaryResult(
        summary="Decided to use FastAPI for the REST API. Wrote a hello world function."
    )
    state: IntelligenceState = {
        "chunks": _sample_chunks(),
        "classified_chunks": _sample_chunks(),
        "llm_client": llm,
        "errors": [],
    }
    result = await summarize_node(state)
    assert "FastAPI" in result["summary"]


async def test_summarize_single_chunk():
    """Single chunk returns truncated content."""
    llm = _mock_llm(available=False)
    state: IntelligenceState = {
        "chunks": [{"content": "Short note", "content_type": "fact"}],
        "classified_chunks": [{"content": "Short note", "content_type": "fact"}],
        "llm_client": llm,
        "errors": [],
    }
    result = await summarize_node(state)
    assert result["summary"] == "Short note"


# --- Full pipeline ---


async def test_build_intelligence_graph_compiles():
    """The LangGraph pipeline compiles without errors."""
    compiled = build_intelligence_graph()
    assert compiled is not None


async def test_full_pipeline_heuristic_mode():
    """Full pipeline run without LLM produces valid outputs."""
    compiled = build_intelligence_graph()
    llm = _mock_llm(available=False)

    result = await compiled.ainvoke(
        {
            "chunks": _sample_chunks(),
            "llm_client": llm,
            "errors": [],
        }
    )

    assert "classified_chunks" in result
    assert "all_topics" in result
    assert "summary" in result
    assert len(result["classified_chunks"]) == 2
    assert isinstance(result["all_topics"], list)
    assert isinstance(result["summary"], str)
