"""Tests for Memgentic data models."""

from memgentic.models import (
    CaptureMethod,
    ContentType,
    ConversationChunk,
    Memory,
    MemoryStatus,
    Platform,
    SessionConfig,
    SourceMetadata,
)


def test_memory_creation():
    """Test that a Memory can be created with minimal fields."""
    source = SourceMetadata(platform=Platform.CLAUDE_CODE)
    memory = Memory(content="Test memory content", source=source)

    assert memory.content == "Test memory content"
    assert memory.source.platform == Platform.CLAUDE_CODE
    assert memory.content_type == ContentType.FACT
    assert memory.status == MemoryStatus.ACTIVE
    assert memory.confidence == 1.0
    assert memory.access_count == 0
    assert memory.id  # Auto-generated UUID


def test_memory_with_full_metadata():
    """Test Memory creation with all fields."""
    source = SourceMetadata(
        platform=Platform.CHATGPT,
        platform_version="gpt-4o",
        session_id="abc123",
        session_title="Architecture discussion",
        capture_method=CaptureMethod.JSON_IMPORT,
    )
    memory = Memory(
        content="We decided to use FastAPI",
        content_type=ContentType.DECISION,
        source=source,
        topics=["fastapi", "architecture"],
        entities=["ExampleCorp"],
        confidence=0.95,
    )

    assert memory.source.platform_version == "gpt-4o"
    assert memory.content_type == ContentType.DECISION
    assert "fastapi" in memory.topics
    assert memory.confidence == 0.95


def test_session_config_defaults():
    """Test SessionConfig with default values."""
    config = SessionConfig()
    assert config.include_sources is None
    assert config.exclude_sources is None
    assert config.min_confidence == 0.0


def test_session_config_with_filters():
    """Test SessionConfig with source filters."""
    config = SessionConfig(
        include_sources=[Platform.CLAUDE_CODE, Platform.GEMINI_CLI],
        exclude_sources=None,
        min_confidence=0.5,
    )
    assert len(config.include_sources) == 2
    assert Platform.CLAUDE_CODE in config.include_sources


def test_conversation_chunk():
    """Test ConversationChunk creation."""
    chunk = ConversationChunk(
        content="Human: How do I use FastAPI?\n\nAssistant: Here's how...",
        content_type=ContentType.RAW_EXCHANGE,
        topics=["fastapi", "python"],
    )
    assert chunk.content_type == ContentType.RAW_EXCHANGE
    assert "fastapi" in chunk.topics


def test_platform_enum_values():
    """Test all Platform enum values exist."""
    assert Platform.CLAUDE_CODE.value == "claude_code"
    assert Platform.CHATGPT.value == "chatgpt"
    assert Platform.GEMINI_CLI.value == "gemini_cli"
    assert Platform.ANTIGRAVITY.value == "antigravity"
    assert Platform.CODEX_CLI.value == "codex_cli"
    assert Platform.COPILOT_CLI.value == "copilot_cli"
    assert Platform.AIDER.value == "aider"
