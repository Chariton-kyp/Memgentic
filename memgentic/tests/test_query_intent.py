"""Tests for query intent detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from memgentic.processing.query import QueryIntent, parse_query_intent


class TestContentTypeDetection:
    def test_decision_query_detected(self):
        intent = parse_query_intent("what did we decide about Postgres?")
        assert "decision" in intent.implied_content_types

    def test_learning_query_detected(self):
        intent = parse_query_intent("what did we learn about FastAPI async routes")
        assert "learning" in intent.implied_content_types

    def test_preference_query_detected(self):
        intent = parse_query_intent("user preference for code style")
        assert "preference" in intent.implied_content_types

    def test_bug_fix_query_detected(self):
        intent = parse_query_intent("how did we fix the auth bug")
        assert "bug_fix" in intent.implied_content_types

    def test_plain_query_no_filter(self):
        intent = parse_query_intent("Qdrant collection settings")
        assert intent.implied_content_types == []

    def test_multiple_content_types_detected(self):
        intent = parse_query_intent("what did we decide and what did we learn")
        assert "decision" in intent.implied_content_types
        assert "learning" in intent.implied_content_types


class TestTimeFilters:
    def test_time_filter_today(self):
        intent = parse_query_intent("memories from today")
        assert intent.time_filter_since is not None
        delta = datetime.now(UTC) - intent.time_filter_since
        assert delta < timedelta(days=2)

    def test_time_filter_last_week(self):
        intent = parse_query_intent("anything from last week")
        assert intent.time_filter_since is not None
        delta = datetime.now(UTC) - intent.time_filter_since
        assert timedelta(days=13) < delta < timedelta(days=15)

    def test_time_filter_recently(self):
        intent = parse_query_intent("recently discussed Qdrant")
        assert intent.time_filter_since is not None

    def test_no_time_keyword_no_time_filter(self):
        intent = parse_query_intent("Qdrant performance")
        assert intent.time_filter_since is None


class TestCleanQuery:
    def test_clean_query_strips_filter_words(self):
        intent = parse_query_intent("what did we decide about Qdrant")
        assert "decide" not in intent.clean_query
        assert "qdrant" in intent.clean_query

    def test_clean_query_strips_time_words(self):
        intent = parse_query_intent("Qdrant config from last week")
        assert "last week" not in intent.clean_query
        assert "qdrant" in intent.clean_query

    def test_clean_query_falls_back_to_raw_when_empty(self):
        intent = parse_query_intent("decided")
        # all words stripped → falls back to raw
        assert intent.clean_query


class TestEdgeCases:
    def test_empty_query_safe(self):
        intent = parse_query_intent("")
        assert isinstance(intent, QueryIntent)
        assert intent.implied_content_types == []

    def test_unicode_query_safe(self):
        intent = parse_query_intent("Qdrant ελληνικά 你好")
        assert isinstance(intent, QueryIntent)
        assert "qdrant" in intent.clean_query

    def test_very_long_query(self):
        intent = parse_query_intent("Qdrant " * 200)
        assert isinstance(intent, QueryIntent)
