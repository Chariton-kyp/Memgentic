"use client";

import { useState } from "react";
import { Plus, FileText, Trash2, X as XIcon, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCreateSkillFile, useDeleteSkillFile } from "@/hooks/use-skills";
import { toast } from "sonner";
import type { SkillFile } from "@/lib/types";

interface SkillFilesProps {
  skillId: string;
  files: SkillFile[];
}

export function SkillFiles({ skillId, files }: SkillFilesProps) {
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [showAddFile, setShowAddFile] = useState(false);
  const [newFilePath, setNewFilePath] = useState("");
  const [newFileContent, setNewFileContent] = useState("");

  const createFile = useCreateSkillFile();
  const deleteFile = useDeleteSkillFile();

  const selectedFile = files.find((f) => f.id === selectedFileId);

  const handleAddFile = async () => {
    if (!newFilePath.trim()) {
      toast.error("File path is required");
      return;
    }
    try {
      await createFile.mutateAsync({
        skillId,
        body: { path: newFilePath.trim(), content: newFileContent },
      });
      setShowAddFile(false);
      setNewFilePath("");
      setNewFileContent("");
      toast.success("File added");
    } catch (err) {
      toast.error("Failed to add file", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const handleDeleteFile = async (fileId: string) => {
    if (!confirm("Delete this file?")) return;
    try {
      await deleteFile.mutateAsync({ skillId, fileId });
      if (selectedFileId === fileId) setSelectedFileId(null);
      toast.success("File deleted");
    } catch (err) {
      toast.error("Failed to delete file", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">Files</p>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => setShowAddFile(!showAddFile)}
        >
          {showAddFile ? (
            <>
              <XIcon className="size-3 mr-1" />
              Cancel
            </>
          ) : (
            <>
              <Plus className="size-3 mr-1" />
              Add File
            </>
          )}
        </Button>
      </div>

      {/* Add file form */}
      {showAddFile && (
        <div className="space-y-2 rounded-md border p-3">
          <Input
            placeholder="File path (e.g., rules/formatting.md)"
            value={newFilePath}
            onChange={(e) => setNewFilePath(e.target.value)}
            className="text-xs h-7"
          />
          <Textarea
            placeholder="File content..."
            value={newFileContent}
            onChange={(e) => setNewFileContent(e.target.value)}
            className="text-xs font-mono min-h-[80px]"
          />
          <Button
            size="xs"
            onClick={handleAddFile}
            disabled={createFile.isPending}
          >
            <Save className="size-3 mr-1" />
            {createFile.isPending ? "Adding..." : "Add"}
          </Button>
        </div>
      )}

      {/* File list */}
      {files.length === 0 && !showAddFile && (
        <p className="text-xs text-muted-foreground">No files attached.</p>
      )}

      {files.map((file) => (
        <div key={file.id}>
          <div className="flex items-center justify-between">
            <button
              onClick={() =>
                setSelectedFileId(selectedFileId === file.id ? null : file.id)
              }
              className="flex items-center gap-1.5 text-xs hover:text-foreground text-muted-foreground transition-colors"
            >
              <FileText className="size-3" />
              <span className="font-mono">{file.path}</span>
            </button>
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => handleDeleteFile(file.id)}
              disabled={deleteFile.isPending}
            >
              <Trash2 className="size-3" />
            </Button>
          </div>

          {selectedFileId === file.id && selectedFile && (
            <div className="mt-2 rounded-md border bg-muted/30 p-3">
              <pre className="text-xs font-mono whitespace-pre-wrap break-words max-h-60 overflow-y-auto">
                {selectedFile.content}
              </pre>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
