"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Search,
  Brain,
  ChevronLeft,
  ChevronRight,
  X,
  Plus,
  Zap,
  Archive,
} from "lucide-react";
import {
  useMemories,
  useSearch,
  useSources,
  usePinnedMemories,
} from "@/hooks/use-memories";
import {
  useCollectionMemories,
} from "@/hooks/use-collections";
import { CONTENT_TYPE_CONFIG } from "@/lib/constants";
import { batchUpdateMemories } from "@/lib/api";
import { useDashboardStore } from "@/stores/dashboard-store";
import { useActivityStore } from "@/stores/activity-store";
import { Header } from "@/components/layout/header";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MemoryCard, MemoryCardSkeleton } from "@/components/memory-card";
import { PinnedRow } from "@/components/pinned-row";
import { CollectionsSidebar } from "@/components/collections/collections-sidebar";
import { UploadModal } from "@/components/upload/upload-modal";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import type { Memory } from "@/lib/types";

function BatchActionBar({
  count,
  onArchive,
  onClear,
  archiving,
}: {
  count: number;
  onArchive: () => void;
  onClear: () => void;
  archiving: boolean;
}) {
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
      <div className="flex items-center gap-3 rounded-xl border bg-popover px-4 py-3 shadow-xl ring-1 ring-foreground/10">
        <span className="text-sm font-medium">
          {count} selected
        </span>
        <Button size="sm" variant="outline" onClick={onArchive} disabled={archiving}>
          <Archive className="size-3.5 mr-1" />
          {archiving ? "Archiving..." : "Archive Selected"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClear}>
          <X className="size-3.5 mr-1" />
          Clear
        </Button>
      </div>
    </div>
  );
}

export default function HomePage() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [sourceFilter, setSourceFilter] = useState<string | undefined>();
  const [contentTypeFilter, setContentTypeFilter] = useState<
    string | undefined
  >();
  const [activeView, setActiveView] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [lastSelectedId, setLastSelectedId] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const pageSize = 20;
  const queryClient = useQueryClient();

  const { uploadModalOpen, setUploadModalOpen } = useDashboardStore();
  const todayCount = useActivityStore((s) => s.todayCount);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Reset page when search or filters change
  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, sourceFilter, contentTypeFilter, activeView]);

  const isSearching = debouncedQuery.length >= 2;
  const isPinnedView = activeView === "pinned";
  const isCollectionView =
    activeView !== null && activeView !== "pinned";

  // Prefetch sources so the sidebar / filters hydrate before first user
  // interaction. The dashboard doesn't read the return value here — the
  // sidebar subscribes through its own ``useSources()`` call — but keeping
  // the prefetch warm avoids a flicker on first filter open.
  useSources();

  const {
    data: memoriesData,
    isLoading: memoriesLoading,
    error: memoriesError,
  } = useMemories({
    page,
    page_size: pageSize,
    source: sourceFilter,
    content_type: contentTypeFilter,
  });

  const {
    data: searchData,
    isLoading: searchLoading,
    error: searchError,
  } = useSearch(debouncedQuery, {
    ...(sourceFilter ? { sources: [sourceFilter] } : {}),
    ...(contentTypeFilter ? { content_types: [contentTypeFilter] } : {}),
  });

  const { data: pinnedData, isLoading: pinnedLoading } = usePinnedMemories();

  const {
    data: collectionMemoriesData,
    isLoading: collectionLoading,
  } = useCollectionMemories(
    isCollectionView ? activeView : null,
    { page, page_size: pageSize }
  );

  // Determine which data to show
  let isLoading: boolean;
  let error: Error | null;
  let memories: Memory[];
  let total: number;

  if (isSearching) {
    isLoading = searchLoading;
    error = searchError as Error | null;
    memories = searchData?.results.map((r) => r.memory) ?? [];
    total = searchData?.total ?? 0;
  } else if (isPinnedView) {
    isLoading = pinnedLoading;
    error = null;
    memories = pinnedData?.memories ?? [];
    total = pinnedData?.total ?? 0;
  } else if (isCollectionView) {
    isLoading = collectionLoading;
    error = null;
    memories = collectionMemoriesData?.memories ?? [];
    total = collectionMemoriesData?.total ?? 0;
  } else {
    isLoading = memoriesLoading;
    error = memoriesError as Error | null;
    memories = memoriesData?.memories ?? [];
    total = memoriesData?.total ?? 0;
  }

  const totalPages = Math.ceil(total / pageSize);
  const batchMode = selectedIds.size > 0;

  const handleToggleSelect = useCallback(
    (id: string, shiftKey: boolean) => {
      setSelectedIds((prev) => {
        const next = new Set(prev);

        if (shiftKey && lastSelectedId && memories.length > 0) {
          // Range selection
          const lastIdx = memories.findIndex((m) => m.id === lastSelectedId);
          const currentIdx = memories.findIndex((m) => m.id === id);
          if (lastIdx !== -1 && currentIdx !== -1) {
            const start = Math.min(lastIdx, currentIdx);
            const end = Math.max(lastIdx, currentIdx);
            for (let i = start; i <= end; i++) {
              next.add(memories[i].id);
            }
          } else {
            if (next.has(id)) next.delete(id);
            else next.add(id);
          }
        } else {
          if (next.has(id)) next.delete(id);
          else next.add(id);
        }

        return next;
      });
      setLastSelectedId(id);
    },
    [lastSelectedId, memories]
  );

  const handleBatchArchive = async () => {
    if (selectedIds.size === 0) return;
    setArchiving(true);
    try {
      await batchUpdateMemories(Array.from(selectedIds), { status: "archived" });
      toast.success(`Archived ${selectedIds.size} memories`);
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    } catch (err) {
      toast.error("Failed to archive", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setArchiving(false);
    }
  };

  return (
    <>
      <Header title="Memories">
        <Button
          variant="default"
          size="sm"
          onClick={() => setUploadModalOpen(true)}
        >
          <Plus className="size-4 mr-1" />
          Add Knowledge
        </Button>
        {todayCount > 0 && (
          <Badge variant="secondary" className="gap-1">
            <Zap className="size-3" />
            {todayCount} today
          </Badge>
        )}
      </Header>
      <div className="flex-1 flex">
        {/* Collections sidebar */}
        <div className="p-4">
          <CollectionsSidebar
            activeView={activeView}
            onViewChange={setActiveView}
            activeSource={sourceFilter}
            onSourceChange={(source) => {
              setSourceFilter(source);
              setContentTypeFilter(undefined);
            }}
          />
        </div>

        {/* Main area */}
        <div className="flex-1 p-6 space-y-6 min-w-0">
          {/* Search bar + filters */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="relative flex-1 max-w-xl" role="search">
              <Search
                className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                placeholder="Search memories..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-10"
                aria-label="Search memories"
              />
            </div>

            <div
              className="flex flex-wrap items-center gap-2"
              role="group"
              aria-label="Filters"
            >
              <Select
                value={contentTypeFilter ?? "all"}
                onValueChange={(v) =>
                  setContentTypeFilter(!v || v === "all" ? undefined : v)
                }
              >
                <SelectTrigger
                  className="w-[160px]"
                  aria-label="Filter by content type"
                >
                  <SelectValue placeholder="All Types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  {Object.entries(CONTENT_TYPE_CONFIG).map(([key, cfg]) => (
                    <SelectItem key={key} value={key}>
                      {cfg.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {(sourceFilter || contentTypeFilter) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSourceFilter(undefined);
                    setContentTypeFilter(undefined);
                    setActiveView(null);
                  }}
                >
                  <X className="size-3 mr-1" />
                  Clear filters
                </Button>
              )}
            </div>
          </div>

          {/* Pinned row (only in default "All Memories" view) */}
          {activeView === null && !isSearching && <PinnedRow />}

          {/* Batch selection hint */}
          {!batchMode && !isSearching && memories.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Hold Shift and click to select multiple memories for batch actions.
            </p>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
              Failed to load memories: {error.message}
            </div>
          )}

          {/* Loading */}
          {isLoading && (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <MemoryCardSkeleton key={i} />
              ))}
            </div>
          )}

          {/* Results */}
          {!isLoading && !error && memories.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Brain className="size-12 text-muted-foreground mb-4" />
              <h2 className="text-lg font-semibold">No memories yet</h2>
              <p className="text-sm text-muted-foreground mt-1">
                {isSearching
                  ? "No memories match your search."
                  : isPinnedView
                    ? "No pinned memories. Star a memory to pin it."
                    : "Start capturing knowledge to see it here."}
              </p>
              {!isSearching && !isPinnedView && (
                <Button
                  variant="outline"
                  className="mt-4"
                  onClick={() => setUploadModalOpen(true)}
                >
                  <Plus className="size-4 mr-1" />
                  Add your first memory
                </Button>
              )}
            </div>
          )}

          {!isLoading && !error && memories.length > 0 && (
            <>
              {isSearching && (
                <p className="text-sm text-muted-foreground">
                  {total} result{total !== 1 ? "s" : ""} for &ldquo;
                  {debouncedQuery}&rdquo;
                </p>
              )}

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {memories.map((memory) => (
                  <div
                    key={memory.id}
                    className="relative group"
                    onClick={(e) => {
                      if (e.shiftKey) {
                        e.preventDefault();
                        handleToggleSelect(memory.id, true);
                      }
                    }}
                  >
                    {batchMode && (
                      <div className="absolute left-2 top-2 z-10">
                        <Checkbox
                          checked={selectedIds.has(memory.id)}
                          onCheckedChange={() => handleToggleSelect(memory.id, false)}
                          aria-label={`Select memory`}
                        />
                      </div>
                    )}
                    <div className={selectedIds.has(memory.id) ? "ring-2 ring-primary rounded-xl" : ""}>
                      <MemoryCard memory={memory} />
                    </div>
                  </div>
                ))}
              </div>

              {/* Pagination */}
              {!isSearching && totalPages > 1 && (
                <nav
                  className="flex items-center justify-center gap-4 pt-4"
                  aria-label="Pagination"
                >
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                  >
                    <ChevronLeft className="size-4 mr-1" />
                    Previous
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    Page {page} of {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setPage((p) => Math.min(totalPages, p + 1))
                    }
                    disabled={page >= totalPages}
                  >
                    Next
                    <ChevronRight className="size-4 ml-1" />
                  </Button>
                </nav>
              )}
            </>
          )}
        </div>
      </div>

      {/* Upload modal */}
      <UploadModal
        open={uploadModalOpen}
        onOpenChange={setUploadModalOpen}
      />

      {/* Batch action bar */}
      {batchMode && (
        <BatchActionBar
          count={selectedIds.size}
          onArchive={handleBatchArchive}
          onClear={() => setSelectedIds(new Set())}
          archiving={archiving}
        />
      )}
    </>
  );
}
