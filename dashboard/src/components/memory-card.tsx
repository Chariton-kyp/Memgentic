"use client";

import { useState } from "react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { Star, Archive, FolderPlus } from "lucide-react";
import { toast } from "sonner";
import { getPlatformConfig, getContentTypeConfig } from "@/lib/constants";
import { usePinMemory, useUnpinMemory } from "@/hooks/use-memories";
import { useCollections, useAddToCollection } from "@/hooks/use-collections";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { updateMemory } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import type { Memory } from "@/lib/types";

function ConfidenceDot({ confidence }: { confidence: number }) {
  const color =
    confidence >= 0.8
      ? "bg-green-500"
      : confidence >= 0.5
        ? "bg-yellow-500"
        : "bg-red-500";
  return (
    <span
      className={`inline-block size-2 rounded-full ${color}`}
      title={`${(confidence * 100).toFixed(0)}% confidence`}
    />
  );
}

export function MemoryCard({ memory }: { memory: Memory }) {
  const [hovered, setHovered] = useState(false);
  const platform = getPlatformConfig(memory.platform);
  const contentType = getContentTypeConfig(memory.content_type);
  const pinMutation = usePinMemory();
  const unpinMutation = useUnpinMemory();
  const { data: collectionsData } = useCollections();
  const addToCollection = useAddToCollection();

  const handlePin = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (memory.is_pinned) {
      unpinMutation.mutate(memory.id, {
        onSuccess: () => toast.success("Memory unpinned"),
      });
    } else {
      pinMutation.mutate(memory.id, {
        onSuccess: () => toast.success("Memory pinned"),
      });
    }
  };

  const handleArchive = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await updateMemory(memory.id, { status: "archived" });
      toast.success("Memory archived");
    } catch {
      toast.error("Failed to archive memory");
    }
  };

  const handleAddToCollection = (collectionId: string | null) => {
    if (!collectionId) return;
    addToCollection.mutate(
      { collectionId, memoryId: memory.id },
      {
        onSuccess: () => toast.success("Added to collection"),
        onError: () => toast.error("Failed to add to collection"),
      }
    );
  };

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="relative"
    >
      <Link href={`/memories/${memory.id}`}>
        <Card className="transition-colors hover:bg-muted/50">
          <CardContent className="p-4 space-y-3">
            {/* Source badge + time row */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ConfidenceDot confidence={memory.confidence} />
                <Badge
                  variant="secondary"
                  className={platform.bgColor}
                  style={{ borderColor: platform.color }}
                >
                  {platform.label}
                </Badge>
              </div>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(memory.created_at), {
                  addSuffix: true,
                })}
              </span>
            </div>

            {/* Content preview */}
            <p className="text-sm leading-relaxed line-clamp-3">
              {memory.content.slice(0, 300)}
              {memory.content.length > 300 ? "..." : ""}
            </p>

            {/* Topics + content type */}
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{contentType.label}</Badge>
              {memory.topics.slice(0, 3).map((topic) => (
                <Badge key={topic} variant="secondary" className="text-xs">
                  {topic}
                </Badge>
              ))}
              {memory.topics.length > 3 && (
                <span className="text-xs text-muted-foreground">
                  +{memory.topics.length - 3} more
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      </Link>

      {/* Hover actions */}
      {hovered && (
        <div className="absolute top-2 right-2 flex items-center gap-1 z-10">
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={handlePin}
            className={memory.is_pinned ? "text-yellow-500" : "text-muted-foreground"}
            title={memory.is_pinned ? "Unpin" : "Pin"}
          >
            <Star className={`size-3.5 ${memory.is_pinned ? "fill-current" : ""}`} />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={handleArchive}
            title="Archive"
            className="text-muted-foreground"
          >
            <Archive className="size-3.5" />
          </Button>
          {collectionsData && collectionsData.collections.length > 0 && (
            <div onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
              <Select onValueChange={handleAddToCollection}>
                <SelectTrigger className="h-6 w-6 border-none p-0 [&_svg]:hidden" aria-label="Add to collection">
                  <FolderPlus className="size-3.5 text-muted-foreground" />
                </SelectTrigger>
                <SelectContent>
                  {collectionsData.collections.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      <span
                        className="inline-block size-2 rounded-full mr-1"
                        style={{ backgroundColor: c.color || "#6B7280" }}
                      />
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function MemoryCardSkeleton() {
  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-3 w-16" />
        </div>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <div className="flex gap-2">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-20" />
        </div>
      </CardContent>
    </Card>
  );
}
