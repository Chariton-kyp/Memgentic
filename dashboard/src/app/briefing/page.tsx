"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Header } from "@/components/layout/header";
import {
  getBriefing,
  listBriefingTiers,
  previewBriefingWeights,
} from "@/lib/api";
import type {
  BriefingResponse,
  BriefingTiersResponse,
  BriefingWeights,
  RecallTier,
} from "@/lib/types";
import { Copy, RefreshCw, Sliders } from "lucide-react";

// Tier metadata for the picker UI. Keep copy in sync with the backend tier
// definitions — each tier has a short description so users can tell them apart.
type TierKey = Exclude<RecallTier, "default">;

interface TierMeta {
  key: TierKey;
  label: string;
  description: string;
  needsCollection?: boolean;
  needsTopic?: boolean;
  needsQuery?: boolean;
  needsEntity?: boolean;
}

const TIERS: TierMeta[] = [
  {
    key: "T0",
    label: "T0 Persona",
    description: "The agent's self-concept. Always loaded.",
  },
  {
    key: "T1",
    label: "T1 Horizon",
    description: "Top memories + top skills. Default briefing.",
  },
  {
    key: "T2",
    label: "T2 Orbit",
    description: "Memories filtered by collection or topic.",
    needsCollection: true,
    needsTopic: true,
  },
  {
    key: "T3",
    label: "T3 Deep Recall",
    description: "Semantic + keyword hybrid search.",
    needsQuery: true,
  },
  {
    key: "T4",
    label: "T4 Atlas",
    description: "Knowledge-graph traversal around an entity.",
    needsEntity: true,
  },
];

const DEFAULT_WEIGHTS: BriefingWeights = {
  importance: 0.3,
  recency: 0.25,
  pinned: 0.25,
  cluster: 0.1,
  skill_link: 0.1,
  tau_days: 30,
};

// Sliders that map to BriefingScorer knobs. τ is a raw numeric input because
// it's measured in days, not a 0–1 weight.
const WEIGHT_SLIDERS: {
  key: keyof Omit<BriefingWeights, "tau_days">;
  label: string;
  hint: string;
}[] = [
  { key: "importance", label: "Importance", hint: "LLM-assigned salience" },
  { key: "recency", label: "Recency", hint: "Exponential decay on age" },
  { key: "pinned", label: "Pinned", hint: "Boost for user-pinned items" },
  { key: "cluster", label: "Cluster", hint: "Centrality inside its cluster" },
  { key: "skill_link", label: "Skill link", hint: "Linked to an active skill" },
];

export default function BriefingPage() {
  const qc = useQueryClient();

  // Tier + per-tier extra inputs. We deliberately keep each extra in its own
  // state slot so users can switch tiers without losing their context.
  const [tier, setTier] = useState<TierKey>("T1");
  const [collection, setCollection] = useState("");
  const [topic, setTopic] = useState("");
  const [query, setQuery] = useState("");
  const [entity, setEntity] = useState("");
  const [maxTokens, setMaxTokens] = useState<string>("");

  // Slider values are held locally and committed on pointer-up — live
  // state keeps the slider snappy, the commit triggers one POST + re-GET.
  const [weights, setWeights] = useState<BriefingWeights>(DEFAULT_WEIGHTS);
  const [committedWeights, setCommittedWeights] =
    useState<BriefingWeights>(DEFAULT_WEIGHTS);

  const activeTier = useMemo(
    () => TIERS.find((t) => t.key === tier) ?? TIERS[1],
    [tier],
  );

  const tiersQuery = useQuery<BriefingTiersResponse>({
    queryKey: ["briefing-tiers"],
    queryFn: () => listBriefingTiers(),
  });

  const briefingQuery = useQuery<BriefingResponse>({
    queryKey: [
      "briefing",
      tier,
      collection,
      topic,
      query,
      entity,
      maxTokens,
      committedWeights,
    ],
    queryFn: () =>
      getBriefing({
        tier,
        collection: activeTier.needsCollection && collection ? collection : undefined,
        topic: activeTier.needsTopic && topic ? topic : undefined,
        query: activeTier.needsQuery && query ? query : undefined,
        entity: activeTier.needsEntity && entity ? entity : undefined,
        max_tokens: maxTokens ? Number(maxTokens) : undefined,
      }),
  });

  const weightsMutation = useMutation({
    mutationFn: (patch: Partial<BriefingWeights>) => previewBriefingWeights(patch),
    onSuccess: (resp) => {
      // Server returns the merged weights (defaults + overrides). Mirror them
      // back so sliders show what the server actually used.
      setWeights(resp.weights);
      setCommittedWeights(resp.weights);
      qc.invalidateQueries({ queryKey: ["briefing"] });
    },
    onError: (err) => {
      toast.error(`Failed to apply weights: ${(err as Error).message}`);
    },
  });

  const commitWeights = useCallback(() => {
    weightsMutation.mutate(weights);
  }, [weights, weightsMutation]);

  const resetWeights = useCallback(() => {
    setWeights(DEFAULT_WEIGHTS);
    weightsMutation.mutate(DEFAULT_WEIGHTS);
  }, [weightsMutation]);

  const handleCopy = useCallback(async () => {
    const text = briefingQuery.data?.text ?? "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Briefing copied");
    } catch {
      toast.error("Clipboard unavailable");
    }
  }, [briefingQuery.data]);

  return (
    <>
      <Header title="Briefing" />
      <div className="flex-1 overflow-auto p-6">
        <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
          {/* LEFT: controls */}
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Tier</CardTitle>
                <CardDescription>
                  Progressive context loader. Pick how much to pull.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {TIERS.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setTier(t.key)}
                    aria-pressed={tier === t.key}
                    className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                      tier === t.key
                        ? "border-ring bg-muted/60"
                        : "border-border hover:bg-muted/40"
                    }`}
                  >
                    <div className="font-medium">{t.label}</div>
                    <div className="text-xs text-muted-foreground">
                      {t.description}
                    </div>
                  </button>
                ))}
              </CardContent>
            </Card>

            {(activeTier.needsCollection ||
              activeTier.needsTopic ||
              activeTier.needsQuery ||
              activeTier.needsEntity) && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Scope</CardTitle>
                  <CardDescription>
                    Extra inputs for {activeTier.label}.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {activeTier.needsCollection && (
                    <div>
                      <label
                        htmlFor="briefing-collection"
                        className="text-xs font-medium text-muted-foreground"
                      >
                        Collection
                      </label>
                      <Input
                        id="briefing-collection"
                        value={collection}
                        onChange={(e) => setCollection(e.target.value)}
                        placeholder="e.g. myapp"
                      />
                    </div>
                  )}
                  {activeTier.needsTopic && (
                    <div>
                      <label
                        htmlFor="briefing-topic"
                        className="text-xs font-medium text-muted-foreground"
                      >
                        Topic
                      </label>
                      <Input
                        id="briefing-topic"
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        placeholder="e.g. auth"
                      />
                    </div>
                  )}
                  {activeTier.needsQuery && (
                    <div>
                      <label
                        htmlFor="briefing-query"
                        className="text-xs font-medium text-muted-foreground"
                      >
                        Query
                      </label>
                      <Input
                        id="briefing-query"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="e.g. why graphql"
                      />
                    </div>
                  )}
                  {activeTier.needsEntity && (
                    <div>
                      <label
                        htmlFor="briefing-entity"
                        className="text-xs font-medium text-muted-foreground"
                      >
                        Entity
                      </label>
                      <Input
                        id="briefing-entity"
                        value={entity}
                        onChange={(e) => setEntity(e.target.value)}
                        placeholder="e.g. Kai"
                      />
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Sliders className="size-4" />
                    Weights
                  </CardTitle>
                  <CardDescription>
                    Hybrid scoring knobs for T1 Horizon.
                  </CardDescription>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={resetWeights}
                  disabled={weightsMutation.isPending}
                >
                  Reset
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                {WEIGHT_SLIDERS.map((w) => (
                  <div key={w.key}>
                    <div className="flex items-center justify-between text-xs">
                      <label
                        htmlFor={`weight-${w.key}`}
                        className="font-medium"
                      >
                        {w.label}
                      </label>
                      <span className="font-mono text-muted-foreground">
                        {weights[w.key].toFixed(2)}
                      </span>
                    </div>
                    <input
                      id={`weight-${w.key}`}
                      aria-label={w.label}
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={weights[w.key]}
                      onChange={(e) =>
                        setWeights((prev) => ({
                          ...prev,
                          [w.key]: Number(e.target.value),
                        }))
                      }
                      onPointerUp={commitWeights}
                      onKeyUp={commitWeights}
                      className="w-full accent-foreground"
                    />
                    <div className="text-xs text-muted-foreground">{w.hint}</div>
                  </div>
                ))}
                <div>
                  <label
                    htmlFor="weight-tau"
                    className="text-xs font-medium"
                  >
                    τ (recency half-life, days)
                  </label>
                  <Input
                    id="weight-tau"
                    type="number"
                    min={1}
                    max={365}
                    value={weights.tau_days}
                    onChange={(e) =>
                      setWeights((prev) => ({
                        ...prev,
                        tau_days: Number(e.target.value),
                      }))
                    }
                    onBlur={commitWeights}
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Budget override</CardTitle>
                <CardDescription>
                  Optional max_tokens cap sent to the backend.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Input
                  id="briefing-max-tokens"
                  type="number"
                  min={0}
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(e.target.value)}
                  placeholder="default from tier"
                />
              </CardContent>
            </Card>
          </div>

          {/* RIGHT: preview */}
          <div className="space-y-6">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    {activeTier.label}
                    {briefingQuery.data && (
                      <Badge variant="secondary">
                        {briefingQuery.data.tokens} tok
                      </Badge>
                    )}
                  </CardTitle>
                  <CardDescription>{activeTier.description}</CardDescription>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => briefingQuery.refetch()}
                    disabled={briefingQuery.isFetching}
                  >
                    <RefreshCw className="size-3.5 mr-1" />
                    Refresh
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleCopy}
                    disabled={!briefingQuery.data?.text}
                  >
                    <Copy className="size-3.5 mr-1" />
                    Copy
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {briefingQuery.isLoading && (
                  <div className="space-y-2" data-testid="briefing-loading">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-5/6" />
                    <Skeleton className="h-4 w-2/3" />
                  </div>
                )}
                {briefingQuery.error && (
                  <div
                    role="alert"
                    className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
                  >
                    Failed to load briefing:{" "}
                    {(briefingQuery.error as Error).message}
                  </div>
                )}
                {briefingQuery.data && !briefingQuery.isLoading && (
                  <Textarea
                    readOnly
                    rows={20}
                    value={briefingQuery.data.text}
                    className="font-mono text-xs"
                    data-testid="briefing-preview"
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Tier status</CardTitle>
                <CardDescription>
                  Budgets and memory caps reported by the server.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {tiersQuery.isLoading && (
                  <Skeleton className="h-24 w-full" />
                )}
                {tiersQuery.error && (
                  <div
                    role="alert"
                    className="text-sm text-destructive"
                  >
                    Failed to load tier status:{" "}
                    {(tiersQuery.error as Error).message}
                  </div>
                )}
                {tiersQuery.data && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="py-1 pr-3 font-medium">Tier</th>
                          <th className="py-1 pr-3 font-medium">Label</th>
                          <th className="py-1 pr-3 font-medium">Tokens</th>
                          <th className="py-1 pr-3 font-medium">Max mems</th>
                          <th className="py-1 pr-3 font-medium">Ctx</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(tiersQuery.data.tiers).map(
                          ([key, info]) => (
                            <tr key={key} className="border-b last:border-b-0">
                              <td className="py-1 pr-3 font-mono">{key}</td>
                              <td className="py-1 pr-3">{info.label}</td>
                              <td className="py-1 pr-3 font-mono">
                                {info.budget.tokens}
                              </td>
                              <td className="py-1 pr-3 font-mono">
                                {info.budget.max_memories}
                              </td>
                              <td className="py-1 pr-3 font-mono">
                                {info.budget.model_context}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
