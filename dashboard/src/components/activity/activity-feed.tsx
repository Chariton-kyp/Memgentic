"use client";

import { formatDistanceToNow } from "date-fns";
import { Brain, Pin, Sparkles, Upload, Pencil, Trash2 } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { useActivityStore } from "@/stores/activity-store";
import type { ActivityEvent } from "@/lib/types";

interface ActivityFeedProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function getEventIcon(type: ActivityEvent["type"]) {
  switch (type) {
    case "memory:created":
      return <Brain className="size-4 text-blue-500" />;
    case "memory:pinned":
      return <Pin className="size-4 text-amber-500" />;
    case "memory:updated":
      return <Pencil className="size-4 text-green-500" />;
    case "memory:deleted":
      return <Trash2 className="size-4 text-red-500" />;
    case "skill:created":
      return <Sparkles className="size-4 text-purple-500" />;
    case "skill:updated":
      return <Pencil className="size-4 text-green-500" />;
    case "skill:deleted":
      return <Trash2 className="size-4 text-red-500" />;
    case "ingestion:progress":
      return <Upload className="size-4 text-cyan-500" />;
    default:
      return <Brain className="size-4 text-muted-foreground" />;
  }
}

function getEventDescription(event: ActivityEvent): string {
  const data = event.data;
  switch (event.type) {
    case "memory:created": {
      const content = typeof data?.content === "string" ? data.content.slice(0, 60) : "";
      return content ? `Memory captured: ${content}...` : "New memory captured";
    }
    case "memory:updated":
      return "Memory updated";
    case "memory:deleted":
      return "Memory deleted";
    case "memory:pinned":
      return "Memory pinned";
    case "skill:created": {
      const name = typeof data?.name === "string" ? data.name : "";
      return name ? `Skill created: ${name}` : "New skill created";
    }
    case "skill:updated": {
      const name = typeof data?.name === "string" ? data.name : "";
      return name ? `Skill updated: ${name}` : "Skill updated";
    }
    case "skill:deleted": {
      const name = typeof data?.name === "string" ? data.name : "";
      return name ? `Skill deleted: ${name}` : "Skill deleted";
    }
    case "ingestion:progress":
      return "Import in progress";
    default:
      return "Activity event";
  }
}

export function ActivityFeed({ open, onOpenChange }: ActivityFeedProps) {
  const events = useActivityStore((s) => s.events);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>Activity</SheetTitle>
          <SheetDescription>Recent events across your workspace</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          {events.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Brain className="size-8 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">
                No recent activity
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Events will appear here as you use Memgentic.
              </p>
            </div>
          ) : (
            <div className="space-y-1">
              {events.map((event, index) => (
                <div
                  key={`${event.type}-${event.timestamp}-${index}`}
                  className="flex items-start gap-3 rounded-md p-2 hover:bg-muted/50 transition-colors"
                >
                  <div className="mt-0.5 shrink-0">
                    {getEventIcon(event.type)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">{getEventDescription(event)}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {formatDistanceToNow(new Date(event.timestamp), {
                        addSuffix: true,
                      })}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
