"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Header } from "@/components/layout/header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  applyDream,
  createDream,
  getDream,
  listDreams,
  rejectDream,
  type DreamPatch,
  type DreamPatchAction,
  type DreamRun,
} from "@/lib/api";
import {
  CheckCircle2,
  Loader2,
  Play,
  Sparkles,
  Wand2,
  XCircle,
} from "lucide-react";

const ACTION_BADGE: Record<DreamPatchAction, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  merge: { label: "merge", variant: "destructive" },
  supersede: { label: "supersede", variant: "destructive" },
  archive_stale: { label: "archive_stale", variant: "destructive" },
  normalize_date: { label: "normalize_date", variant: "secondary" },
  insert_insight: { label: "insert_insight", variant: "default" },
  update_field: { label: "update_field", variant: "outline" },
};

const STATUS_COLOR: Record<string, string> = {
  pending: "text-muted-foreground",
  running: "text-blue-500",
  completed: "text-green-500",
  failed: "text-red-500",
  canceled: "text-yellow-500",
};

function formatRelative(ts: string | null | undefined): string {
  if (!ts) return "—";
  const then = new Date(ts).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function PatchCard({ patch }: { patch: DreamPatch }) {
  const meta = ACTION_BADGE[patch.action] ?? { label: patch.action, variant: "outline" as const };
  const isApplied = patch.status === "applied";
  const isRejected = patch.status === "rejected";
  return (
    <div
      className={`rounded-md border p-3 text-sm ${
        isApplied
          ? "border-green-500/40 bg-green-500/5"
          : isRejected
            ? "border-muted bg-muted/30 opacity-70"
            : "border-border bg-card"
      }`}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <Badge variant={meta.variant}>{meta.label}</Badge>
          <span className="text-xs text-muted-foreground">{patch.status}</span>
        </div>
        <span className="text-[10px] font-mono text-muted-foreground">
          {patch.id.slice(0, 8)}
        </span>
      </div>
      {patch.target_memory_ids.length > 0 && (
        <div className="text-xs text-muted-foreground mb-1">
          targets:{" "}
          <span className="font-mono">
            {patch.target_memory_ids
              .slice(0, 5)
              .map((t) => t.slice(0, 8))
              .join(", ")}
            {patch.target_memory_ids.length > 5
              ? ` +${patch.target_memory_ids.length - 5}`
              : ""}
          </span>
        </div>
      )}
      {patch.evidence && (
        <p className="text-sm leading-snug whitespace-pre-wrap">{patch.evidence}</p>
      )}
      {patch.new_content && (
        <div className="mt-2 rounded bg-muted/50 p-2 text-xs whitespace-pre-wrap">
          {patch.new_content}
        </div>
      )}
    </div>
  );
}

// Provider hint inferred from a model-name prefix — mirrors the Python
// _detect_provider() helper exactly so the dashboard surfaces the same
// routing decision the backend will make.
function detectProvider(model: string): "anthropic" | "gemini" | "openai" | "ollama" | "" {
  const lower = model.trim().toLowerCase();
  if (!lower) return "";
  if (lower.startsWith("claude-") || lower.startsWith("anthropic/")) return "anthropic";
  if (lower.startsWith("gemini-") || lower.startsWith("models/gemini-")) return "gemini";
  if (lower.startsWith("gpt-") || lower.startsWith("openai/") || lower.startsWith("o1-")) return "openai";
  return "ollama";
}

const PROVIDER_BADGE: Record<string, { label: string; cls: string }> = {
  anthropic: { label: "Anthropic", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  gemini: { label: "Gemini", cls: "bg-blue-500/15 text-blue-700 dark:text-blue-300" },
  openai: { label: "OpenAI-compat", cls: "bg-green-500/15 text-green-700 dark:text-green-300" },
  ollama: { label: "Ollama (local)", cls: "bg-purple-500/15 text-purple-700 dark:text-purple-300" },
  "": { label: "default", cls: "bg-muted text-muted-foreground" },
};

export default function DreamsPage() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [project, setProject] = useState<string>("");
  const [instructions, setInstructions] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [signalModel, setSignalModel] = useState<string>("");
  const [consolidateModel, setConsolidateModel] = useState<string>("");

  const dreamsQuery = useQuery({
    queryKey: ["dreams"],
    queryFn: () => listDreams({ limit: 50 }),
  });

  const detailQuery = useQuery({
    queryKey: ["dream", selectedId],
    queryFn: () => (selectedId ? getDream(selectedId) : Promise.resolve(null)),
    enabled: !!selectedId,
  });

  const createMut = useMutation({
    mutationFn: () =>
      createDream({
        project: project || undefined,
        instructions: instructions || undefined,
        // Pass empty strings as null so the backend uses settings defaults;
        // a non-empty value forces per-run override.
        signal_model: signalModel ? signalModel : null,
        consolidate_model: consolidateModel ? consolidateModel : null,
      }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["dreams"] });
      setSelectedId(run.id);
    },
  });

  const applyMut = useMutation({
    mutationFn: (only_non_destructive: boolean) =>
      applyDream(selectedId!, { only_non_destructive }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dreams"] });
      qc.invalidateQueries({ queryKey: ["dream", selectedId] });
    },
  });

  const rejectMut = useMutation({
    mutationFn: () => rejectDream(selectedId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dreams"] });
      qc.invalidateQueries({ queryKey: ["dream", selectedId] });
    },
  });

  const dreams = dreamsQuery.data?.dreams ?? [];
  const detail = detailQuery.data;
  const proposedCount =
    detail?.patches.filter((p) => p.status === "proposed").length ?? 0;

  return (
    <>
      <Header title="Dreams" />
      <div className="flex-1 p-6 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Wand2 className="size-4" />
              LLM-driven memory consolidation
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              A dream is an LLM pass over recent session transcripts and the
              live memory store. It proposes patches (merge / supersede /
              archive / normalize_date / insert_insight / update_field) without
              touching the live data — the user reviews and explicitly applies.
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="flex-1 min-w-50">
                <label className="text-xs font-medium text-muted-foreground">
                  Project (optional, defaults to all)
                </label>
                <input
                  type="text"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  placeholder="memgentic-public-export"
                  className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="flex-1 min-w-65">
                <label className="text-xs font-medium text-muted-foreground">
                  Instructions (optional)
                </label>
                <input
                  type="text"
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  placeholder="Focus on coding-style preferences"
                  className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <Button
                onClick={() => createMut.mutate()}
                disabled={createMut.isPending}
                className="gap-2"
              >
                {createMut.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                Run dream
              </Button>
            </div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors text-left"
            >
              {showAdvanced ? "▾" : "▸"} Advanced — per-run model override
            </button>
            {showAdvanced && (
              <div className="rounded-md border bg-muted/30 p-3 space-y-3">
                <p className="text-xs text-muted-foreground">
                  Override the model used by each phase, just for this run.
                  Empty = use the configured default. Routing is by name
                  prefix:{" "}
                  <code className="text-xs">claude-*</code> →{" "}
                  <span className={PROVIDER_BADGE.anthropic.cls + " px-1 rounded"}>
                    Anthropic
                  </span>
                  ,{" "}
                  <code className="text-xs">gemini-*</code> →{" "}
                  <span className={PROVIDER_BADGE.gemini.cls + " px-1 rounded"}>
                    Gemini
                  </span>
                  ,{" "}
                  <code className="text-xs">gpt-*</code> →{" "}
                  <span className={PROVIDER_BADGE.openai.cls + " px-1 rounded"}>
                    OpenAI-compat
                  </span>
                  , anything else (e.g.{" "}
                  <code className="text-xs">qwen3.6:35b-a3b</code>) →{" "}
                  <span className={PROVIDER_BADGE.ollama.cls + " px-1 rounded"}>
                    Ollama
                  </span>
                  .
                </p>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground flex items-center justify-between">
                      <span>Phase 2 — Gather Signal</span>
                      {signalModel && (
                        <span
                          className={`text-[10px] font-normal px-1.5 py-0.5 rounded ${PROVIDER_BADGE[detectProvider(signalModel)].cls}`}
                        >
                          {PROVIDER_BADGE[detectProvider(signalModel)].label}
                        </span>
                      )}
                    </label>
                    <input
                      type="text"
                      value={signalModel}
                      onChange={(e) => setSignalModel(e.target.value)}
                      placeholder="e.g. claude-haiku-4-5 or gemma4:e4b"
                      className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground flex items-center justify-between">
                      <span>Phase 3 — Consolidate</span>
                      {consolidateModel && (
                        <span
                          className={`text-[10px] font-normal px-1.5 py-0.5 rounded ${PROVIDER_BADGE[detectProvider(consolidateModel)].cls}`}
                        >
                          {PROVIDER_BADGE[detectProvider(consolidateModel)].label}
                        </span>
                      )}
                    </label>
                    <input
                      type="text"
                      value={consolidateModel}
                      onChange={(e) => setConsolidateModel(e.target.value)}
                      placeholder="e.g. claude-sonnet-4-6 or qwen3.6:35b-a3b"
                      className="mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm font-mono"
                    />
                  </div>
                </div>
                <div className="text-xs text-muted-foreground space-y-1">
                  <div>
                    <strong>Cheap cloud:</strong> Phase 2 ={" "}
                    <code>claude-haiku-4-5</code>, Phase 3 ={" "}
                    <code>claude-haiku-4-5</code> (~$0.10/run)
                  </div>
                  <div>
                    <strong>Best local (64 GB+ RAM):</strong> Phase 2 = leave empty,
                    Phase 3 = <code>qwen3.6:35b-a3b</code> (MoE, $0)
                  </div>
                  <div>
                    <strong>Portable (16 GB RAM, NVMe stream):</strong> Phase 2 ={" "}
                    <code>gemma4:e4b</code>, Phase 3 ={" "}
                    <code>gemma4:26b-a4b</code>
                  </div>
                </div>
              </div>
            )}
            {createMut.isPending && (
              <p className="text-xs text-muted-foreground">
                Running pipeline. Cloud Haiku ~30-90 s. Local Qwen 3.6 ~6-15 min.
                Sonnet ~5-10 min. The request blocks until it finishes.
              </p>
            )}
            {createMut.error && (
              <p className="text-sm text-destructive">
                {(createMut.error as Error).message}
              </p>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
          {/* List of runs */}
          <div className="space-y-3">
            <h2 className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">
              Runs
            </h2>
            {dreamsQuery.isLoading && (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-20 w-full" />
                ))}
              </div>
            )}
            {dreamsQuery.error && (
              <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
                {(dreamsQuery.error as Error).message}
              </div>
            )}
            {!dreamsQuery.isLoading && dreams.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No dreams yet. Trigger one above.
              </p>
            )}
            <div className="space-y-2">
              {dreams.map((d: DreamRun) => {
                const isSelected = d.id === selectedId;
                return (
                  <button
                    key={d.id}
                    onClick={() => setSelectedId(d.id)}
                    className={`w-full text-left rounded-lg border p-3 transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/5"
                        : "border-border hover:bg-muted/50"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono text-xs">
                        {d.id.slice(0, 12)}
                      </span>
                      <span
                        className={`text-xs ${STATUS_COLOR[d.status] ?? ""}`}
                      >
                        {d.status}
                      </span>
                    </div>
                    <div className="text-sm">
                      <span className="font-medium">
                        {d.project || "(all)"}
                      </span>
                      <span className="text-muted-foreground">
                        {" · "}
                        {d.patches_count} patches
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1 flex items-center gap-3">
                      <span>{formatRelative(d.created_at)}</span>
                      <span>{d.model || "—"}</span>
                      {(d.usage_input_tokens > 0 ||
                        d.usage_output_tokens > 0) && (
                        <span title="Token usage">
                          {d.usage_input_tokens.toLocaleString()} in /{" "}
                          {d.usage_output_tokens.toLocaleString()} out
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Detail pane */}
          <div className="space-y-4">
            {!selectedId && (
              <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
                Select a dream to inspect its patches.
              </div>
            )}
            {selectedId && detailQuery.isLoading && (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-24 w-full" />
                ))}
              </div>
            )}
            {detail && (
              <>
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Sparkles className="size-4" />
                      {detail.run.project || "(all projects)"}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-muted-foreground">Status: </span>
                        <span
                          className={STATUS_COLOR[detail.run.status] ?? ""}
                        >
                          {detail.run.status}
                        </span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Model: </span>
                        <span>{detail.run.model || "—"}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">
                          Memories in scope:{" "}
                        </span>
                        <span>{detail.run.input_memory_count}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">
                          Tokens (in/out):{" "}
                        </span>
                        <span>
                          {detail.run.usage_input_tokens.toLocaleString()} /{" "}
                          {detail.run.usage_output_tokens.toLocaleString()}
                        </span>
                      </div>
                    </div>
                    {detail.run.error && (
                      <div className="rounded border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive">
                        {detail.run.error}
                      </div>
                    )}
                    {detail.run.status === "completed" && proposedCount > 0 && (
                      <div className="flex flex-wrap gap-2 pt-2">
                        <Button
                          size="sm"
                          variant="default"
                          onClick={() => applyMut.mutate(true)}
                          disabled={applyMut.isPending}
                          className="gap-2"
                        >
                          <CheckCircle2 className="size-4" />
                          Apply non-destructive only
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => {
                            if (
                              window.confirm(
                                "This applies merges, supersedes, and archives — they are reversible only via DB restore. Continue?",
                              )
                            ) {
                              applyMut.mutate(false);
                            }
                          }}
                          disabled={applyMut.isPending}
                          className="gap-2"
                        >
                          <CheckCircle2 className="size-4" />
                          Apply ALL (incl. destructive)
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => rejectMut.mutate()}
                          disabled={rejectMut.isPending}
                          className="gap-2"
                        >
                          <XCircle className="size-4" />
                          Reject all proposed
                        </Button>
                      </div>
                    )}
                    {applyMut.data && (
                      <div className="rounded border bg-muted/30 p-2 text-xs space-y-1">
                        <div>
                          Applied: <strong>{applyMut.data.applied}</strong>{" "}
                          · Skipped (destructive):{" "}
                          <strong>{applyMut.data.skipped_destructive}</strong>
                        </div>
                        {applyMut.data.inserted_memories.length > 0 && (
                          <div>
                            Inserted insights:{" "}
                            {applyMut.data.inserted_memories.length}
                          </div>
                        )}
                        {applyMut.data.superseded_memories.length > 0 && (
                          <div>
                            Superseded:{" "}
                            {applyMut.data.superseded_memories.length}
                          </div>
                        )}
                        {applyMut.data.archived_memories.length > 0 && (
                          <div>
                            Archived: {applyMut.data.archived_memories.length}
                          </div>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <div className="space-y-2">
                  <h3 className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">
                    Patches ({detail.patches.length})
                  </h3>
                  {detail.patches.length === 0 && (
                    <p className="text-sm text-muted-foreground">
                      No patches were proposed.
                    </p>
                  )}
                  <div className="space-y-2">
                    {detail.patches.map((patch) => (
                      <PatchCard key={patch.id} patch={patch} />
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
