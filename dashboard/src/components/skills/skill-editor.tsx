"use client";

import { useState, useEffect, useCallback } from "react";
import { Save, Trash2, Globe, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { SkillFiles } from "@/components/skills/skill-files";
import {
  useSkill,
  useUpdateSkill,
  useDeleteSkill,
  useDistributeSkill,
  useRemoveSkillFromTool,
} from "@/hooks/use-skills";
import { toast } from "sonner";
import type { SkillDistribution } from "@/lib/types";

const DISTRIBUTE_TARGETS = [
  { id: "claude", label: "Claude" },
  { id: "codex", label: "Codex" },
  { id: "cursor", label: "Cursor" },
  { id: "copilot", label: "Copilot" },
  { id: "opencode", label: "OpenCode" },
];

interface SkillEditorProps {
  skillId: string;
  onDeleted?: () => void;
}

export function SkillEditor({ skillId, onDeleted }: SkillEditorProps) {
  const { data: skill, isLoading } = useSkill(skillId);
  const updateSkill = useUpdateSkill();
  const deleteSkill = useDeleteSkill();
  const distributeSkill = useDistributeSkill();
  const removeFromTool = useRemoveSkillFromTool();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [distributeTo, setDistributeTo] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);

  // Sync form fields when skill data loads or changes. This is the
  // standard prop→local-state hydration pattern for editable forms: the
  // parent passes ``key={selectedId}`` on ``SkillEditor`` so a different
  // skill forces a full remount, but the *same* selected skill refetching
  // (e.g. after a mutation invalidates its query) still has to flow back
  // into the form. ``react-hooks/set-state-in-effect`` flags the batched
  // setState calls; they are intentional and idempotent under StrictMode.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (skill) {
      setName(skill.name);
      setDescription(skill.description || "");
      setContent(skill.content || "");
      setTags(skill.tags.join(", "));
      setDistributeTo(skill.distribute_to || []);
      setDirty(false);
    }
  }, [skill]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const markDirty = useCallback(() => setDirty(true), []);

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }
    try {
      await updateSkill.mutateAsync({
        id: skillId,
        body: {
          name: name.trim(),
          description: description.trim() || undefined,
          content: content.trim() || undefined,
          tags: tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
          distribute_to: distributeTo,
        },
      });
      setDirty(false);
      toast.success("Skill saved");
    } catch (err) {
      toast.error("Failed to save", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const handleDelete = async () => {
    if (!confirm("Are you sure you want to delete this skill?")) return;
    try {
      await deleteSkill.mutateAsync(skillId);
      toast.success("Skill deleted");
      onDeleted?.();
    } catch (err) {
      toast.error("Failed to delete", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const handleDistribute = async () => {
    if (distributeTo.length === 0) {
      toast.error("Select at least one tool to distribute to");
      return;
    }
    try {
      await distributeSkill.mutateAsync({ id: skillId, tools: distributeTo });
      toast.success("Skill distributed");
    } catch (err) {
      toast.error("Failed to distribute", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const toggleDistributeTarget = (target: string) => {
    setDistributeTo((prev) =>
      prev.includes(target)
        ? prev.filter((t) => t !== target)
        : [...prev, target]
    );
    markDirty();
  };

  const handleRemoveFromTool = async (tool: string) => {
    if (!confirm(`Remove this skill from ${tool}?`)) return;
    try {
      await removeFromTool.mutateAsync({ skillId, tool });
      toast.success(`Removed from ${tool}`);
    } catch (err) {
      toast.error("Failed to remove", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-6 w-32" />
      </div>
    );
  }

  if (!skill) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
        Skill not found.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Name */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Name
        </label>
        <Input
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            markDirty();
          }}
          placeholder="Skill name"
        />
      </div>

      {/* Description */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Description
        </label>
        <Textarea
          value={description}
          onChange={(e) => {
            setDescription(e.target.value);
            markDirty();
          }}
          placeholder="What does this skill do?"
          className="min-h-[60px]"
        />
      </div>

      {/* Content */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Content
        </label>
        <Textarea
          value={content}
          onChange={(e) => {
            setContent(e.target.value);
            markDirty();
          }}
          placeholder="Skill content (markdown, instructions, etc.)"
          className="min-h-[200px] font-mono text-xs"
        />
      </div>

      {/* Tags */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Tags (comma-separated)
        </label>
        <Input
          value={tags}
          onChange={(e) => {
            setTags(e.target.value);
            markDirty();
          }}
          placeholder="coding, review, best-practices"
        />
      </div>

      <Separator />

      {/* Distribute to */}
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-2 block">
          Distribute to
        </label>
        <div className="flex flex-wrap gap-3">
          {DISTRIBUTE_TARGETS.map((target) => (
            <label
              key={target.id}
              className="flex items-center gap-2 text-sm cursor-pointer"
            >
              <Checkbox
                checked={distributeTo.includes(target.id)}
                onCheckedChange={() => toggleDistributeTarget(target.id)}
              />
              {target.label}
            </label>
          ))}
        </div>
      </div>

      <Separator />

      {/* Files */}
      <SkillFiles skillId={skillId} files={skill.files} />

      <Separator />

      {/* Distribution status */}
      {skill.distributions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2">
            Distribution Status
          </p>
          <div className="space-y-1.5">
            {skill.distributions.map((dist: SkillDistribution, idx: number) => (
              <div
                key={`${dist.tool}-${idx}`}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                  <Globe className="size-3 text-muted-foreground shrink-0" />
                  <span className="font-medium">{dist.tool}</span>
                  <span className="text-muted-foreground font-mono truncate max-w-[200px]">
                    {dist.target_path}
                  </span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Badge
                    variant={dist.status === "success" ? "secondary" : "outline"}
                    className="text-[10px]"
                  >
                    {dist.status}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => handleRemoveFromTool(dist.tool)}
                    disabled={removeFromTool.isPending}
                    aria-label={`Remove from ${dist.tool}`}
                    title={`Remove from ${dist.tool}`}
                  >
                    <X className="size-3" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Auto-extracted badge */}
      {skill.auto_extracted && (
        <div className="flex items-center gap-2">
          <Sparkles className="size-3.5 text-amber-500" />
          <span className="text-xs text-muted-foreground">
            Auto-extracted (confidence: {(skill.extraction_confidence * 100).toFixed(0)}%)
          </span>
        </div>
      )}

      <Separator />

      {/* Action bar */}
      <div className="flex items-center gap-2">
        <Button
          onClick={handleSave}
          disabled={updateSkill.isPending || !dirty}
          size="sm"
        >
          <Save className="size-4 mr-1" />
          {updateSkill.isPending ? "Saving..." : "Save"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleDistribute}
          disabled={distributeSkill.isPending || distributeTo.length === 0}
        >
          <Globe className="size-4 mr-1" />
          {distributeSkill.isPending ? "Distributing..." : "Distribute Now"}
        </Button>
        <div className="flex-1" />
        <Button
          variant="destructive"
          size="sm"
          onClick={handleDelete}
          disabled={deleteSkill.isPending}
        >
          <Trash2 className="size-4 mr-1" />
          Delete
        </Button>
      </div>
    </div>
  );
}
