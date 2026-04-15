"""Tests for Codex CLI adapter."""

import pytest

from memgentic.adapters.codex_cli import CodexCliAdapter
from memgentic.models import ContentType, Platform

SAMPLE_SINGLE_HASH = """\
# User
What does this function do?

# Assistant
This function calculates the fibonacci sequence recursively.
It takes an integer n and returns the nth fibonacci number.

# User
Can you optimize it?

# Assistant
Here's an optimized version using memoization:
```python
from functools import lru_cache

@lru_cache(maxsize=None)
def fibonacci(n: int) -> int:
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
```

# User
What about an iterative approach?

# Assistant
An iterative approach avoids recursion depth limits entirely:
```python
def fibonacci_iter(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
```
"""

SAMPLE_DOUBLE_HASH = """\
## User
How do I set up Docker for this project?

## Assistant
You'll need a Dockerfile and docker-compose.yml.
Here's a basic setup for a Python FastAPI app.

## User
Let's go with that approach.

## Assistant
Great decision. I'll create the files for you.
"""


@pytest.fixture
def adapter():
    return CodexCliAdapter()


@pytest.fixture
def single_hash_conversation(tmp_path):
    """Create a sample conversation.md with # headers."""
    session_dir = tmp_path / "session-abc123"
    session_dir.mkdir()
    file_path = session_dir / "conversation.md"
    file_path.write_text(SAMPLE_SINGLE_HASH, encoding="utf-8")
    return file_path


@pytest.fixture
def double_hash_conversation(tmp_path):
    """Create a sample conversation.md with ## headers."""
    session_dir = tmp_path / "session-def456"
    session_dir.mkdir()
    file_path = session_dir / "conversation.md"
    file_path.write_text(SAMPLE_DOUBLE_HASH, encoding="utf-8")
    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.CODEX_CLI


def test_adapter_file_patterns(adapter):
    assert "conversation.md" in adapter.file_patterns
    assert "*.md" in adapter.file_patterns


@pytest.mark.asyncio
async def test_parse_file_single_hash(adapter, single_hash_conversation):
    chunks = await adapter.parse_file(single_hash_conversation)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_file_double_hash(adapter, double_hash_conversation):
    chunks = await adapter.parse_file(double_hash_conversation)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_extracts_correct_exchange_count(adapter, single_hash_conversation):
    chunks = await adapter.parse_file(single_hash_conversation)
    # 3 user messages = 3 exchange chunks + 1 summary (since > 2)
    exchange_chunks = [c for c in chunks if c.content_type != ContentType.CONVERSATION_SUMMARY]
    assert len(exchange_chunks) == 3


@pytest.mark.asyncio
async def test_get_session_id(adapter, single_hash_conversation):
    session_id = await adapter.get_session_id(single_hash_conversation)
    assert session_id == "session-abc123"


@pytest.mark.asyncio
async def test_get_session_id_double_hash(adapter, double_hash_conversation):
    session_id = await adapter.get_session_id(double_hash_conversation)
    assert session_id == "session-def456"


@pytest.mark.asyncio
async def test_get_session_title(adapter, single_hash_conversation):
    title = await adapter.get_session_title(single_hash_conversation)
    assert title is not None
    assert "function" in title.lower()


@pytest.mark.asyncio
async def test_parse_empty_file(adapter, tmp_path):
    session_dir = tmp_path / "session-empty"
    session_dir.mkdir()
    empty_file = session_dir / "conversation.md"
    empty_file.write_text("", encoding="utf-8")
    chunks = await adapter.parse_file(empty_file)
    assert chunks == []


@pytest.mark.asyncio
async def test_content_classification_code(adapter, single_hash_conversation):
    chunks = await adapter.parse_file(single_hash_conversation)
    content_types = [c.content_type for c in chunks]
    # Should detect code snippets due to ``` markers
    assert ContentType.CODE_SNIPPET in content_types


@pytest.mark.asyncio
async def test_content_classification_decision(adapter, double_hash_conversation):
    chunks = await adapter.parse_file(double_hash_conversation)
    content_types = [c.content_type for c in chunks]
    # "let's go with" should trigger decision classification
    assert ContentType.DECISION in content_types


@pytest.mark.asyncio
async def test_topic_extraction(adapter, single_hash_conversation):
    chunks = await adapter.parse_file(single_hash_conversation)
    all_topics: set[str] = set()
    for chunk in chunks:
        all_topics.update(chunk.topics)
    assert "python" in all_topics
