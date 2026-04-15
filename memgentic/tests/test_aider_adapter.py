"""Tests for Aider adapter."""

import pytest

from memgentic.adapters.aider import AiderAdapter
from memgentic.models import ContentType, Platform

SAMPLE_HISTORY = """\
#### user
How should I refactor this function?

#### assistant
I'd suggest breaking it into smaller functions...

#### user
Can you show me the code?

#### assistant
Here's the refactored version:
```python
def helper():
    pass
```

#### user
What about testing?

#### assistant
For testing, you should do something like this:
```python
def test_helper():
    assert helper() is None
```
"""

SAMPLE_WITH_CODE_BLOCKS = """\
#### user
Show me a Docker setup

#### assistant
Here's a Dockerfile:
```dockerfile
FROM python:3.12-slim
COPY . /app
RUN pip install -e .
```

And a docker-compose file:
```yaml
services:
  app:
    build: .
```
"""


@pytest.fixture
def adapter():
    return AiderAdapter()


@pytest.fixture
def sample_conversation(tmp_path):
    """Create a sample .aider.chat.history.md file."""
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    file_path = project_dir / ".aider.chat.history.md"
    file_path.write_text(SAMPLE_HISTORY, encoding="utf-8")
    return file_path


@pytest.fixture
def code_block_conversation(tmp_path):
    """Create a conversation with embedded code blocks."""
    project_dir = tmp_path / "docker-project"
    project_dir.mkdir()
    file_path = project_dir / ".aider.chat.history.md"
    file_path.write_text(SAMPLE_WITH_CODE_BLOCKS, encoding="utf-8")
    return file_path


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.AIDER


def test_adapter_watch_paths_empty(adapter):
    assert adapter.watch_paths == []


def test_adapter_file_patterns(adapter):
    assert ".aider.chat.history.md" in adapter.file_patterns


@pytest.mark.asyncio
async def test_parse_file(adapter, sample_conversation):
    chunks = await adapter.parse_file(sample_conversation)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType


@pytest.mark.asyncio
async def test_parse_file_extracts_exchanges(adapter, sample_conversation):
    chunks = await adapter.parse_file(sample_conversation)
    # 3 user messages = 3 exchange chunks + 1 summary (since > 2)
    exchange_chunks = [c for c in chunks if c.content_type != ContentType.CONVERSATION_SUMMARY]
    assert len(exchange_chunks) == 3
    # Each exchange should start with "Human:"
    for chunk in exchange_chunks:
        assert "Human:" in chunk.content


@pytest.mark.asyncio
async def test_parse_handles_code_blocks(adapter, code_block_conversation):
    chunks = await adapter.parse_file(code_block_conversation)
    assert len(chunks) > 0
    # The assistant response with code blocks should be preserved
    all_content = " ".join(c.content for c in chunks)
    assert "Dockerfile" in all_content or "dockerfile" in all_content.lower()


@pytest.mark.asyncio
async def test_parse_empty_file(adapter, tmp_path):
    empty_file = tmp_path / ".aider.chat.history.md"
    empty_file.write_text("", encoding="utf-8")
    chunks = await adapter.parse_file(empty_file)
    assert chunks == []


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_conversation):
    session_id = await adapter.get_session_id(sample_conversation)
    assert session_id == "my-project"


@pytest.mark.asyncio
async def test_get_session_title(adapter, sample_conversation):
    title = await adapter.get_session_title(sample_conversation)
    assert title is not None
    assert "refactor" in title.lower()


@pytest.mark.asyncio
async def test_content_classification(adapter, code_block_conversation):
    chunks = await adapter.parse_file(code_block_conversation)
    content_types = [c.content_type for c in chunks]
    # Should detect code snippets due to ``` markers
    assert ContentType.CODE_SNIPPET in content_types


@pytest.mark.asyncio
async def test_topic_extraction(adapter, code_block_conversation):
    chunks = await adapter.parse_file(code_block_conversation)
    all_topics: set[str] = set()
    for chunk in chunks:
        all_topics.update(chunk.topics)
    assert "docker" in all_topics or "python" in all_topics
