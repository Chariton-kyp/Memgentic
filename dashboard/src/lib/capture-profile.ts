/**
 * Client-side helpers for the capture-profile feature.
 *
 * Dual-profile memories store two rows per chunk (raw + enriched, paired
 * via ``dual_sibling_id``). For memory grids / lists we want to collapse
 * the pair to a single "primary" (enriched) entry with the raw sibling
 * available on demand — anything else just shows the same content twice.
 */

import type { Memory } from "./types";

/**
 * Remove the raw sibling of every dual pair that also has its enriched
 * primary present. Non-dual memories (raw, enriched, unset) are untouched,
 * and raw dual siblings whose partner is missing stay in the list so the
 * user doesn't lose access to the content.
 *
 * In a dual pair both rows carry ``capture_profile === "dual"``. We identify
 * the "primary" (enriched side) as the one with non-empty topics/entities;
 * the pipeline always writes the raw sibling with empty metadata. The
 * primary is kept, the sibling dropped. If both rows happen to have empty
 * topics (no LLM provider configured), we fall back to keeping whichever
 * appears first — deterministic and still collapses the duplicate.
 */
export function dedupDualMemories(memories: Memory[]): Memory[] {
  const byId = new Map(memories.map((m) => [m.id, m]));
  const kept = new Set<string>();
  const result: Memory[] = [];

  for (const m of memories) {
    if (m.capture_profile !== "dual" || !m.dual_sibling_id) {
      result.push(m);
      continue;
    }
    if (kept.has(m.id)) {
      // Already emitted this memory as the primary of an earlier iteration.
      continue;
    }
    const sibling = byId.get(m.dual_sibling_id);
    if (!sibling) {
      // Unpaired — keep so the user doesn't lose access to the content.
      result.push(m);
      kept.add(m.id);
      continue;
    }

    const mHasTopics = m.topics.length > 0 || m.entities.length > 0;
    const sibHasTopics = sibling.topics.length > 0 || sibling.entities.length > 0;

    let primary: Memory;
    if (mHasTopics && !sibHasTopics) {
      primary = m;
    } else if (sibHasTopics && !mHasTopics) {
      primary = sibling;
    } else {
      // Both enriched or both raw — keep the one encountered first.
      primary = m;
    }

    if (!kept.has(primary.id)) {
      result.push(primary);
      kept.add(primary.id);
    }
    // Always mark the sibling as consumed so we don't re-emit it later.
    kept.add(primary === m ? sibling.id : m.id);
  }

  return result;
}

/** Locate the sibling of a dual memory inside a list, or undefined if absent. */
export function findDualSibling(
  memory: Memory,
  all: Memory[],
): Memory | undefined {
  if (!memory.dual_sibling_id) return undefined;
  return all.find((m) => m.id === memory.dual_sibling_id);
}
