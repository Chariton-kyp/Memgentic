"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckIcon, XIcon, Pencil, Clock, Network } from "lucide-react";
import {
  acceptTriple,
  editTriple,
  getChronographStats,
  getChronographTimeline,
  listProposedTriples,
  listTriples,
  rejectTriple,
  type ChronographStats,
  type ChronographTriple,
} from "@/lib/api";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FGNode = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FGLink = any;

function formatDate(value: string | null): string {
  if (!value) return "—";
  return value.slice(0, 10);
}

function StatsRow({ stats }: { stats: ChronographStats | undefined }) {
  if (!stats) {
    return <Skeleton className="h-20 w-full" />;
  }
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      <StatCard label="Entities" value={stats.entities} />
      <StatCard label="Triples" value={stats.triples} />
      <StatCard label="Predicates" value={stats.predicates} />
      <StatCard label="Accepted" value={stats.accepted} accent="green" />
      <StatCard
        label="Proposed"
        value={stats.proposed}
        accent={stats.proposed > 0 ? "amber" : undefined}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: "green" | "amber";
}) {
  const tone =
    accent === "green"
      ? "text-green-600"
      : accent === "amber"
        ? "text-amber-600"
        : "text-foreground";
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-xs uppercase text-muted-foreground">{label}</div>
        <div className={`text-2xl font-semibold ${tone}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ validation queue

function ValidationQueue() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["chronograph", "proposed"],
    queryFn: () => listProposedTriples(100),
  });

  const accept = useMutation({
    mutationFn: (id: string) => acceptTriple(id),
    onSuccess: () => {
      toast.success("Triple accepted");
      queryClient.invalidateQueries({ queryKey: ["chronograph"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const reject = useMutation({
    mutationFn: (id: string) => rejectTriple(id),
    onSuccess: () => {
      toast.success("Triple rejected");
      queryClient.invalidateQueries({ queryKey: ["chronograph"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const edit = useMutation({
    mutationFn: (vars: { id: string; predicate: string }) =>
      editTriple(vars.id, { predicate: vars.predicate }),
    onSuccess: () => {
      toast.success("Triple updated");
      queryClient.invalidateQueries({ queryKey: ["chronograph"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  const triples = data?.triples ?? [];

  if (triples.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          The validation queue is empty. Proposed triples appear here once the
          extractor runs on newly ingested memories.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Validation queue
          <Badge variant="secondary">{triples.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left border-b">
              <th className="py-2 pr-2">Subject</th>
              <th className="py-2 pr-2">Predicate</th>
              <th className="py-2 pr-2">Object</th>
              <th className="py-2 pr-2">Valid from</th>
              <th className="py-2 pr-2">Confidence</th>
              <th className="py-2 pr-2">Source</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {triples.map((t) => (
              <TripleRow
                key={t.id}
                triple={t}
                onAccept={() => accept.mutate(t.id)}
                onReject={() => reject.mutate(t.id)}
                onEdit={(predicate) => edit.mutate({ id: t.id, predicate })}
              />
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function TripleRow({
  triple,
  onAccept,
  onReject,
  onEdit,
}: {
  triple: ChronographTriple;
  onAccept: () => void;
  onReject: () => void;
  onEdit: (predicate: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [predicate, setPredicate] = useState(triple.predicate);
  return (
    <tr className="border-b last:border-0 hover:bg-muted/40">
      <td className="py-2 pr-2 font-medium">{triple.subject}</td>
      <td className="py-2 pr-2">
        {editing ? (
          <Input
            value={predicate}
            onChange={(e) => setPredicate(e.target.value)}
            className="h-8"
          />
        ) : (
          <Badge variant="outline">{triple.predicate}</Badge>
        )}
      </td>
      <td className="py-2 pr-2">{triple.object}</td>
      <td className="py-2 pr-2 text-muted-foreground">
        {formatDate(triple.valid_from)}
      </td>
      <td className="py-2 pr-2">
        <span
          className={
            triple.confidence >= 0.8
              ? "text-green-600"
              : triple.confidence >= 0.5
                ? "text-amber-600"
                : "text-red-600"
          }
        >
          {triple.confidence.toFixed(2)}
        </span>
      </td>
      <td className="py-2 pr-2">
        {triple.source_memory_id ? (
          <a
            href={`/memories/${triple.source_memory_id}`}
            className="text-xs underline text-muted-foreground hover:text-foreground"
          >
            source
          </a>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-2 text-right whitespace-nowrap">
        {editing ? (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                onEdit(predicate);
                setEditing(false);
              }}
            >
              Save
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setPredicate(triple.predicate);
                setEditing(false);
              }}
            >
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button
              size="sm"
              variant="outline"
              className="mr-1"
              onClick={() => setEditing(true)}
              aria-label="Edit"
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="mr-1"
              onClick={onAccept}
              aria-label="Accept"
            >
              <CheckIcon className="h-3 w-3" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={onReject}
              aria-label="Reject"
            >
              <XIcon className="h-3 w-3" />
            </Button>
          </>
        )}
      </td>
    </tr>
  );
}

// ------------------------------------------------------------------ graph view

function GraphView() {
  const { data, isLoading } = useQuery({
    queryKey: ["chronograph", "triples", "accepted"],
    queryFn: () => listTriples({ status: "accepted", limit: 500 }),
  });

  const graph = useMemo(() => {
    const triples = data?.triples ?? [];
    const nodes = new Map<string, FGNode>();
    const links: FGLink[] = [];
    for (const t of triples) {
      if (!nodes.has(t.subject)) {
        nodes.set(t.subject, { id: t.subject, type: "entity", count: 0 });
      }
      if (!nodes.has(t.object)) {
        nodes.set(t.object, { id: t.object, type: "entity", count: 0 });
      }
      nodes.get(t.subject)!.count += 1;
      nodes.get(t.object)!.count += 1;
      links.push({
        source: t.subject,
        target: t.object,
        predicate: t.predicate,
        active: t.valid_to === null,
      });
    }
    return { nodes: Array.from(nodes.values()), links };
  }, [data]);

  if (isLoading) {
    return <Skeleton className="h-[600px] w-full" />;
  }
  if (graph.nodes.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">
          No accepted triples yet. Accept proposed triples in the validation
          queue to populate the graph.
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="p-0 h-[600px] relative">
        <ForceGraph2D
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          graphData={graph as any}
          nodeLabel={(node: FGNode) => `${node.id} (${node.count})`}
          linkLabel={(link: FGLink) => link.predicate}
          linkColor={(link: FGLink) => (link.active ? "#3b82f6" : "#9ca3af")}
          linkDirectionalArrowLength={6}
          linkDirectionalArrowRelPos={1}
          nodeAutoColorBy="type"
          width={900}
          height={600}
        />
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ timeline

function TimelineView() {
  const [entity, setEntity] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["chronograph", "timeline", entity],
    queryFn: () =>
      getChronographTimeline({
        entity: entity || undefined,
        status: "accepted",
        limit: 300,
      }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-4 w-4" /> Timeline
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Input
          placeholder="Filter by entity (leave empty for everything)"
          value={entity}
          onChange={(e) => setEntity(e.target.value)}
        />
        {isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : data && data.triples.length > 0 ? (
          <ol className="space-y-2 border-l-2 border-muted pl-4">
            {data.triples.map((t) => (
              <li key={t.id} className="relative">
                <span className="absolute -left-[9px] top-1.5 block h-3 w-3 rounded-full bg-primary" />
                <div className="text-xs uppercase text-muted-foreground">
                  {formatDate(t.valid_from)}
                  {t.valid_to ? ` → ${formatDate(t.valid_to)}` : " → now"}
                </div>
                <div className="text-sm">
                  <span className="font-medium">{t.subject}</span>{" "}
                  <Badge variant="outline" className="align-middle">
                    {t.predicate}
                  </Badge>{" "}
                  <span className="font-medium">{t.object}</span>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <div className="text-sm text-muted-foreground">
            No accepted triples yet — accept some from the validation queue.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------------------ page

export default function ChronographPage() {
  const { data: stats } = useQuery({
    queryKey: ["chronograph", "stats"],
    queryFn: () => getChronographStats(),
  });

  return (
    <div className="space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Network className="h-5 w-5" /> Chronograph
        </h1>
        <p className="text-sm text-muted-foreground">
          Bitemporal entity-relationship graph. Every triple carries a validity
          window, confidence score, and a link back to its source memory.
        </p>
      </header>

      <StatsRow stats={stats} />

      <Tabs defaultValue="validate">
        <TabsList>
          <TabsTrigger value="validate">Validation queue</TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
        </TabsList>
        <TabsContent value="validate" className="mt-4">
          <ValidationQueue />
        </TabsContent>
        <TabsContent value="graph" className="mt-4">
          <GraphView />
        </TabsContent>
        <TabsContent value="timeline" className="mt-4">
          <TimelineView />
        </TabsContent>
      </Tabs>
    </div>
  );
}
