"""Background maintenance — merge duplicates, flag contradictions, recompute importance.

Renamed from ``processing/consolidation.py`` (Plan 12 §6.5) to free the
``consolidation`` namespace for the future Layer-S/P LLM-distillation
worker (``memgentic/consolidation/distiller.py``). Behavior is unchanged
from the prior ``consolidation.py``: this module covers the deterministic
maintenance ops that operate on Layer E (episodic) memories — duplicate
merging, contradiction flagging, importance recomputation.

Public functions (``consolidate``, ``find_duplicates``, etc.) keep the
same signatures and return types so call sites update only the import
path, not the call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from memgentic.config import MemgenticSettings
from memgentic.models import MemoryStatus, SessionConfig
from memgentic.processing.embedder import Embedder
from memgentic.processing.utils import text_overlap
from memgentic.storage.metadata import MetadataStore
from memgentic.storage.vectors import VectorStore

logger = structlog.get_logger()


@dataclass
class ConsolidationReport:
    """Summary of a consolidation run."""

    duplicates_merged: int = 0
    contradictions_flagged: int = 0
    importance_updated: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)


async def consolidate(
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    settings: MemgenticSettings,
) -> ConsolidationReport:
    """Run all consolidation operations. Returns a report."""
    report = ConsolidationReport()

    # Step 1: Recompute importance scores for all active memories
    await _recompute_importance(metadata_store, settings, report)

    # Step 2: Merge duplicates + detect contradictions
    await _merge_duplicates(metadata_store, vector_store, embedder, settings, report)

    return report


async def _recompute_importance(
    metadata_store: MetadataStore,
    settings: MemgenticSettings,
    report: ConsolidationReport,
) -> None:
    """Recompute importance_score for all active memories based on age and access."""
    half_life = settings.memory_half_life_days
    now = datetime.now(UTC)

    memories = await metadata_store.get_memories_by_filter(
        session_config=SessionConfig(), limit=10000
    )

    updates: list[tuple[str, float]] = []
    for memory in memories:
        try:
            age_days = (now - memory.created_at).days
            recency = math.exp(-age_days / half_life) if half_life > 0 else 1.0
            access_boost = 1.0 + math.log1p(memory.access_count) * 0.1
            new_score = round(min(recency * access_boost, 1.0), 4)

            if abs(new_score - memory.importance_score) > 0.001:
                updates.append((memory.id, new_score))
                report.importance_updated += 1
        except Exception as e:
            report.errors += 1
            logger.debug("consolidation.importance_error", id=memory.id, error=str(e))

    if updates:
        await metadata_store.update_importance_scores_batch(updates)
        report.details.append(f"Updated importance scores for {report.importance_updated} memories")
    logger.info(
        "consolidation.importance_done",
        updated=report.importance_updated,
        total=len(memories),
    )


async def _merge_duplicates(
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    embedder: Embedder,
    settings: MemgenticSettings,
    report: ConsolidationReport,
) -> None:
    """Find and merge near-duplicate memories from the same platform."""
    memories = await metadata_store.get_memories_by_filter(
        session_config=SessionConfig(), limit=5000
    )

    processed: set[str] = set()

    for memory in memories:
        if memory.id in processed:
            continue

        try:
            embedding = await embedder.embed(memory.content)
            results = await vector_store.search(embedding, limit=5)
        except Exception:
            continue

        for result in results:
            other_id = result["id"]
            if other_id == memory.id or other_id in processed:
                continue

            score = result.get("score", 0)
            other_platform = result.get("payload", {}).get("platform", "")

            # Same platform + high similarity = duplicate
            if score > 0.92 and other_platform == memory.source.platform.value:
                other = await metadata_store.get_memory(other_id)
                if not other:
                    continue

                # Keep the one with higher confidence, then newer
                keep, discard = (
                    (memory, other) if memory.confidence >= other.confidence else (other, memory)
                )

                discard.status = MemoryStatus.SUPERSEDED
                discard.supersedes = []
                keep.supersedes = list(set(keep.supersedes + [discard.id]))

                await metadata_store.save_memory(discard)
                await metadata_store.save_memory(keep)
                await vector_store.delete_memory(discard.id)

                processed.add(discard.id)
                report.duplicates_merged += 1
                report.details.append(
                    f"Merged duplicate: {discard.id[:8]}... → {keep.id[:8]}... "
                    f"(platform={other_platform}, similarity={score:.3f})"
                )

            # Different platform + high similarity + different content = contradiction
            elif score > 0.85 and other_platform != memory.source.platform.value:
                other = await metadata_store.get_memory(other_id)
                if other and text_overlap(memory.content, other.content) < 0.3:
                    report.contradictions_flagged += 1
                    report.details.append(
                        f"Possible contradiction: {memory.id[:8]}... "
                        f"({memory.source.platform.value}) "
                        f"vs {other_id[:8]}... ({other_platform}) — "
                        f"similarity={score:.3f}"
                    )
