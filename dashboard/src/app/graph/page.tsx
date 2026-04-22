"use client";

import { useState, useMemo, useRef, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { useGraphData } from "@/hooks/use-memories";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import { Network, CircleDot, ArrowRight } from "lucide-react";
import type { GraphNode, GraphEdge } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

const NODE_COLORS: Record<string, string> = {
  entity: "#3b82f6",
  topic: "#22c55e",
  memory: "#a855f7",
};

function getNodeColor(type: string): string {
  return NODE_COLORS[type] ?? "#6b7280";
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FGNode = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FGLink = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FGRef = any;

export default function GraphPage() {
  const { data, isLoading, error } = useGraphData();
  const [search, setSearch] = useState("");
  const [typeFilters, setTypeFilters] = useState<Record<string, boolean>>({
    entity: true,
    topic: true,
    memory: true,
  });
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const graphRef = useRef<FGRef>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: Math.max(entry.contentRect.height, 500),
        });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Narrow ``data`` inside each useMemo body (rather than via a hoisted
  // optional-chained const) so the React Compiler's inferred deps match
  // the source deps and ``preserve-manual-memoization`` stays happy.
  const availableTypes = useMemo(() => {
    const nodes = data?.nodes ?? [];
    const types = new Set(nodes.map((n) => n.type));
    return Array.from(types).sort();
  }, [data]);

  const toggleType = useCallback((type: string) => {
    setTypeFilters((prev) => ({ ...prev, [type]: !prev[type] }));
  }, []);

  const filteredNodes = useMemo(() => {
    const nodes = data?.nodes ?? [];
    return nodes.filter((node: GraphNode) => {
      const matchesType = typeFilters[node.type] !== false;
      const matchesSearch =
        search === "" || node.id.toLowerCase().includes(search.toLowerCase());
      return matchesType && matchesSearch;
    });
  }, [data, typeFilters, search]);

  const filteredEdges = useMemo(() => {
    const edges = data?.edges ?? [];
    const nodeIds = new Set(filteredNodes.map((n: GraphNode) => n.id));
    return edges.filter(
      (edge: GraphEdge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)
    );
  }, [data, filteredNodes]);

  const graphData = useMemo(
    () => ({
      nodes: filteredNodes.map((n: GraphNode) => ({
        id: n.id,
        type: n.type,
        count: n.count,
      })),
      links: filteredEdges.map((e: GraphEdge) => ({
        source: e.source,
        target: e.target,
        weight: e.weight,
      })),
    }),
    [filteredNodes, filteredEdges]
  );

  const paintNode = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const label = node.id;
      const fontSize = Math.max(12 / globalScale, 2);
      const size = Math.max(3, Math.sqrt(node.count) * 3);
      const isHovered = hoveredNode === node.id;

      // Draw node circle
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, isHovered ? size * 1.3 : size, 0, 2 * Math.PI);
      ctx.fillStyle = getNodeColor(node.type);
      ctx.globalAlpha = isHovered ? 1 : 0.85;
      ctx.fill();
      ctx.globalAlpha = 1;

      // Draw label
      if (globalScale > 0.7 || isHovered) {
        ctx.font = `${isHovered ? "bold " : ""}${fontSize}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = isHovered ? "#ffffff" : "#d1d5db";
        ctx.fillText(label, node.x ?? 0, (node.y ?? 0) + size + 2);
      }
    },
    [hoveredNode]
  );

  const handleNodeClick = useCallback(
    (node: FGNode) => {
      if (graphRef.current && node.x != null && node.y != null) {
        graphRef.current.centerAt(node.x, node.y, 500);
        graphRef.current.zoom(3, 500);
      }
    },
    []
  );

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-[500px]" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="p-6 text-center text-destructive">
            Failed to load graph data: {(error as Error).message}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!data || (data.nodes.length === 0 && data.edges.length === 0)) {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-4 p-12 text-center">
            <Network className="size-12 text-muted-foreground" />
            <div>
              <h2 className="text-lg font-semibold">No graph data yet</h2>
              <p className="text-sm text-muted-foreground">
                Ingest some conversations first to see the knowledge graph.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Knowledge Graph</h1>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>{filteredNodes.length} nodes</span>
          <span>&middot;</span>
          <span>{filteredEdges.length} edges</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          placeholder="Search nodes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <div className="flex items-center gap-4">
          {availableTypes.map((type) => (
            <label
              key={type}
              className="flex items-center gap-2 text-sm cursor-pointer"
            >
              <Checkbox
                checked={typeFilters[type] !== false}
                onCheckedChange={() => toggleType(type)}
              />
              <span
                className="inline-block size-2.5 rounded-full"
                style={{ backgroundColor: getNodeColor(type) }}
              />
              <span className="capitalize">{type}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Force Graph Visualization */}
      <Card>
        <CardContent className="p-0 overflow-hidden" ref={containerRef}>
          {hoveredNode && (
            <div className="absolute top-4 right-4 z-10 rounded-lg border bg-card p-3 shadow-md text-sm">
              <span className="font-medium">{hoveredNode}</span>
            </div>
          )}
          <ForceGraph2D
            ref={graphRef}
            graphData={graphData}
            width={dimensions.width}
            height={dimensions.height}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node: FGNode, color: string, ctx: CanvasRenderingContext2D) => {
              const size = Math.max(3, Math.sqrt(node.count) * 3);
              ctx.beginPath();
              ctx.arc(node.x ?? 0, node.y ?? 0, size + 2, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkWidth={(link: FGLink) =>
              typeof link.weight === "number"
                ? Math.max(0.5, Math.min(link.weight, 8))
                : 1
            }
            linkColor={() => "rgba(156, 163, 175, 0.3)"}
            linkDirectionalParticles={0}
            onNodeClick={handleNodeClick}
            onNodeHover={(node: FGNode | null) =>
              setHoveredNode(node?.id ?? null)
            }
            cooldownTicks={100}
            cooldownTime={3000}
            enableZoomInteraction={true}
            enablePanInteraction={true}
            enableNodeDrag={true}
            backgroundColor="transparent"
          />
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Nodes Grid */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CircleDot className="size-4" />
              Nodes ({filteredNodes.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {filteredNodes.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No nodes match your filters.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2 max-h-[400px] overflow-y-auto">
                {filteredNodes
                  .sort((a: GraphNode, b: GraphNode) => b.count - a.count)
                  .map((node: GraphNode) => (
                    <div
                      key={node.id}
                      className="flex items-center gap-1.5 rounded-lg border bg-card px-3 py-2 text-sm"
                    >
                      <span
                        className="inline-block size-2.5 rounded-full"
                        style={{ backgroundColor: getNodeColor(node.type) }}
                      />
                      <span className="font-medium">{node.id}</span>
                      <Badge
                        variant={
                          node.type === "entity" ? "default" : "secondary"
                        }
                      >
                        {node.type}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {node.count}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Edges List */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ArrowRight className="size-4" />
              Connections ({filteredEdges.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {filteredEdges.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No connections match your filters.
              </p>
            ) : (
              <div className="space-y-1 max-h-[400px] overflow-y-auto">
                {filteredEdges
                  .sort((a: GraphEdge, b: GraphEdge) => b.weight - a.weight)
                  .map((edge: GraphEdge, i: number) => (
                    <div
                      key={`${edge.source}-${edge.target}-${i}`}
                      className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm hover:bg-muted"
                    >
                      <span className="font-medium">{edge.source}</span>
                      <ArrowRight className="size-3 text-muted-foreground shrink-0" />
                      <span className="font-medium">{edge.target}</span>
                      <span className="ml-auto text-xs text-muted-foreground">
                        w:{edge.weight}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
