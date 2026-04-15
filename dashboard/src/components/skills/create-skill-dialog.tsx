"use client";

import { useState } from "react";
import { Plus, GitBranch, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  useCreateSkill,
  useImportSkillFromGitHub,
} from "@/hooks/use-skills";
import { toast } from "sonner";

interface CreateSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (id: string) => void;
}

function CreateTab({
  onCreated,
  onClose,
}: {
  onCreated?: (id: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");

  const createSkill = useCreateSkill();

  const handleCreate = async () => {
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }
    try {
      const skill = await createSkill.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
        content: content.trim() || undefined,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      toast.success("Skill created");
      setName("");
      setDescription("");
      setContent("");
      setTags("");
      onClose();
      onCreated?.(skill.id);
    } catch (err) {
      toast.error("Failed to create skill", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  return (
    <div className="space-y-4 py-2">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Name
        </label>
        <Input
          placeholder="e.g., Code Review Guidelines"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Description
        </label>
        <Textarea
          placeholder="What does this skill do?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="min-h-[60px]"
        />
      </div>
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Content
        </label>
        <Textarea
          placeholder="Skill content (markdown, instructions, etc.)"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="min-h-[120px] font-mono text-xs"
        />
      </div>
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Tags (comma-separated)
        </label>
        <Input
          placeholder="coding, review, best-practices"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
        />
      </div>
      <DialogFooter>
        <Button
          onClick={handleCreate}
          disabled={createSkill.isPending || !name.trim()}
        >
          {createSkill.isPending ? "Creating..." : "Create Skill"}
        </Button>
      </DialogFooter>
    </div>
  );
}

function ImportTab({
  onCreated,
  onClose,
}: {
  onCreated?: (id: string) => void;
  onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const importSkill = useImportSkillFromGitHub();

  const handleImport = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      toast.error("GitHub URL is required");
      return;
    }
    try {
      const skill = await importSkill.mutateAsync(trimmed);
      toast.success("Skill imported from GitHub");
      setUrl("");
      onClose();
      onCreated?.(skill.id);
    } catch (err) {
      toast.error("Failed to import skill", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  return (
    <div className="space-y-4 py-2">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          GitHub URL
        </label>
        <Input
          placeholder="https://github.com/owner/repo/tree/main/skill-name"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          type="url"
        />
        <p className="text-xs text-muted-foreground mt-1.5">
          Imports a SKILL.md folder from any GitHub repository.
        </p>
      </div>
      <DialogFooter>
        <Button
          onClick={handleImport}
          disabled={importSkill.isPending || !url.trim()}
        >
          {importSkill.isPending && (
            <Loader2 className="size-4 mr-1 animate-spin" />
          )}
          {importSkill.isPending ? "Importing..." : "Import"}
        </Button>
      </DialogFooter>
    </div>
  );
}

export function CreateSkillDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateSkillDialogProps) {
  const handleClose = () => onOpenChange(false);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New Skill</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="create">
          <TabsList className="w-full">
            <TabsTrigger value="create">
              <Plus className="size-4 mr-1" />
              Create
            </TabsTrigger>
            <TabsTrigger value="import">
              <GitBranch className="size-4 mr-1" />
              Import from GitHub
            </TabsTrigger>
          </TabsList>
          <TabsContent value="create" className="pt-4">
            <CreateTab onCreated={onCreated} onClose={handleClose} />
          </TabsContent>
          <TabsContent value="import" className="pt-4">
            <ImportTab onCreated={onCreated} onClose={handleClose} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
