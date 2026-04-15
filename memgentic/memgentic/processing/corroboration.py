"""Corroboration — boost confidence when multiple sources confirm the same fact."""

from __future__ import annotations

import structlog

from memgentic.config import MemgenticSettings
from memgentic.models import Memory
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

logger = structlog.get_logger()


async def check_corroboration(
    memory: Memory,
    embedding: list[float],
    vector_store: VectorStore,
    metadata_store: MetadataStore,
    settings: MemgenticSettings,
) -> None:
    """Check if a new memory is corroborated by existing memories from other platforms.

    If a semantically similar memory (>threshold) exists from a DIFFERENT platform,
    boost the existing memory's confidence and record the corroboration.
    """
    if not settings.enable_corroboration:
        return

    try:
        results = await vector_store.search(embedding, limit=5)
    except Exception as e:
        logger.debug("corroboration.search_failed", error=str(e))
        return

    for result in results:
        score = result.get("score", 0)
        if score < settings.corroboration_threshold:
            continue

        payload = result.get("payload", {})
        existing_platform = payload.get("platform", "")

        # Only corroborate across different platforms
        if existing_platform == memory.source.platform.value:
            continue

        existing_id = result["id"]
        new_platform = memory.source.platform.value

        # Boost existing memory's confidence
        new_confidence = min(
            (payload.get("confidence", 1.0) or 1.0) + settings.corroboration_boost,
            1.0,
        )

        try:
            await metadata_store.update_corroboration(
                memory_id=existing_id,
                platform=new_platform,
                new_confidence=new_confidence,
            )
            logger.info(
                "corroboration.detected",
                existing_id=existing_id,
                existing_platform=existing_platform,
                new_platform=new_platform,
                score=round(score, 3),
                new_confidence=new_confidence,
            )
        except Exception as e:
            logger.debug("corroboration.update_failed", error=str(e))
