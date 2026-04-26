"""Tests for memgentic.processing.query_features bilingual extractors."""

from __future__ import annotations

import datetime as _dt

from memgentic.processing.query_features import QueryFeatures, extract_features


_NOW = _dt.datetime(2026, 4, 26, 12, 0, 0, tzinfo=_dt.UTC)


class TestTemporal:
    def test_two_months_ago_english(self):
        f = extract_features("what did Maria say two months ago", now=_NOW)
        assert f.temporal_reference_days == 60.0

    def test_digit_amount(self):
        f = extract_features("the bug we filed 3 weeks ago", now=_NOW)
        assert f.temporal_reference_days == 21.0

    def test_greek_priori(self):
        f = extract_features("τι είπε ο Γιάννης πριν δύο μήνες", now=_NOW)
        assert f.temporal_reference_days == 60.0

    def test_implicit_anchor_yesterday(self):
        f = extract_features("the meeting yesterday", now=_NOW)
        assert f.temporal_reference_days == 1.0

    def test_implicit_anchor_greek_xthes(self):
        f = extract_features("τι κάναμε χθες", now=_NOW)
        assert f.temporal_reference_days == 1.0

    def test_absolute_year_falls_back(self):
        # No "ago" phrase — fall back to year-distance.
        f = extract_features("the launch in 2024", now=_NOW)
        assert f.absolute_year == 2024
        assert f.temporal_reference_days == (2026 - 2024) * 365.0

    def test_absolute_year_does_not_override_relative(self):
        # When a relative phrase is present, prefer it; the year still
        # surfaces in the absolute_year field for downstream use.
        f = extract_features("the contract signed last week mentioned 2024", now=_NOW)
        assert f.temporal_reference_days == 7.0
        assert f.absolute_year == 2024

    def test_no_temporal_reference(self):
        f = extract_features("what is RAG", now=_NOW)
        assert f.temporal_reference_days is None


class TestQuotedPhrases:
    def test_double_quotes(self):
        f = extract_features('find note with "circuit breaker pattern"')
        assert f.quoted_phrases == ("circuit breaker pattern",)

    def test_single_quotes(self):
        f = extract_features("the function 'load_user' was buggy")
        assert f.quoted_phrases == ("load_user",)

    def test_greek_guillemets(self):
        f = extract_features("βρες το κείμενο «μνημονιακή πολιτική»")
        assert f.quoted_phrases == ("μνημονιακή πολιτική",)

    def test_curly_quotes_normalised(self):
        f = extract_features("look for “memgentic core”")
        assert f.quoted_phrases == ("memgentic core",)

    def test_multiple_quoted_phrases(self):
        f = extract_features("'foo' and \"bar\" both")
        assert "foo" in f.quoted_phrases
        assert "bar" in f.quoted_phrases

    def test_short_quote_ignored(self):
        # Single-character quote (apostrophes in contractions) drops out.
        f = extract_features("don't worry about it")
        assert f.quoted_phrases == ()


class TestProperNouns:
    def test_simple_name(self):
        f = extract_features("what did Maria say about the contract")
        assert "Maria" in f.proper_nouns

    def test_skips_question_initial(self):
        # "What" at position 0 is a question word, not a proper noun.
        f = extract_features("What did Alex propose")
        assert "What" not in f.proper_nouns
        assert "Alex" in f.proper_nouns

    def test_dedupes_repeated_names(self):
        f = extract_features("Memgentic supports Memgentic recall")
        assert f.proper_nouns == ("Memgentic",)

    def test_greek_proper_noun(self):
        f = extract_features("Τι είπε ο Γιάννης χθες")
        # Greek capitalised name still extracts.
        assert "Γιάννης" in f.proper_nouns
        # "Τι" sentence-initial Greek question word is excluded.
        assert "Τι" not in f.proper_nouns

    def test_quoted_name_not_double_counted(self):
        # If a name appears inside a quoted span, only the quote captures it
        # (boost code handles them differently, so we don't want both firing).
        f = extract_features("find 'Maria meeting notes'")
        assert "Maria meeting notes" in f.quoted_phrases
        assert "Maria" not in f.proper_nouns

    def test_no_proper_nouns_in_pure_lowercase_query(self):
        f = extract_features("how does rag work")
        assert f.proper_nouns == ()


class TestEdgeCases:
    def test_empty_query(self):
        f = extract_features("")
        assert f == QueryFeatures()

    def test_query_with_only_punctuation(self):
        f = extract_features("???")
        assert f.temporal_reference_days is None
        assert f.proper_nouns == ()
        assert f.quoted_phrases == ()
