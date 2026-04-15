"use client";

import { useState } from "react";
import {
  Brain,
  Star,
  Plus,
  FolderOpen,
} from "lucide-react";
import { toast } from "sonner";
import { getPlatformConfig } from "@/lib/constants";
import { useSources } from "@/hooks/use-memories";
import { useCollections, useCreateCollection } from "@/hooks/use-collections";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogTrigger,
} from "@/components/ui/dialog";

const COLLECTION_COLORS = [
  "#EF4444",
  "#F97316",
  "#EAB308",
  "#22C55E",
  "#3B82F6",
  "#8B5CF6",
  "#EC4899",
  "#6B7280",
];

function CreateCollectionDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(COLLECTION_COLORS[0]);
  const createMutation = useCreateCollection();

  const handleCreate = () => {
    if (!name.trim()) return;
    createMutation.mutate(
      { name: name.trim(), description: description.trim(), color },
      {
        onSuccess: () => {
          toast.success("Collection created");
          setName("");
          setDescription("");
          setColor(COLLECTION_COLORS[0]);
          setOpen(false);
        },
        onError: () => toast.error("Failed to create collection"),
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <button className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
            <Plus className="size-4" />
            <span>Create Collection</span>
          </button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create Collection</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <label className="text-sm font-medium">Name</label>
            <Input
              placeholder="e.g., Project Alpha"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Description</label>
            <Input
              placeholder="Optional description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Color</label>
            <div className="flex gap-2">
              {COLLECTION_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className={`size-6 rounded-full transition-all ${
                    color === c ? "ring-2 ring-ring ring-offset-2" : ""
                  }`}
                  style={{ backgroundColor: c }}
                  aria-label={`Color ${c}`}
                />
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={handleCreate}
            disabled={!name.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? "Creating..." : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface CollectionsSidebarProps {
  activeView: string | null; // null = all, "pinned", or collection ID
  onViewChange: (view: string | null) => void;
  activeSource: string | undefined;
  onSourceChange: (source: string | undefined) => void;
}

export function CollectionsSidebar({
  activeView,
  onViewChange,
  activeSource,
  onSourceChange,
}: CollectionsSidebarProps) {
  const { data: collectionsData } = useCollections();
  const { data: sourcesData } = useSources();

  const collections = collectionsData?.collections ?? [];
  const sources = sourcesData?.sources ?? [];

  return (
    <aside className="w-56 shrink-0 space-y-1 pr-4 border-r hidden lg:block">
      {/* All Memories */}
      <button
        onClick={() => {
          onViewChange(null);
          onSourceChange(undefined);
        }}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
          activeView === null && !activeSource
            ? "bg-muted font-medium text-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        }`}
      >
        <Brain className="size-4" />
        <span>All Memories</span>
      </button>

      {/* Pinned */}
      <button
        onClick={() => {
          onViewChange("pinned");
          onSourceChange(undefined);
        }}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
          activeView === "pinned"
            ? "bg-muted font-medium text-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        }`}
      >
        <Star className="size-4" />
        <span>Pinned</span>
      </button>

      <Separator className="my-2" />

      {/* Collections */}
      <div className="space-y-1">
        <p className="px-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Collections
        </p>
        {collections.map((collection) => (
          <button
            key={collection.id}
            onClick={() => {
              onViewChange(collection.id);
              onSourceChange(undefined);
            }}
            className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
              activeView === collection.id
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            <FolderOpen
              className="size-4"
              style={{ color: collection.color || "#6B7280" }}
            />
            <span className="truncate flex-1 text-left">{collection.name}</span>
            <span className="text-xs tabular-nums">
              {collection.memory_count}
            </span>
          </button>
        ))}
        <CreateCollectionDialog />
      </div>

      <Separator className="my-2" />

      {/* Sources */}
      <div className="space-y-1">
        <p className="px-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Sources
        </p>
        {sources.map((source) => {
          const config = getPlatformConfig(source.platform);
          return (
            <button
              key={source.platform}
              onClick={() => {
                onViewChange(null);
                onSourceChange(
                  activeSource === source.platform
                    ? undefined
                    : source.platform
                );
              }}
              className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                activeSource === source.platform
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <span
                className="inline-block size-2.5 rounded-full"
                style={{ backgroundColor: config.color }}
              />
              <span className="truncate flex-1 text-left">{config.label}</span>
              <span className="text-xs tabular-nums">{source.count}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
