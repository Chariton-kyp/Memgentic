"""Prompt templates for the auto-dream consolidation pipeline.

Module-level constants follow the same convention as the prompts in
``intelligence.py`` — all phases ship a self-contained, few-shot prompt that
asks for structured Pydantic output.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase 2 — Gather Signal
# ---------------------------------------------------------------------------

GATHER_SIGNAL_SYSTEM = (
    "You are reviewing recent AI-assistant session transcripts to find "
    "high-signal patterns worth promoting into long-term memory. You are "
    "looking specifically for:\n"
    "  - corrections: places where the user pushed back on or fixed an "
    "    assistant claim\n"
    "  - preference_changes: places where the user established or changed "
    "    a convention, style, or workflow preference\n"
    "  - recurring_patterns: behaviors, mistakes, or workflows that repeat "
    "    across sessions and deserve a single canonical entry\n"
    "  - decisions_with_dates: explicit decisions that ought to carry an "
    "    absolute date stamp instead of a relative one"
)

GATHER_SIGNAL_USER_TEMPLATE = (
    "Today's date is {today}. Review these {n_sessions} session summaries "
    "for project '{project}'. For each item you surface, be concrete and "
    "cite the underlying behavior so the user can verify it.\n\n"
    "If a fact is dated relatively ('yesterday', 'last week'), resolve it "
    "into an absolute YYYY-MM-DD date in 'decisions_with_dates' using "
    "today's date as the anchor.\n\n"
    "Sessions:\n{sessions_block}\n\n"
    "Return a JSON object matching the SignalReport schema. Be terse — "
    "fewer high-quality items beats a long noisy list."
)

# ---------------------------------------------------------------------------
# Phase 3 — Consolidate (patch generation)
# ---------------------------------------------------------------------------

CONSOLIDATE_SYSTEM = (
    "You are auditing a personal AI-memory store. Your job is to propose "
    "concrete patches that improve quality without losing information. "
    "You are NOT allowed to mutate the live store directly — you only "
    "propose patches that the user will review.\n\n"
    "Patch actions you may produce:\n"
    "  - merge: two or more memory rows say the same thing; keep the most "
    "    canonical (highest confidence, most precise wording) and mark "
    "    the others as superseded.\n"
    "  - supersede: a newer memory contradicts/replaces an older one; the "
    "    newer fact wins, the older becomes superseded.\n"
    "  - archive_stale: a memory references something that no longer "
    "    exists (deleted file, abandoned plan, retracted decision) and "
    "    should be hidden from default recall.\n"
    "  - normalize_date: a memory contains a relative date ('yesterday', "
    "    'last sprint'); produce a chronograph triple with valid_from "
    "    set to the absolute date. NEVER edit the original content text.\n"
    "  - insert_insight: surface a recurring pattern that deserves its own "
    "    high-signal memory. Cite the supporting memory ids in "
    "    target_memory_ids.\n"
    "  - update_field: tighten topics/entities/metadata on a single "
    "    memory. NEVER touch raw content (preserve provenance).\n\n"
    "RULES:\n"
    "  1. Be conservative — when in doubt, do nothing. The cost of a wrong "
    "     patch is higher than the cost of leaving noise.\n"
    "  2. Every patch must include `evidence` explaining WHY it is safe.\n"
    "  3. `target_memory_ids` must reference ids from the cluster you "
    "     were given. Do not invent ids.\n"
    "  4. Prefer `update_field` over `merge` when only metadata is wrong."
)

CONSOLIDATE_USER_TEMPLATE = (
    "Today's date is {today}. You are consolidating memories for project "
    "'{project}'.\n\n"
    "Inventory:\n"
    "  - active memories: {n_memories}\n"
    "  - source breakdown: {source_breakdown}\n"
    "  - content type breakdown: {content_type_breakdown}\n\n"
    "Signal report from recent sessions:\n{signal_block}\n\n"
    "Memory cluster under review (id, source, created_at, content):\n"
    "{cluster_block}\n\n"
    "Cosine similarity hints (id_a, id_b, score) — these are HINTS, not "
    "ground truth. The LLM decides whether to merge:\n"
    "{similarity_hints}\n\n"
    "User instructions: {instructions}\n\n"
    "Return a PatchSet (a JSON object with a `patches` array). Each patch "
    "must include `action`, `target_memory_ids`, `evidence`, and any "
    "fields required by that action. Empty patches array is acceptable."
)
