"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, FileText, Link2, X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useUploadText, useUploadFile, useTopics, useCreateMemory } from "@/hooks/use-memories";
import { uploadUrl } from "@/lib/api";
import { CONTENT_TYPE_CONFIG } from "@/lib/constants";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

function TopicInput({
  topics,
  onChange,
}: {
  topics: string[];
  onChange: (topics: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const { data: topicsData } = useTopics();
  const allTopics = topicsData?.topics ?? [];
  const filtered = input.length > 0
    ? allTopics.filter(
        (t) =>
          t.toLowerCase().includes(input.toLowerCase()) &&
          !topics.includes(t)
      ).slice(0, 5)
    : [];

  const addTopic = (topic: string) => {
    const trimmed = topic.trim().toLowerCase();
    if (trimmed && !topics.includes(trimmed)) {
      onChange([...topics, trimmed]);
    }
    setInput("");
  };

  const removeTopic = (topic: string) => {
    onChange(topics.filter((t) => t !== topic));
  };

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">Topics</label>
      <div className="flex flex-wrap gap-1 mb-1">
        {topics.map((topic) => (
          <Badge key={topic} variant="secondary" className="gap-1">
            {topic}
            <button onClick={() => removeTopic(topic)} className="ml-0.5">
              <X className="size-3" />
            </button>
          </Badge>
        ))}
      </div>
      <div className="relative">
        <Input
          placeholder="Add topics..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && input.trim()) {
              e.preventDefault();
              addTopic(input);
            }
          }}
        />
        {filtered.length > 0 && (
          <div className="absolute z-10 mt-1 w-full rounded-md border bg-popover p-1 shadow-md">
            {filtered.map((topic) => (
              <button
                key={topic}
                onClick={() => addTopic(topic)}
                className="w-full rounded px-2 py-1 text-left text-sm hover:bg-muted"
              >
                {topic}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function WriteTab({ onSuccess }: { onSuccess: () => void }) {
  const [content, setContent] = useState("");
  const [topics, setTopics] = useState<string[]>([]);
  const [contentType, setContentType] = useState<string>("fact");
  const createMemory = useCreateMemory();

  const handleSave = () => {
    if (!content.trim()) return;
    createMemory.mutate(
      {
        content: content.trim(),
        content_type: contentType,
        topics,
        source: "dashboard",
      },
      {
        onSuccess: () => {
          toast.success("Memory saved");
          setContent("");
          setTopics([]);
          onSuccess();
        },
        onError: () => toast.error("Failed to save memory"),
      }
    );
  };

  return (
    <div className="space-y-4">
      <Textarea
        placeholder="What do you want to remember?"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        className="min-h-[160px]"
      />
      <TopicInput topics={topics} onChange={setTopics} />
      <div className="space-y-2">
        <label className="text-sm font-medium">Content Type</label>
        <Select value={contentType} onValueChange={(v) => { if (v) setContentType(v); }}>
          <SelectTrigger className="w-full" aria-label="Content type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(CONTENT_TYPE_CONFIG).map(([key, cfg]) => (
              <SelectItem key={key} value={key}>
                {cfg.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button
        onClick={handleSave}
        disabled={!content.trim() || createMemory.isPending}
        className="w-full"
      >
        {createMemory.isPending && <Loader2 className="size-4 mr-2 animate-spin" />}
        Save
      </Button>
    </div>
  );
}

function FileTab({ onSuccess }: { onSuccess: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [contentType, setContentType] = useState<string>("fact");
  const uploadFile = useUploadFile();

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/plain": [".txt"],
      "text/markdown": [".md"],
      "application/pdf": [".pdf"],
      "application/json": [".json"],
    },
    maxFiles: 1,
  });

  const handleImport = () => {
    if (!file) return;
    uploadFile.mutate(
      { file, metadata: { topics, content_type: contentType } },
      {
        onSuccess: () => {
          toast.success("File imported");
          setFile(null);
          setTopics([]);
          onSuccess();
        },
        onError: () => toast.error("Failed to import file"),
      }
    );
  };

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center cursor-pointer transition-colors ${
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-muted-foreground/50"
        }`}
      >
        <input {...getInputProps()} />
        {file ? (
          <div className="flex items-center gap-2">
            <FileText className="size-5 text-muted-foreground" />
            <span className="text-sm font-medium">{file.name}</span>
            <span className="text-xs text-muted-foreground">
              ({(file.size / 1024).toFixed(1)} KB)
            </span>
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={(e) => {
                e.stopPropagation();
                setFile(null);
              }}
            >
              <X className="size-3" />
            </Button>
          </div>
        ) : (
          <>
            <Upload className="size-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">
              Drop .md, .txt, .pdf, or .json here
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              or click to browse
            </p>
          </>
        )}
      </div>
      <TopicInput topics={topics} onChange={setTopics} />
      <div className="space-y-2">
        <label className="text-sm font-medium">Content Type</label>
        <Select value={contentType} onValueChange={(v) => { if (v) setContentType(v); }}>
          <SelectTrigger className="w-full" aria-label="Content type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(CONTENT_TYPE_CONFIG).map(([key, cfg]) => (
              <SelectItem key={key} value={key}>
                {cfg.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button
        onClick={handleImport}
        disabled={!file || uploadFile.isPending}
        className="w-full"
      >
        {uploadFile.isPending && <Loader2 className="size-4 mr-2 animate-spin" />}
        Import
      </Button>
    </div>
  );
}

function UrlTab({ onSuccess }: { onSuccess: () => void }) {
  const [url, setUrl] = useState("");
  const [topics, setTopics] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const handleFetch = async () => {
    if (!url.trim()) return;
    setLoading(true);
    try {
      await uploadUrl({ url: url.trim(), topics });
      toast.success("URL content saved");
      setUrl("");
      setTopics([]);
      onSuccess();
    } catch {
      toast.error("Failed to fetch URL");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="text-sm font-medium">URL</label>
        <Input
          placeholder="https://example.com/article"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          type="url"
        />
      </div>
      <TopicInput topics={topics} onChange={setTopics} />
      <Button
        onClick={handleFetch}
        disabled={!url.trim() || loading}
        className="w-full"
      >
        {loading && <Loader2 className="size-4 mr-2 animate-spin" />}
        Fetch & Save
      </Button>
    </div>
  );
}

interface UploadModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UploadModal({ open, onOpenChange }: UploadModalProps) {
  const handleSuccess = () => {
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add Knowledge</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="write">
          <TabsList className="w-full">
            <TabsTrigger value="write">
              <FileText className="size-4 mr-1" />
              Write
            </TabsTrigger>
            <TabsTrigger value="file">
              <Upload className="size-4 mr-1" />
              File
            </TabsTrigger>
            <TabsTrigger value="url">
              <Link2 className="size-4 mr-1" />
              URL
            </TabsTrigger>
          </TabsList>
          <TabsContent value="write" className="pt-4">
            <WriteTab onSuccess={handleSuccess} />
          </TabsContent>
          <TabsContent value="file" className="pt-4">
            <FileTab onSuccess={handleSuccess} />
          </TabsContent>
          <TabsContent value="url" className="pt-4">
            <UrlTab onSuccess={handleSuccess} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
