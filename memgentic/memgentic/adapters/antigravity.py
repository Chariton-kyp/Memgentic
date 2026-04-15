"""Antigravity adapter — parses Protocol Buffer conversation files from ~/.gemini/antigravity/."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from memgentic.adapters.base import BaseAdapter
from memgentic.models import ContentType, ConversationChunk, Platform

logger = structlog.get_logger()

# Try to use the Rust-native protobuf parser (15-30x faster).
try:
    from memgentic_native.parsers import extract_strings_fallback as _native_pb_fallback
    from memgentic_native.parsers import extract_strings_from_protobuf as _native_pb_extract

    _USE_NATIVE_PB = True
except ImportError:
    _USE_NATIVE_PB = False

# Antigravity stores conversations at ~/.gemini/antigravity/conversations/*.pb
ANTIGRAVITY_BASE = Path.home() / ".gemini" / "antigravity" / "conversations"


def _extract_strings_from_protobuf(data: bytes, min_length: int = 10) -> list[str]:
    """Extract UTF-8 strings from raw protobuf wire-format data.

    Protobuf encodes strings as length-delimited fields (wire type 2):
        - varint field tag (field_number << 3 | 2)
        - varint length
        - UTF-8 bytes

    This function walks the wire format and pulls out all length-delimited
    fields that decode as valid UTF-8 text.  Non-string fields (nested
    messages, packed repeated fields) are silently skipped.

    Args:
        data: Raw bytes from a ``.pb`` file.
        min_length: Minimum character length for a string to be kept.

    Returns:
        Ordered list of extracted text strings.
    """
    strings: list[str] = []
    pos = 0
    size = len(data)

    while pos < size:
        # Read varint (field tag)
        tag, pos = _read_varint(data, pos)
        if tag is None or pos >= size:
            break

        wire_type = tag & 0x07

        if wire_type == 0:
            # Varint — skip
            _, pos = _read_varint(data, pos)
            if pos is None:
                break
        elif wire_type == 1:
            # 64-bit fixed — skip 8 bytes
            pos += 8
        elif wire_type == 2:
            # Length-delimited (string, bytes, nested message, packed repeated)
            length, pos = _read_varint(data, pos)
            if length is None or pos + length > size:
                break
            chunk = data[pos : pos + length]
            pos += length

            # Try to decode as UTF-8 text
            try:
                text = chunk.decode("utf-8")
                # Filter: must be mostly printable and long enough
                if len(text) >= min_length and _is_readable_text(text):
                    strings.append(text)
            except (UnicodeDecodeError, ValueError):
                # Not a string field — could be nested message or bytes
                # Try to recurse into it as a nested message
                nested = _extract_strings_from_protobuf(chunk, min_length)
                strings.extend(nested)
        elif wire_type == 5:
            # 32-bit fixed — skip 4 bytes
            pos += 4
        else:
            # Unknown wire type — cannot continue safely
            break

    return strings


def _read_varint(data: bytes, pos: int) -> tuple[int | None, int]:
    """Read a protobuf varint starting at *pos*.

    Returns:
        Tuple of (decoded value or None on error, new position).
    """
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return result, pos
        shift += 7
        if shift > 63:
            # Malformed varint
            return None, pos
    return None, pos


def _is_readable_text(text: str) -> bool:
    """Heuristic: return True if the text is mostly human-readable.

    Rejects binary-looking strings that happen to be valid UTF-8.
    """
    if not text.strip():
        return False
    printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
    return printable / len(text) >= 0.85


def _extract_strings_fallback(data: bytes, min_length: int = 20) -> list[str]:
    """Fallback text extraction — scan for runs of printable UTF-8.

    Used when structured protobuf parsing yields no results.  Slides a
    window over the raw bytes looking for long runs of valid UTF-8 text.

    Args:
        data: Raw file bytes.
        min_length: Minimum character length for an extracted string.

    Returns:
        List of extracted text strings.
    """
    strings: list[str] = []
    pos = 0
    size = len(data)

    while pos < size:
        # Skip non-printable bytes
        if not (32 <= data[pos] <= 126 or data[pos] in (9, 10, 13)):
            pos += 1
            continue

        # Start of a potential text run
        start = pos
        while pos < size and (32 <= data[pos] <= 126 or data[pos] in (9, 10, 13)):
            pos += 1

        chunk = data[start:pos]
        try:
            text = chunk.decode("utf-8").strip()
            if len(text) >= min_length and _is_readable_text(text):
                strings.append(text)
        except (UnicodeDecodeError, ValueError):
            pass

    return strings


class AntigravityAdapter(BaseAdapter):
    """Parse Antigravity (Google Gemini experimental) conversation history.

    Antigravity stores conversations as Protocol Buffer (``.pb``) files in
    ``~/.gemini/antigravity/conversations/``.  Because the exact ``.proto``
    schema is not publicly documented, this adapter uses a best-effort
    approach:

    1. **Structured parsing** — walk the protobuf wire format and extract
       all length-delimited fields that decode as readable UTF-8 text.
    2. **Fallback extraction** — if structured parsing yields nothing,
       scan for long runs of printable ASCII/UTF-8 in the raw bytes.

    Extracted text strings are grouped into conversation chunks ready for
    the ingestion pipeline.
    """

    @property
    def platform(self) -> Platform:
        return Platform.ANTIGRAVITY

    @property
    def watch_paths(self) -> list[Path]:
        return [ANTIGRAVITY_BASE]

    @property
    def file_patterns(self) -> list[str]:
        return ["*.pb"]

    async def get_session_id(self, file_path: Path) -> str | None:
        """Session ID is the filename without extension."""
        return file_path.stem

    async def get_session_title(self, file_path: Path) -> str | None:
        """Extract the first meaningful text string as a session title."""
        strings = await asyncio.to_thread(self._read_strings, file_path)
        if strings:
            return strings[0][:100].strip()
        return None

    async def parse_file(self, file_path: Path) -> list[ConversationChunk]:
        """Parse an Antigravity .pb conversation file into chunks.

        Strategy: Extract all readable strings from the protobuf data, then
        group consecutive strings into exchange-sized chunks.  Each chunk
        becomes a memory unit.

        Args:
            file_path: Path to a ``.pb`` conversation file.

        Returns:
            List of ConversationChunk objects ready for ingestion.
        """
        strings = await asyncio.to_thread(self._read_strings, file_path)

        if not strings:
            return []

        chunks: list[ConversationChunk] = []

        # Group strings into chunks of ~3 strings each (approximate exchanges)
        group_size = 3
        for i in range(0, len(strings), group_size):
            group = strings[i : i + group_size]
            chunk_text = "\n\n".join(group)

            if len(chunk_text) > 50:  # Skip trivially short chunks
                chunks.append(
                    ConversationChunk(
                        content=chunk_text,
                        content_type=self._classify_content(chunk_text),
                        topics=self._extract_topics(chunk_text),
                        entities=[],
                        confidence=0.7,  # Lower confidence due to best-effort parsing
                    )
                )

        # Summary chunk for longer conversations
        if len(chunks) > 2:
            summary_parts = []
            for i, chunk in enumerate(chunks[:5], 1):
                preview = chunk.content[:200]
                summary_parts.append(f"Exchange {i}: {preview}")

            summary = f"Antigravity conversation with {len(chunks)} chunks.\n\n" + "\n\n".join(
                summary_parts
            )
            chunks.insert(
                0,
                ConversationChunk(
                    content=summary,
                    content_type=ContentType.CONVERSATION_SUMMARY,
                    topics=self._merge_topics(chunks),
                    entities=[],
                    confidence=0.65,
                ),
            )

        logger.info(
            "antigravity.parsed",
            file=str(file_path),
            strings=len(strings),
            chunks=len(chunks),
        )
        return chunks

    # --- Private helpers ---

    def _read_strings(self, file_path: Path) -> list[str]:
        """Synchronous helper — read and extract text strings from a .pb file.

        Uses Rust native protobuf parser when available (15-30x faster).
        """
        try:
            data = file_path.read_bytes()
        except OSError as e:
            logger.warning("antigravity.read_error", file=str(file_path), error=str(e))
            return []

        if not data:
            return []

        if _USE_NATIVE_PB:
            try:
                strings = list(_native_pb_extract(data))
                if not strings:
                    strings = list(_native_pb_fallback(data))
                return strings
            except Exception as e:
                logger.warning(
                    "antigravity.native_parse_fallback",
                    file=str(file_path),
                    error=str(e),
                )

        # Python fallback
        strings = _extract_strings_from_protobuf(data)

        if not strings:
            strings = _extract_strings_fallback(data)

        return strings
