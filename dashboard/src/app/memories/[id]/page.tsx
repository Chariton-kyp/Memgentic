"use client";

import { useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { format } from "date-fns";
import { ArrowLeft, Archive, Trash2, Pencil, X as XIcon, Save } from "lucide-react";
import { useMemory, useDeleteMemory, useSearch } from "@/hooks/use-memories";
import { getPlatformConfig, getContentTypeConfig } from "@/lib/constants";
import Link from "next/link";
import { updateMemory, getRelatedMemories } from "@/lib/api";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";

export default function MemoryDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const id = params.id;

  const { data: memory, isLoading, error } = useMemory(id);
  const deleteMutation = useDeleteMemory();

  // Editing state
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [editTopics, setEditTopics] = useState("");
  const [editEntities, setEditEntities] = useState("");
  const [saving, setSaving] = useState(false);

  // Related memories via dedicated endpoint with graceful 404 handling
  const { data: relatedData, isLoading: relatedLoading } = useQuery({
    queryKey: ["related-memories", id],
    queryFn: async () => {
      try {
        return await getRelatedMemories(id);
      } catch {
        // Graceful 404 handling — endpoint may not exist yet
        return { results: [] };
      }
    },
    enabled: !!id && !!memory,
  });

  // Fallback: use search-based related memories if the dedicated endpoint returned nothing
  const { data: searchRelatedData } = useSearch(
    memory?.content?.slice(0, 200) ?? "",
    { limit: 6 }
  );

  const relatedResults = relatedData?.results && relatedData.results.length > 0
    ? relatedData.results
    : (searchRelatedData?.results?.filter((r) => r.memory.id !== id)?.slice(0, 5) ?? []);

  const startEditing = useCallback(() => {
    if (!memory) return;
    setEditContent(memory.content);
    setEditTopics(memory.topics.join(", "));
    setEditEntities(memory.entities.join(", "));
    setIsEditing(true);
  }, [memory]);

  const cancelEditing = useCallback(() => {
    setIsEditing(false);
    setEditContent("");
    setEditTopics("");
    setEditEntities("");
  }, []);

  const saveEditing = useCallback(async () => {
    if (!memory) return;
    setSaving(true);
    try {
      const topics = editTopics
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const entities = editEntities
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean);

      await updateMemory(memory.id, { topics, entities });
      queryClient.invalidateQueries({ queryKey: ["memory", id] });
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      setIsEditing(false);
      toast.success("Memory updated");
    } catch (err) {
      toast.error("Failed to save changes", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setSaving(false);
    }
  }, [memory, editTopics, editEntities, queryClient, id]);

  const handleArchive = async () => {
    if (!memory) return;
    await updateMemory(memory.id, { status: "archived" });
    router.push("/");
  };

  const handleDelete = async () => {
    if (!memory) return;
    if (!confirm("Are you sure you want to delete this memory?")) return;
    deleteMutation.mutate(memory.id, {
      onSuccess: () => router.push("/"),
    });
  };

  if (isLoading) {
    return (
      <>
        <Header title="Memory" />
        <div className="flex-1 p-6 space-y-6">
          <Skeleton className="h-8 w-32" />
          <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
            <div className="space-y-4">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-40 w-full" />
            </div>
            <div className="space-y-4">
              <Skeleton className="h-64 w-full" />
            </div>
          </div>
        </div>
      </>
    );
  }

  if (error || !memory) {
    return (
      <>
        <Header title="Memory" />
        <div className="flex-1 p-6">
          <Button variant="ghost" onClick={() => router.push("/")}>
            <ArrowLeft className="size-4 mr-2" />
            Back
          </Button>
          <div className="mt-6 rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            {error
              ? `Failed to load memory: ${(error as Error).message}`
              : "Memory not found."}
          </div>
        </div>
      </>
    );
  }

  const platform = getPlatformConfig(memory.platform);
  const contentType = getContentTypeConfig(memory.content_type);

  return (
    <>
      <Header title="Memory Detail" />
      <div className="flex-1 p-6 space-y-6">
        {/* Back + Actions */}
        <div className="flex items-center justify-between">
          <Button variant="ghost" onClick={() => router.push("/")} aria-label="Back to memories list">
            <ArrowLeft className="size-4 mr-2" aria-hidden="true" />
            Back
          </Button>
          <div className="flex gap-2">
            {isEditing ? (
              <>
                <Button variant="outline" size="sm" onClick={cancelEditing} disabled={saving}>
                  <XIcon className="size-4 mr-1" />
                  Cancel
                </Button>
                <Button size="sm" onClick={saveEditing} disabled={saving}>
                  <Save className="size-4 mr-1" />
                  {saving ? "Saving..." : "Save"}
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" size="sm" onClick={startEditing}>
                  <Pencil className="size-4 mr-1" />
                  Edit
                </Button>
                <Button variant="outline" size="sm" onClick={handleArchive}>
                  <Archive className="size-4 mr-1" />
                  Archive
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 className="size-4 mr-1" />
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>

        {/* Content + Metadata */}
        <div className="grid gap-6 lg:grid-cols-[1fr_300px]" role="main" aria-label="Memory details">
          {/* Main content */}
          <Card>
            <CardContent className="p-6">
              {isEditing ? (
                <Textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="min-h-[300px] font-[family-name:var(--font-geist-mono)] text-sm"
                  placeholder="Memory content..."
                  disabled
                  title="Content editing is read-only; edit topics and entities below."
                />
              ) : (
                <div className="whitespace-pre-wrap text-sm leading-relaxed font-[family-name:var(--font-geist-mono)]">
                  {memory.content}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Metadata sidebar */}
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Platform */}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Platform</p>
                  <Badge
                    variant="secondary"
                    className={platform.bgColor}
                    style={{ borderColor: platform.color }}
                  >
                    {platform.label}
                  </Badge>
                </div>

                {/* Content Type */}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">
                    Content Type
                  </p>
                  <Badge variant="outline">{contentType.label}</Badge>
                </div>

                {/* Confidence */}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">
                    Confidence
                  </p>
                  <p className="text-sm font-medium">
                    {(memory.confidence * 100).toFixed(0)}%
                  </p>
                </div>

                {/* Status */}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Status</p>
                  <Badge variant="secondary">{memory.status}</Badge>
                </div>

                <Separator />

                {/* Created date */}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Created</p>
                  <p className="text-sm">
                    {format(new Date(memory.created_at), "PPpp")}
                  </p>
                </div>

                {/* Session info */}
                {memory.source.session_title && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">
                      Session
                    </p>
                    <p className="text-sm">{memory.source.session_title}</p>
                  </div>
                )}
                {memory.source.session_id && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">
                      Session ID
                    </p>
                    <p className="text-xs font-mono text-muted-foreground break-all">
                      {memory.source.session_id}
                    </p>
                  </div>
                )}

                {/* Capture method */}
                <div>
                  <p className="text-xs text-muted-foreground mb-1">
                    Capture Method
                  </p>
                  <p className="text-sm">{memory.source.capture_method}</p>
                </div>

                <Separator />

                {/* Topics */}
                <div>
                  <p className="text-xs text-muted-foreground mb-2">Topics</p>
                  {isEditing ? (
                    <Input
                      value={editTopics}
                      onChange={(e) => setEditTopics(e.target.value)}
                      placeholder="topic1, topic2, ..."
                      className="text-xs"
                    />
                  ) : memory.topics.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {memory.topics.map((topic) => (
                        <Badge key={topic} variant="secondary" className="text-xs">
                          {topic}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">No topics</p>
                  )}
                </div>

                {/* Entities */}
                <div>
                  <p className="text-xs text-muted-foreground mb-2">
                    Entities
                  </p>
                  {isEditing ? (
                    <Input
                      value={editEntities}
                      onChange={(e) => setEditEntities(e.target.value)}
                      placeholder="entity1, entity2, ..."
                      className="text-xs"
                    />
                  ) : memory.entities.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                      {memory.entities.map((entity) => (
                        <Badge key={entity} variant="outline" className="text-xs">
                          {entity}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">No entities</p>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Related Memories */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Related Memories</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {relatedLoading ? (
                  <>
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-3/4" />
                  </>
                ) : relatedResults.length > 0 ? (
                  relatedResults.map((result) => (
                    <Link
                      key={result.memory.id}
                      href={`/memories/${result.memory.id}`}
                      className="block rounded-md p-2 hover:bg-muted/50 transition-colors"
                    >
                      <p className="text-xs line-clamp-2">
                        {result.memory.content.slice(0, 120)}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant="secondary" className="text-[10px]">
                          {getPlatformConfig(result.memory.platform).label}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">
                          {(result.score * 100).toFixed(0)}% match
                        </span>
                      </div>
                    </Link>
                  ))
                ) : (
                  <p className="text-xs text-muted-foreground">No related memories found.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
