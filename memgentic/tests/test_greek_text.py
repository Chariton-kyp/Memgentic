"""Tests for Greek text normalization helpers."""

from __future__ import annotations

from memgentic.processing.greek_text import (
    GREEK_STOPWORDS,
    normalize_greek_text,
    tokenize_for_search,
)


class TestNormalizeGreekText:
    def test_lowercases(self) -> None:
        assert normalize_greek_text("HELLO") == "hello"

    def test_strips_lowercase_tonos(self) -> None:
        assert normalize_greek_text("μουσακάς") == "μουσακας"

    def test_strips_uppercase_tonos(self) -> None:
        # "ΚΏΣΤΑ" (Kostas with capital tonos) → "κωστα"
        assert normalize_greek_text("ΚΏΣΤΑ") == "κωστα"

    def test_strips_dialytika(self) -> None:
        assert normalize_greek_text("προϊόν") == "προιον"
        assert normalize_greek_text("ΰ") == "υ"

    def test_mixed_accents_and_punctuation(self) -> None:
        assert normalize_greek_text("Δικηγορικό Γραφείο") == "δικηγορικο γραφειο"

    def test_handles_combining_marks_via_nfd(self) -> None:
        # "ή" composed: U+03AE; same character via NFD decomposition is η + ́
        composed = "ή"
        decomposed = "ή"
        # Both must normalise to plain "η"
        assert normalize_greek_text(composed) == "η"
        assert normalize_greek_text(decomposed) == "η"

    def test_passes_english_through_lowercased(self) -> None:
        assert normalize_greek_text("Hello World 2026") == "hello world 2026"

    def test_empty_input(self) -> None:
        assert normalize_greek_text("") == ""

    def test_none_safe_for_falsy_strings(self) -> None:
        # We don't accept None but whitespace-only stays whitespace-only,
        # and the empty-input shortcut is exercised by the empty-string test.
        assert normalize_greek_text("   ") == "   "


class TestTokenizeForSearch:
    def test_basic_split(self) -> None:
        assert tokenize_for_search("Δικηγορικό Γραφείο") == ["δικηγορικο", "γραφειο"]

    def test_strips_short_tokens(self) -> None:
        # Single-char tokens dropped by default min_token_length=2
        assert tokenize_for_search("a bc def") == ["bc", "def"]

    def test_min_token_length_override(self) -> None:
        assert tokenize_for_search("a bc def", min_token_length=3) == ["def"]

    def test_keeps_stopwords_by_default(self) -> None:
        # Default remove_stopwords=False so embedder pipelines get all tokens
        result = tokenize_for_search("το παιδί")
        assert "το" in result
        assert "παιδι" in result

    def test_drops_stopwords_when_enabled(self) -> None:
        result = tokenize_for_search("το παιδί τρέχει στον κήπο", remove_stopwords=True)
        # "το" + "στον" are stopwords and dropped
        assert "το" not in result
        assert "στον" not in result
        assert "παιδι" in result
        assert "τρεχει" in result
        assert "κηπο" in result

    def test_punctuation_split(self) -> None:
        # Email-style punctuation should be a separator
        assert tokenize_for_search("user@example.com") == ["user", "example", "com"]

    def test_empty_input(self) -> None:
        assert tokenize_for_search("") == []

    def test_unicode_word_boundary(self) -> None:
        # Greek+Latin mix splits cleanly
        assert tokenize_for_search("RAG για ελληνικά") == ["rag", "για", "ελληνικα"]


class TestStopwordSet:
    def test_includes_common_greek_articles(self) -> None:
        for word in ("ο", "η", "το", "οι", "τα"):
            assert word in GREEK_STOPWORDS

    def test_includes_common_english_function_words(self) -> None:
        # The set is intentionally bilingual so mixed-language text doesn't
        # leak filler tokens into BM25 queries.
        for word in ("the", "and", "of", "to"):
            assert word in GREEK_STOPWORDS

    def test_does_not_include_content_words(self) -> None:
        # Sanity check that content-bearing words aren't accidentally listed
        for word in ("μνημη", "memgentic", "search", "claude"):
            assert word not in GREEK_STOPWORDS
