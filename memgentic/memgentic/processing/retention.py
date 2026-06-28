"""Self-cleaning + retention (W4).

Two cooperating mechanisms keep the store from growing monotonically:

* ``run_clean`` — a one-time bulk archival pass over ACTIVE memories. It finds
  exact-duplicate clusters and obvious noise (the W1 capture-hygiene filters
  applied retroactively to already-stored rows), keeps the best of each cluster
  and **archives** (soft-deletes) the rest. Recoverable: the metadata row stays
  with ``status='archived'``; only its vector is dropped from recall.
* ``run_gc`` — the retention garbage collector. It **hard-deletes** rows that
  are already ``archived``/``superseded`` AND older than the configured grace
  period, removing both the SQLite row and its vector.

Absolute safety invariants (enforced here AND at the storage layer in
``MetadataStore.get_gc_candidates`` / ``hard_delete_memories``):

* a ``is_pinned=True`` memory is NEVER archived or hard-deleted;
* a ``capture_method='mcp_tool'`` memory (the owner's deliberate
  ``memgentic_remember`` saves) is NEVER archived or hard-deleted;
* GC never touches ``status='active'`` rows.

Both destructive entry points are dry-run by default — pass ``apply=True`` to
mutate.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from memgentic.models import CaptureMethod, Memory, MemoryStatus
from memgentic.processing.heuristics import is_noise

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Safety predicate — the single source of truth for "off-limits to cleaning"
# ---------------------------------------------------------------------------


def is_protected(memory: Memory) -> bool:
    """Return True when a memory must never be archived OR hard-deleted.

    The two absolute W4 safety rules: a pinned memory, or one captured via the
    MCP ``memgentic_remember`` tool (the owner's deliberate, highest-value
    saves). Used by every destructive path (clean, GC, reductive dream) so the
    rule lives in exactly one place.
    """
    return bool(memory.is_pinned) or memory.source.capture_method == CaptureMethod.MCP_TOOL


_WS_RE = re.compile(r"\s+")


def _normalize_content(content: str) -> str:
    """Case- and whitespace-insensitive key used to cluster exact duplicates."""
    return _WS_RE.sub(" ", (content or "").strip().lower())


def _keep_rank(memory: Memory) -> tuple[int, int, float, datetime]:
    """Best-of-cluster ranking key: pinned > mcp_tool > importance > newest."""
    return (
        1 if memory.is_pinned else 0,
        1 if memory.source.capture_method == CaptureMethod.MCP_TOOL else 0,
        memory.importance_score,
        memory.created_at,
    )


# ---------------------------------------------------------------------------
# Bulk clean — duplicate-cluster + noise archival planner
# ---------------------------------------------------------------------------


@dataclass
class CleanPlan:
    """What ``run_clean`` WOULD archive (computed, not yet applied)."""

    dup_clusters: int = 0
    dup_archive: list[Memory] = field(default_factory=list)
    noise_archive: list[Memory] = field(default_factory=list)
    preserved_pinned: int = 0
    preserved_mcp_tool: int = 0

    @property
    def archive_ids(self) -> list[str]:
        """De-duplicated list of memory ids this plan would archive."""
        seen: set[str] = set()
        out: list[str] = []
        for mem in (*self.dup_archive, *self.noise_archive):
            if mem.id not in seen:
                seen.add(mem.id)
                out.append(mem.id)
        return out

    @property
    def by_content_type(self) -> dict[str, int]:
        """Count of to-be-archived memories grouped by content_type."""
        counts: dict[str, int] = {}
        seen: set[str] = set()
        for mem in (*self.dup_archive, *self.noise_archive):
            if mem.id in seen:
                continue
            seen.add(mem.id)
            counts[mem.content_type.value] = counts.get(mem.content_type.value, 0) + 1
        return counts


def plan_clean(memories: list[Memory]) -> CleanPlan:
    """Decide which ACTIVE memories a bulk clean would archive.

    Duplicate clusters: rows sharing normalized content. The best row
    (pinned > mcp_tool > importance > newest) is kept; the other non-protected
    rows are archived. Pinned / mcp_tool duplicates are ALWAYS preserved.

    Noise: rows whose content matches the W1 noise / meta-prompt filters,
    again skipping pinned / mcp_tool rows.

    Pure function — performs no I/O, so it is trivially unit-testable.
    """
    plan = CleanPlan()
    active = [m for m in memories if m.status == MemoryStatus.ACTIVE]

    # --- duplicate clusters ---
    groups: dict[str, list[Memory]] = {}
    for mem in active:
        groups.setdefault(_normalize_content(mem.content), []).append(mem)

    archived_ids: set[str] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        plan.dup_clusters += 1
        best = max(group, key=_keep_rank)
        for mem in group:
            if mem.id == best.id:
                continue
            if is_protected(mem):
                if mem.is_pinned:
                    plan.preserved_pinned += 1
                else:
                    plan.preserved_mcp_tool += 1
                continue
            plan.dup_archive.append(mem)
            archived_ids.add(mem.id)

    # --- noise (W1 filters applied retroactively) ---
    for mem in active:
        if mem.id in archived_ids or is_protected(mem):
            continue
        if is_noise(mem.content):
            plan.noise_archive.append(mem)

    return plan


@dataclass
class CleanReport:
    """Outcome of a ``run_clean`` invocation (dry-run or applied)."""

    dup_clusters: int = 0
    dup_archived: int = 0
    noise_archived: int = 0
    preserved_pinned: int = 0
    preserved_mcp_tool: int = 0
    total_archived: int = 0
    applied: bool = False
    by_content_type: dict[str, int] = field(default_factory=dict)
    archived_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def _load_active(metadata_store: Any, *, limit: int, user_id: str) -> list[Memory]:
    """Page through ACTIVE memories (``get_memories_by_filter`` is active-only)."""
    out: list[Memory] = []
    offset = 0
    page = 1000
    while len(out) < limit:
        want = min(page, limit - len(out))
        batch = await metadata_store.get_memories_by_filter(
            limit=want, offset=offset, user_id=user_id
        )
        if not batch:
            break
        out.extend(batch)
        if len(batch) < want:
            break
        offset += len(batch)
    return out


async def run_clean(
    *,
    metadata_store: Any,
    vector_store: Any | None = None,
    apply: bool = False,
    limit: int = 50_000,
    user_id: str = "",
) -> CleanReport:
    """Plan (and optionally apply) the bulk duplicate/noise archival.

    Dry-run by default: returns a report describing what WOULD be archived
    without mutating anything. With ``apply=True``, each planned id is
    soft-deleted (``status='archived'``) and its vector dropped from recall —
    pinned / mcp_tool rows are never touched (enforced by ``plan_clean``). Hard
    deletion is deferred to ``run_gc`` after the grace period, so a clean stays
    fully recoverable.
    """
    memories = await _load_active(metadata_store, limit=limit, user_id=user_id)
    plan = plan_clean(memories)
    archive_ids = plan.archive_ids
    report = CleanReport(
        dup_clusters=plan.dup_clusters,
        dup_archived=len(plan.dup_archive),
        noise_archived=len(plan.noise_archive),
        preserved_pinned=plan.preserved_pinned,
        preserved_mcp_tool=plan.preserved_mcp_tool,
        total_archived=len(archive_ids),
        applied=apply,
        by_content_type=plan.by_content_type,
        archived_ids=archive_ids,
    )
    if not apply or not archive_ids:
        return report

    for mid in archive_ids:
        try:
            await metadata_store.update_memory_status(
                mid, MemoryStatus.ARCHIVED.value, user_id=user_id
            )
            if vector_store is not None:
                with contextlib.suppress(Exception):
                    await vector_store.delete_memory(mid)
        except Exception as exc:
            report.errors.append(f"archive {mid[:8]}: {exc}")
    logger.info(
        "retention.clean",
        dup_archived=report.dup_archived,
        noise_archived=report.noise_archived,
        preserved_pinned=report.preserved_pinned,
        preserved_mcp_tool=report.preserved_mcp_tool,
        applied=apply,
    )
    return report


# ---------------------------------------------------------------------------
# Garbage collection — hard-delete expired archived/superseded rows
# ---------------------------------------------------------------------------


@dataclass
class GCReport:
    """Outcome of a ``run_gc`` invocation (dry-run or applied)."""

    grace_days: int
    cutoff_iso: str
    candidates: int = 0
    hard_deleted: int = 0
    vectors_deleted: int = 0
    applied: bool = False
    disabled: bool = False
    deleted_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def run_gc(
    *,
    metadata_store: Any,
    settings: Any,
    vector_store: Any | None = None,
    apply: bool = False,
    limit: int = 10_000,
    user_id: str = "",
) -> GCReport:
    """Hard-delete archived/superseded memories past the retention grace period.

    Dry-run by default — returns the candidate set without mutating. With
    ``apply=True`` each candidate's vector is removed first, then the SQLite row
    is hard-deleted. ``settings.hard_delete_archived_after_days <= 0`` disables
    GC entirely (returns ``disabled=True``). Pinned / mcp_tool / active rows are
    never candidates (filtered in SQL and re-checked here as defense in depth).
    """
    grace = int(getattr(settings, "hard_delete_archived_after_days", 0))
    if grace <= 0:
        return GCReport(grace_days=grace, cutoff_iso="", applied=apply, disabled=True)

    cutoff = datetime.now(UTC) - timedelta(days=grace)
    cutoff_iso = cutoff.isoformat()
    candidates = await metadata_store.get_gc_candidates(
        before_iso=cutoff_iso, limit=limit, user_id=user_id
    )
    # Defense in depth: the SQL already excludes pinned / mcp_tool / active, but
    # re-assert the invariants in Python so no future query regression can leak
    # a protected row into a hard delete.
    safe = [
        m
        for m in candidates
        if m.status in (MemoryStatus.ARCHIVED, MemoryStatus.SUPERSEDED) and not is_protected(m)
    ]
    report = GCReport(
        grace_days=grace,
        cutoff_iso=cutoff_iso,
        candidates=len(safe),
        applied=apply,
        deleted_ids=[m.id for m in safe],
    )
    if not apply or not safe:
        return report

    if vector_store is not None:
        for mem in safe:
            try:
                await vector_store.delete_memory(mem.id)
                report.vectors_deleted += 1
            except Exception as exc:
                report.errors.append(f"vector {mem.id[:8]}: {exc}")

    report.hard_deleted = await metadata_store.hard_delete_memories([m.id for m in safe])
    logger.info(
        "retention.gc",
        grace_days=grace,
        candidates=len(safe),
        hard_deleted=report.hard_deleted,
        vectors_deleted=report.vectors_deleted,
    )
    return report


__all__ = [
    "CleanPlan",
    "CleanReport",
    "GCReport",
    "is_protected",
    "plan_clean",
    "run_clean",
    "run_gc",
]
