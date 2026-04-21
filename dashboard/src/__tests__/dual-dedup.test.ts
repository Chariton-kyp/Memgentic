import { describe, it, expect } from "vitest";
import type { Memory, SourceMetadata } from "../lib/types";
import { dedupDualMemories, findDualSibling } from "../lib/capture-profile";

const baseSource: SourceMetadata = {
  platform: "claude_code",
  platform_version: null,
  session_id: null,
  session_title: null,
  capture_method: "mcp_tool",
  original_timestamp: null,
  file_path: null,
};

function mem(overrides: Partial<Memory>): Memory {
  return {
    id: "id",
    content: "content",
    content_type: "fact",
    platform: "claude_code",
    topics: [],
    entities: [],
    confidence: 1,
    status: "active",
    is_pinned: false,
    pinned_at: null,
    created_at: "2026-04-21T00:00:00Z",
    last_accessed: null,
    access_count: 0,
    source: baseSource,
    ...overrides,
  };
}

describe("dedupDualMemories", () => {
  it("keeps non-dual memories untouched", () => {
    const list = [
      mem({ id: "a", capture_profile: "enriched" }),
      mem({ id: "b", capture_profile: "raw" }),
    ];
    expect(dedupDualMemories(list)).toEqual(list);
  });

  it("collapses a paired dual set to the enriched primary", () => {
    const enriched = mem({
      id: "enriched-1",
      capture_profile: "dual",
      dual_sibling_id: "raw-1",
      topics: ["qdrant"],
    });
    const raw = mem({
      id: "raw-1",
      capture_profile: "dual",
      dual_sibling_id: "enriched-1",
      topics: [],
    });
    const result = dedupDualMemories([enriched, raw]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("enriched-1");
  });

  it("keeps an unpaired dual sibling so content stays reachable", () => {
    const orphan = mem({
      id: "orphan",
      capture_profile: "dual",
      dual_sibling_id: "missing",
      topics: [],
    });
    const result = dedupDualMemories([orphan]);
    expect(result).toEqual([orphan]);
  });

  it("works when the list is ordered raw-first", () => {
    const raw = mem({
      id: "raw-2",
      capture_profile: "dual",
      dual_sibling_id: "enriched-2",
      topics: [],
    });
    const enriched = mem({
      id: "enriched-2",
      capture_profile: "dual",
      dual_sibling_id: "raw-2",
      topics: ["topic"],
    });
    const result = dedupDualMemories([raw, enriched]);
    expect(result.map((m) => m.id)).toEqual(["enriched-2"]);
  });
});

describe("findDualSibling", () => {
  it("returns the sibling when present", () => {
    const a = mem({ id: "a", capture_profile: "dual", dual_sibling_id: "b" });
    const b = mem({ id: "b", capture_profile: "dual", dual_sibling_id: "a" });
    expect(findDualSibling(a, [a, b])?.id).toBe("b");
  });

  it("returns undefined for non-dual memories", () => {
    const lone = mem({ id: "lone", capture_profile: "enriched" });
    expect(findDualSibling(lone, [lone])).toBeUndefined();
  });
});
