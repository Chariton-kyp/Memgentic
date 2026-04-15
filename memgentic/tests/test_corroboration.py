"""Tests for cross-platform corroboration — confidence boosting when sources confirm facts."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from memgentic.config import MemgenticSettings, StorageBackend
from memgentic.models import (
    CaptureMethod,
    ContentType,
    Memory,
    Platform,
    SourceMetadata,
)
from memgentic.processing.corroboration import check_corroboration


def _make_memory(
    mid: str = "m-1",
    content: str = "test content",
    platform: Platform = Platform.CLAUDE_CODE,
    confidence: float = 0.8,
) -> Memory:
    return Memory(
        id=mid,
        content=content,
        content_type=ContentType.FACT,
        source=SourceMetadata(
            platform=platform,
            capture_method=CaptureMethod.MCP_TOOL,
        ),
        confidence=confidence,
    )


@pytest.fixture()
def settings(tmp_path):
    return MemgenticSettings(
        data_dir=tmp_path / "memgentic_data",
        storage_backend=StorageBackend.LOCAL,
        qdrant_url="http://localhost:1",
        collection_name="test_memories",
        embedding_dimensions=768,
        enable_corroboration=True,
        corroboration_threshold=0.85,
        corroboration_boost=0.1,
    )


class TestCorroboration:
    """Tests for cross-platform confidence boosting."""

    async def test_cross_platform_boosts_confidence(self, settings):
        """Memory from claude_code, new memory from chatgpt with high similarity → boost."""
        new_memory = _make_memory(mid="new-1", platform=Platform.CHATGPT, confidence=0.9)
        embedding = [0.1] * 768

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "existing-1",
                    "score": 0.90,
                    "payload": {"platform": "claude_code", "confidence": 0.8},
                }
            ]
        )

        mock_ms = AsyncMock()
        mock_ms.update_corroboration = AsyncMock()

        await check_corroboration(new_memory, embedding, mock_vs, mock_ms, settings)

        mock_ms.update_corroboration.assert_called_once()
        call_args = mock_ms.update_corroboration.call_args
        assert call_args.kwargs["memory_id"] == "existing-1"
        assert call_args.kwargs["platform"] == "chatgpt"
        assert call_args.kwargs["new_confidence"] == pytest.approx(0.9)  # 0.8 + 0.1

    async def test_same_platform_no_boost(self, settings):
        """Same platform → no corroboration."""
        new_memory = _make_memory(mid="new-2", platform=Platform.CLAUDE_CODE)
        embedding = [0.1] * 768

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "existing-2",
                    "score": 0.95,
                    "payload": {"platform": "claude_code", "confidence": 0.9},
                }
            ]
        )

        mock_ms = AsyncMock()

        await check_corroboration(new_memory, embedding, mock_vs, mock_ms, settings)

        mock_ms.update_corroboration.assert_not_called()

    async def test_below_threshold_no_boost(self, settings):
        """Similarity < 0.85 → no boost."""
        new_memory = _make_memory(mid="new-3", platform=Platform.CHATGPT)
        embedding = [0.1] * 768

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "existing-3",
                    "score": 0.70,
                    "payload": {"platform": "claude_code", "confidence": 0.8},
                }
            ]
        )

        mock_ms = AsyncMock()

        await check_corroboration(new_memory, embedding, mock_vs, mock_ms, settings)

        mock_ms.update_corroboration.assert_not_called()

    async def test_confidence_capped_at_1(self, settings):
        """Boost doesn't exceed 1.0."""
        new_memory = _make_memory(mid="new-4", platform=Platform.CHATGPT)
        embedding = [0.1] * 768

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "existing-4",
                    "score": 0.92,
                    "payload": {"platform": "claude_code", "confidence": 0.98},
                }
            ]
        )

        mock_ms = AsyncMock()
        mock_ms.update_corroboration = AsyncMock()

        await check_corroboration(new_memory, embedding, mock_vs, mock_ms, settings)

        call_args = mock_ms.update_corroboration.call_args
        assert call_args.kwargs["new_confidence"] <= 1.0

    async def test_disabled_by_config(self, settings):
        """enable_corroboration=False → no search called."""
        settings.enable_corroboration = False
        new_memory = _make_memory(mid="new-5", platform=Platform.CHATGPT)
        embedding = [0.1] * 768

        mock_vs = AsyncMock()
        mock_ms = AsyncMock()

        await check_corroboration(new_memory, embedding, mock_vs, mock_ms, settings)

        mock_vs.search.assert_not_called()
        mock_ms.update_corroboration.assert_not_called()

    async def test_records_platform(self, settings):
        """corroborated_by list updated with the new platform."""
        new_memory = _make_memory(mid="new-6", platform=Platform.GEMINI_CLI)
        embedding = [0.1] * 768

        mock_vs = AsyncMock()
        mock_vs.search = AsyncMock(
            return_value=[
                {
                    "id": "existing-6",
                    "score": 0.90,
                    "payload": {"platform": "claude_code", "confidence": 0.7},
                }
            ]
        )

        mock_ms = AsyncMock()
        mock_ms.update_corroboration = AsyncMock()

        await check_corroboration(new_memory, embedding, mock_vs, mock_ms, settings)

        call_args = mock_ms.update_corroboration.call_args
        assert call_args.kwargs["platform"] == "gemini_cli"
