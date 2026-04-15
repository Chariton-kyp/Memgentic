"""Tests for Antigravity adapter — Protocol Buffer conversation parsing."""

from __future__ import annotations

import pytest

from memgentic.adapters.antigravity import (
    AntigravityAdapter,
    _extract_strings_fallback,
    _extract_strings_from_protobuf,
    _is_readable_text,
    _read_varint,
)
from memgentic.models import ContentType, Platform


def _encode_varint(value: int) -> bytes:
    """Encode an integer as a protobuf varint."""
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def _encode_string_field(field_number: int, text: str) -> bytes:
    """Encode a string as a protobuf length-delimited field."""
    encoded = text.encode("utf-8")
    tag = (field_number << 3) | 2  # wire type 2 = length-delimited
    return _encode_varint(tag) + _encode_varint(len(encoded)) + encoded


def _encode_varint_field(field_number: int, value: int) -> bytes:
    """Encode an integer as a protobuf varint field."""
    tag = (field_number << 3) | 0  # wire type 0 = varint
    return _encode_varint(tag) + _encode_varint(value)


def _build_sample_pb() -> bytes:
    """Build a sample protobuf-like binary with conversation strings."""
    data = b""
    data += _encode_string_field(1, "How do I set up a Python virtual environment?")
    data += _encode_varint_field(2, 42)  # some numeric field
    data += _encode_string_field(
        3,
        "You can create a virtual environment using the venv module. Run python -m venv myenv to create one.",
    )
    data += _encode_string_field(4, "What about using conda instead of venv?")
    data += _encode_string_field(
        5,
        "Conda is a great alternative that also manages packages. Install Miniconda for a lightweight setup.",
    )
    return data


def _build_minimal_pb() -> bytes:
    """Build a minimal protobuf with one short string (below threshold)."""
    return _encode_string_field(1, "short")


def _build_nested_pb() -> bytes:
    """Build a protobuf with nested messages containing strings."""
    inner = _encode_string_field(
        1, "This is a nested message string inside the protobuf container."
    )
    # Wrap inner as a length-delimited field (field 2, wire type 2)
    tag = (2 << 3) | 2
    outer = _encode_varint(tag) + _encode_varint(len(inner)) + inner
    return outer


@pytest.fixture
def adapter():
    return AntigravityAdapter()


@pytest.fixture
def sample_pb_file(tmp_path):
    """Create a sample .pb file with protobuf-like conversation data."""
    file_path = tmp_path / "conversation-abc123.pb"
    file_path.write_bytes(_build_sample_pb())
    return file_path


@pytest.fixture
def empty_pb_file(tmp_path):
    """Create an empty .pb file."""
    file_path = tmp_path / "empty.pb"
    file_path.write_bytes(b"")
    return file_path


@pytest.fixture
def corrupted_pb_file(tmp_path):
    """Create a .pb file with random binary data."""
    file_path = tmp_path / "corrupted.pb"
    file_path.write_bytes(bytes(range(256)) * 4)
    return file_path


@pytest.fixture
def fallback_text_file(tmp_path):
    """Create a binary file with embedded ASCII text (for fallback extraction)."""
    file_path = tmp_path / "fallback.pb"
    data = (
        b"\x00\x01\x02\x03"
        + b"This is a long text string embedded in binary data for testing purposes."
        + b"\x00\x00\xff\xfe"
        + b"Another piece of readable text that should be extracted by the fallback method."
        + b"\x00\x01"
    )
    file_path.write_bytes(data)
    return file_path


# --- Platform / properties ---


def test_adapter_platform(adapter):
    assert adapter.platform == Platform.ANTIGRAVITY


def test_adapter_file_patterns(adapter):
    assert "*.pb" in adapter.file_patterns


def test_adapter_watch_paths(adapter):
    paths = adapter.watch_paths
    assert len(paths) == 1
    assert "antigravity" in str(paths[0])
    assert "conversations" in str(paths[0])


# --- discover_files ---


def test_discover_files_with_pb_files(adapter, tmp_path, monkeypatch):
    """Discover .pb files in the watch directory."""
    conv_dir = tmp_path / ".gemini" / "antigravity" / "conversations"
    conv_dir.mkdir(parents=True)
    (conv_dir / "conv1.pb").write_bytes(b"\x00")
    (conv_dir / "conv2.pb").write_bytes(b"\x00")
    (conv_dir / "readme.txt").write_text("ignore me")

    monkeypatch.setattr("memgentic.adapters.antigravity.ANTIGRAVITY_BASE", conv_dir)

    # Recreate adapter so it picks up the monkeypatched path
    from memgentic.adapters.antigravity import AntigravityAdapter

    a = AntigravityAdapter()
    files = a.discover_files()
    assert len(files) == 2
    assert all(f.suffix == ".pb" for f in files)


def test_discover_files_nonexistent_directory(adapter):
    """discover_files returns empty when directory doesn't exist."""
    # The default watch path likely doesn't exist in CI
    # Just verify it doesn't raise
    files = adapter.discover_files()
    assert isinstance(files, list)


# --- parse_file ---


@pytest.mark.asyncio
async def test_parse_file_valid_pb(adapter, sample_pb_file):
    """Parse a valid .pb file into conversation chunks."""
    chunks = await adapter.parse_file(sample_pb_file)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.content
        assert chunk.content_type in ContentType
        assert 0 <= chunk.confidence <= 1


@pytest.mark.asyncio
async def test_parse_file_empty(adapter, empty_pb_file):
    """Empty .pb files should return no chunks."""
    chunks = await adapter.parse_file(empty_pb_file)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_file_corrupted(adapter, corrupted_pb_file):
    """Corrupted data should not raise — returns empty or partial results."""
    chunks = await adapter.parse_file(corrupted_pb_file)
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_parse_file_nonexistent(adapter, tmp_path):
    """Non-existent file should return empty list, not raise."""
    fake_path = tmp_path / "does_not_exist.pb"
    chunks = await adapter.parse_file(fake_path)
    assert chunks == []


@pytest.mark.asyncio
async def test_parse_file_confidence_is_lower(adapter, sample_pb_file):
    """Antigravity chunks should have lower confidence due to best-effort parsing."""
    chunks = await adapter.parse_file(sample_pb_file)
    for chunk in chunks:
        assert chunk.confidence <= 0.7 or chunk.content_type == ContentType.CONVERSATION_SUMMARY


@pytest.mark.asyncio
async def test_parse_file_creates_summary_for_long_conversations(adapter, tmp_path):
    """Conversations with many strings should get a summary chunk."""
    # Build a .pb with many strings (>6 to get >2 chunks of 3)
    data = b""
    for i in range(12):
        data += _encode_string_field(
            i + 1, f"This is message number {i} in a long conversation about software architecture."
        )
    file_path = tmp_path / "long_conversation.pb"
    file_path.write_bytes(data)

    chunks = await adapter.parse_file(file_path)
    content_types = [c.content_type for c in chunks]
    assert ContentType.CONVERSATION_SUMMARY in content_types


# --- get_session_id / get_session_title ---


@pytest.mark.asyncio
async def test_get_session_id(adapter, sample_pb_file):
    session_id = await adapter.get_session_id(sample_pb_file)
    assert session_id == "conversation-abc123"


@pytest.mark.asyncio
async def test_get_session_title(adapter, sample_pb_file):
    title = await adapter.get_session_title(sample_pb_file)
    assert title is not None
    assert len(title) > 0
    assert len(title) <= 100


@pytest.mark.asyncio
async def test_get_session_title_empty_file(adapter, empty_pb_file):
    title = await adapter.get_session_title(empty_pb_file)
    assert title is None


# --- Protobuf parsing helpers ---


def test_extract_strings_from_protobuf():
    """Structured protobuf extraction finds all text fields."""
    data = _build_sample_pb()
    strings = _extract_strings_from_protobuf(data)
    assert len(strings) >= 4
    assert any("virtual environment" in s for s in strings)
    assert any("conda" in s.lower() for s in strings)


def test_extract_strings_from_protobuf_empty():
    strings = _extract_strings_from_protobuf(b"")
    assert strings == []


def test_extract_strings_nested_message():
    """Nested protobuf messages should also yield strings."""
    data = _build_nested_pb()
    strings = _extract_strings_from_protobuf(data)
    assert len(strings) >= 1
    assert any("nested" in s for s in strings)


def test_extract_strings_fallback_finds_text():
    """Fallback extraction should find ASCII text runs in binary data."""
    data = (
        b"\x00\x01\x02"
        + b"This is a long enough text string for the fallback extractor to find it."
        + b"\xff\xfe"
    )
    strings = _extract_strings_fallback(data)
    assert len(strings) >= 1
    assert any("fallback" in s for s in strings)


def test_extract_strings_fallback_empty():
    strings = _extract_strings_fallback(b"")
    assert strings == []


def test_extract_strings_fallback_binary_only():
    """Pure binary data (no printable runs) should yield nothing."""
    data = bytes(range(0, 32)) * 10  # control characters only
    strings = _extract_strings_fallback(data)
    assert strings == []


def test_read_varint_basic():
    """Read a simple single-byte varint."""
    data = _encode_varint(42)
    value, pos = _read_varint(data, 0)
    assert value == 42
    assert pos == len(data)


def test_read_varint_multibyte():
    """Read a multi-byte varint."""
    data = _encode_varint(300)
    value, pos = _read_varint(data, 0)
    assert value == 300


def test_read_varint_empty():
    """Reading from empty data should return None."""
    value, pos = _read_varint(b"", 0)
    assert value is None


def test_is_readable_text():
    assert _is_readable_text("Hello, world!") is True
    assert _is_readable_text("   ") is False  # whitespace only
    assert _is_readable_text("") is False
    # Mostly control characters
    assert _is_readable_text("\x00\x01\x02\x03\x04") is False


# --- Topic extraction ---


@pytest.mark.asyncio
async def test_topic_extraction(adapter, tmp_path):
    """Adapter should extract tech topics from parsed content."""
    data = _encode_string_field(1, "We should use Python with FastAPI for the backend REST API")
    data += _encode_string_field(
        2, "Docker containers will handle deployment and Kubernetes for orchestration"
    )
    file_path = tmp_path / "topics.pb"
    file_path.write_bytes(data)

    chunks = await adapter.parse_file(file_path)
    all_topics: set[str] = set()
    for chunk in chunks:
        all_topics.update(chunk.topics)
    assert "python" in all_topics or "docker" in all_topics or "fastapi" in all_topics
