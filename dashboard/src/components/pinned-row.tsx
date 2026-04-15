"use client";

import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { Star } from "lucide-react";
import { toast } from "sonner";
import { getPlatformConfig } from "@/lib/constants";
import { usePinnedMemories, useUnpinMemory } from "@/hooks/use-memories";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function PinnedRow() {
  const { data } = usePinnedMemories();
  const unpinMutation = useUnpinMemory();

  const pinnedMemories = data?.memories ?? [];

  if (pinnedMemories.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Star className="size-4 text-yellow-500 fill-yellow-500" />
        <h2 className="text-sm font-medium">Pinned</h2>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin">
        {pinnedMemories.map((memory) => {
          const platform = getPlatformConfig(memory.platform);
          return (
            <Link
              key={memory.id}
              href={`/memories/${memory.id}`}
              className="shrink-0"
            >
              <Card className="w-64 transition-colors hover:bg-muted/50">
                <CardContent className="p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <Badge
                      variant="secondary"
                      className={`text-[10px] ${platform.bgColor}`}
                      style={{ borderColor: platform.color }}
                    >
                      {platform.label}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className="text-yellow-500"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        unpinMutation.mutate(memory.id, {
                          onSuccess: () => toast.success("Memory unpinned"),
                        });
                      }}
                      title="Unpin"
                    >
                      <Star className="size-3 fill-current" />
                    </Button>
                  </div>
                  <p className="text-xs leading-relaxed line-clamp-2">
                    {memory.content.slice(0, 150)}
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {formatDistanceToNow(new Date(memory.created_at), {
                      addSuffix: true,
                    })}
                  </p>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
