"use client";

import { useState, useMemo } from "react";
import { useMemories } from "@/hooks/use-memories";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { getPlatformConfig, getContentTypeConfig } from "@/lib/constants";
import { format, formatDistanceToNow, parseISO } from "date-fns";
import { Clock, ChevronLeft, ChevronRight } from "lucide-react";
import type { Memory } from "@/lib/types";

function groupByDate(memories: Memory[]): Record<string, Memory[]> {
  const groups: Record<string, Memory[]> = {};
  for (const memory of memories) {
    const dateKey = format(parseISO(memory.created_at), "yyyy-MM-dd");
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(memory);
  }
  return groups;
}

export default function TimelinePage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, error } = useMemories({ page, page_size: 50 });

  const grouped = useMemo(() => {
    if (!data?.memories) return {};
    return groupByDate(data.memories);
  }, [data?.memories]);

  const dateKeys = useMemo(
    () => Object.keys(grouped).sort((a, b) => b.localeCompare(a)),
    [grouped]
  );

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-3">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-center text-destructive">
        Failed to load timeline: {(error as Error).message}
      </div>
    );
  }

  if (!data || data.memories.length === 0) {
    return (
      <div className="p-6">
        <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
          <Clock className="size-12 text-muted-foreground" />
          <div>
            <h2 className="text-lg font-semibold">No memories yet</h2>
            <p className="text-sm text-muted-foreground">
              Memories will appear here as they are ingested.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Timeline</h1>
        <span className="text-sm text-muted-foreground">
          {data.total} memories
        </span>
      </div>

      {/* Vertical Timeline */}
      <div className="relative space-y-8">
        {/* Vertical line */}
        <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />

        {dateKeys.map((dateKey) => {
          const dateLabel = format(parseISO(dateKey), "EEEE, MMMM d, yyyy");
          const memories = grouped[dateKey];

          return (
            <div key={dateKey} className="relative pl-10">
              {/* Date dot */}
              <div className="absolute left-2.5 top-1 size-3 rounded-full bg-primary" />

              {/* Date header */}
              <h2 className="sticky top-0 z-10 bg-background pb-3 text-sm font-bold text-foreground">
                {dateLabel}
              </h2>

              <div className="space-y-3">
                {memories.map((memory) => {
                  const platform = getPlatformConfig(memory.platform);
                  const contentType = getContentTypeConfig(memory.content_type);
                  const preview =
                    memory.content.length > 100
                      ? memory.content.slice(0, 100) + "..."
                      : memory.content;

                  return (
                    <div
                      key={memory.id}
                      className="rounded-lg border bg-card p-4 text-card-foreground shadow-sm"
                    >
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span
                          className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${platform.bgColor}`}
                          style={{ color: platform.color }}
                        >
                          {platform.label}
                        </span>
                        <Badge variant="secondary">{contentType.label}</Badge>
                        {memory.source.session_title && (
                          <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                            {memory.source.session_title}
                          </span>
                        )}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {formatDistanceToNow(parseISO(memory.created_at), {
                            addSuffix: true,
                          })}
                        </span>
                      </div>
                      <p className="text-sm text-foreground/80">{preview}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4 pt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            <ChevronLeft className="size-4" />
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Next
            <ChevronRight className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
