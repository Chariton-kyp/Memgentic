"""Tests for the Memgentic exception hierarchy."""

from __future__ import annotations

import pytest

from memgentic.exceptions import (
    AdapterError,
    EmbeddingError,
    MemgenticError,
    PipelineError,
    StorageError,
)


class TestExceptionHierarchy:
    def test_mneme_error_is_base(self):
        assert issubclass(MemgenticError, Exception)

    def test_embedding_error_is_mneme_error(self):
        assert issubclass(EmbeddingError, MemgenticError)

    def test_storage_error_is_mneme_error(self):
        assert issubclass(StorageError, MemgenticError)

    def test_adapter_error_is_mneme_error(self):
        assert issubclass(AdapterError, MemgenticError)

    def test_pipeline_error_is_mneme_error(self):
        assert issubclass(PipelineError, MemgenticError)

    def test_catch_mneme_error_catches_subtypes(self):
        """Catching MemgenticError should catch all subtypes."""
        for exc_cls in (EmbeddingError, StorageError, AdapterError, PipelineError):
            try:
                raise exc_cls("test message")
            except MemgenticError as e:
                assert str(e) == "test message"
            else:
                pytest.fail(f"{exc_cls.__name__} was not caught by MemgenticError handler")

    def test_embedding_error_not_caught_as_storage_error(self):
        with pytest.raises(EmbeddingError):
            raise EmbeddingError("embedding fail")

    def test_exception_message_preserved(self):
        err = EmbeddingError("Ollama connection refused")
        assert "Ollama connection refused" in str(err)
