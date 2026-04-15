"""Tests for intelligence heuristics overhaul — classifier, entity extraction, summarization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from memgentic.processing.intelligence import (
    IntelligenceState,
    _extract_named_entities,
    _heuristic_classify,
    summarize_node,
)
from memgentic.processing.utils import text_overlap

# ---------------------------------------------------------------------------
# 1. Classifier returns "decision"
# ---------------------------------------------------------------------------


def test_classify_decision():
    ct, conf = _heuristic_classify("We decided to use PostgreSQL for our database")
    assert ct == "decision"


# ---------------------------------------------------------------------------
# 2. Classifier returns "code_snippet" for triple backticks
# ---------------------------------------------------------------------------


def test_classify_code_snippet_backticks():
    ct, conf = _heuristic_classify("Here is the code:\n```python\nprint('hello')\n```")
    assert ct == "code_snippet"


# ---------------------------------------------------------------------------
# 3. Classifier returns "fact" for factual statement
# ---------------------------------------------------------------------------


def test_classify_fact():
    ct, conf = _heuristic_classify("Python 3.12 supports the new type syntax")
    assert ct == "fact"


# ---------------------------------------------------------------------------
# 4. Multi-keyword boost: 2+ decision keywords gets confidence 0.85
# ---------------------------------------------------------------------------


def test_classify_multi_keyword_high_confidence():
    ct, conf = _heuristic_classify(
        "We decided to go with React. The decision was finalized yesterday."
    )
    assert ct == "decision"
    assert conf == 0.85


# ---------------------------------------------------------------------------
# 5. Classifier picks highest-scoring type, not first match
# ---------------------------------------------------------------------------


def test_classify_picks_highest_score():
    # Text with 1 decision keyword but 3+ code keywords
    text = "We decided to write: def main(): import os; return None"
    ct, conf = _heuristic_classify(text)
    assert ct == "code_snippet", f"Expected code_snippet but got {ct}"


# ---------------------------------------------------------------------------
# 6. Entity extraction finds URLs
# ---------------------------------------------------------------------------


def test_entity_extraction_finds_urls():
    text = "Check out https://docs.python.org/3/ for details"
    entities = _extract_named_entities(text)
    assert any("docs.python.org" in e for e in entities)


# ---------------------------------------------------------------------------
# 7. Entity extraction finds CamelCase identifiers
# ---------------------------------------------------------------------------


def test_entity_extraction_finds_camelcase():
    text = "We used FastApi and LangChain for our project"
    # Note: FastApi has CamelCase pattern [A-Z][a-z]+[A-Z][a-z]+
    entities = _extract_named_entities(text)
    camel_found = [e for e in entities if e in ("FastApi", "LangChain")]
    assert len(camel_found) >= 1, f"Expected CamelCase entities, got {entities}"


# ---------------------------------------------------------------------------
# 8. Entity extraction returns non-empty for typical tech conversation
# ---------------------------------------------------------------------------


def test_entity_extraction_nonempty_for_tech():
    text = (
        "We deployed the FastAPI service to https://api.example.com and "
        "configured the NextJs frontend with TailWind CSS. The config is in "
        "src/config.py and tests/test_main.py."
    )
    entities = _extract_named_entities(text)
    assert len(entities) > 0, "Expected non-empty entity list for tech conversation"


# ---------------------------------------------------------------------------
# 9. Summarization produces "Key points:" format for multi-sentence input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_extractive_format():
    llm = MagicMock()
    llm.available = False
    llm.generate_structured = AsyncMock(return_value=None)

    chunks = [
        {
            "content": (
                "FastAPI is great for building APIs. "
                "It provides automatic documentation. "
                "The async support is excellent for performance. "
                "We should definitely use it for the project."
            ),
            "content_type": "fact",
        },
        {
            "content": (
                "Docker containers simplify deployment significantly. "
                "They provide isolation between services. "
                "Kubernetes can orchestrate multiple containers easily."
            ),
            "content_type": "fact",
        },
    ]

    state: IntelligenceState = {
        "chunks": chunks,
        "classified_chunks": chunks,
        "llm_client": llm,
        "errors": [],
        "all_topics": ["fastapi", "docker"],
    }

    result = await summarize_node(state)
    assert result["summary"].startswith("Key points:")


# ---------------------------------------------------------------------------
# 10. text_overlap utility works correctly (imported from utils)
# ---------------------------------------------------------------------------


def test_text_overlap_identical():
    assert text_overlap("hello world", "hello world") == 1.0


def test_text_overlap_disjoint():
    assert text_overlap("hello world", "foo bar") == 0.0


def test_text_overlap_partial():
    score = text_overlap("the cat sat", "the dog sat")
    assert 0.0 < score < 1.0


def test_text_overlap_empty():
    assert text_overlap("", "hello") == 0.0
    assert text_overlap("hello", "") == 0.0


# ---------------------------------------------------------------------------
# 11. Entity extraction finds @-scoped packages
# ---------------------------------------------------------------------------


def test_entity_extraction_finds_scoped_packages():
    text = "We installed @tanstack/react-query and @anthropic-ai/sdk for the project"
    entities = _extract_named_entities(text)
    assert any("@tanstack/react-query" in e for e in entities)
    assert any("@anthropic-ai/sdk" in e for e in entities)


# ---------------------------------------------------------------------------
# 12. Entity extraction finds version strings
# ---------------------------------------------------------------------------


def test_entity_extraction_finds_version_strings():
    text = "We upgraded to Python 3.12 and also use v2.0.1 of the library"
    entities = _extract_named_entities(text)
    assert any("Python 3.12" in e for e in entities)
    assert any("v2.0.1" in e for e in entities)


# ---------------------------------------------------------------------------
# 13. Heuristic summarization produces "Key points:" even for short inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_short_input_key_points_format():
    """When sentences < 2, fallback should still produce 'Key points:' format."""
    llm = MagicMock()
    llm.available = False
    llm.generate_structured = AsyncMock(return_value=None)

    # Use very short content that won't produce 2+ sentences with 5+ words each
    chunks = [
        {"content": "Use React.", "content_type": "fact"},
        {"content": "Try Docker.", "content_type": "fact"},
        {"content": "Learn Python.", "content_type": "fact"},
    ]

    state: IntelligenceState = {
        "chunks": chunks,
        "classified_chunks": chunks,
        "llm_client": llm,
        "errors": [],
        "all_topics": [],
    }

    result = await summarize_node(state)
    assert result["summary"].startswith("Key points:")
