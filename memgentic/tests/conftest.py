"""Shared test fixtures for Memgentic test suite."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    ConversationChunk,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.storage.metadata import MetadataStore


@pytest.fixture()
def tmp_settings(tmp_path: Path) -> MemgenticSettings:
    """MemgenticSettings pointing at a temporary data directory."""
    return MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",  # Unreachable — force local file mode for tests
        collection_name="test_memories",
        embedding_dimensions=768,
    )


@pytest.fixture()
async def metadata_store(tmp_path: Path):
    """Initialised MetadataStore backed by a temporary SQLite database."""
    db_path = tmp_path / "test_memgentic.db"
    store = MetadataStore(db_path)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture()
def sample_source() -> SourceMetadata:
    """Reusable source metadata."""
    return SourceMetadata(
        platform=Platform.CLAUDE_CODE,
        platform_version="claude-sonnet-4",
        session_id="session-001",
        session_title="Architecture discussion",
        capture_method=CaptureMethod.AUTO_DAEMON,
        original_timestamp=datetime(2026, 3, 25, 10, 0, 0, tzinfo=UTC),
        file_path="/home/user/.claude/projects/test/conversation.jsonl",
    )


@pytest.fixture()
def sample_memory(sample_source: SourceMetadata) -> Memory:
    """A Memory instance with full metadata."""
    return Memory(
        id="mem-test-001",
        content="We decided to use Qdrant for vector storage because of its local file mode.",
        content_type=ContentType.DECISION,
        source=sample_source,
        topics=["qdrant", "vector-db", "architecture"],
        entities=["ExampleCorp", "Memgentic"],
        confidence=0.95,
    )


@pytest.fixture(scope="session")
def benchmark_recorder(tmp_path_factory) -> Callable[[str, float], None]:
    """Append benchmark results to a JSON file in a session-scoped temp dir.

    Usage:
        def test_something(benchmark_recorder):
            benchmark_recorder("label", elapsed_seconds)
    """
    results_dir = tmp_path_factory.mktemp("benchmarks")
    results_file = results_dir / "results.json"

    def _record(name: str, value: float) -> None:
        data = []
        if results_file.exists():
            try:
                data = json.loads(results_file.read_text())
            except Exception:
                data = []
        data.append({"name": name, "value": value})
        results_file.write_text(json.dumps(data, indent=2))

    return _record


@pytest.fixture()
def sample_chunks() -> list[ConversationChunk]:
    """A list of ConversationChunk objects for pipeline testing."""
    return [
        ConversationChunk(
            content="We chose Qdrant for vector search due to its local file-based mode.",
            content_type=ContentType.DECISION,
            topics=["qdrant", "architecture"],
            entities=["Memgentic"],
            confidence=0.9,
        ),
        ConversationChunk(
            content="The embedding model is Qwen3-Embedding-4B with 768d MRL truncation.",
            content_type=ContentType.FACT,
            topics=["embeddings", "qwen3"],
            entities=["Ollama"],
            confidence=0.95,
        ),
        ConversationChunk(
            content="User prefers 100% agent-driven implementation, zero manual coding.",
            content_type=ContentType.PREFERENCE,
            topics=["workflow"],
            entities=["Chariton"],
            confidence=1.0,
        ),
    ]
