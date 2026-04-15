"use client";

import { useStats, useSources } from "@/hooks/use-memories";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getPlatformConfig } from "@/lib/constants";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Brain, Database, Radio, HardDrive } from "lucide-react";

export default function AnalyticsPage() {
  const { data: stats, isLoading: statsLoading, error: statsError } = useStats();
  const { data: sourcesData, isLoading: sourcesLoading } = useSources();

  const isLoading = statsLoading || sourcesLoading;

  if (isLoading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }

  if (statsError) {
    return (
      <div className="p-6 text-center text-destructive">
        Failed to load analytics: {(statsError as Error).message}
      </div>
    );
  }

  const sources = sourcesData?.sources ?? stats?.sources ?? [];
  const pieData = sources.map((s) => ({
    name: getPlatformConfig(s.platform).label,
    value: s.count,
    color: getPlatformConfig(s.platform).color,
  }));

  const barData = sources
    .sort((a, b) => b.count - a.count)
    .map((s) => ({
      name: getPlatformConfig(s.platform).label,
      count: s.count,
      fill: getPlatformConfig(s.platform).color,
    }));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Chart 1: Source Distribution Pie */}
        <Card>
          <CardHeader>
            <CardTitle>Source Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            {pieData.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No source data available.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    label={({ name, percent }) =>
                      `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
                    }
                    labelLine={false}
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        {/* Chart 2: Memory Stats Summary */}
        <Card>
          <CardHeader>
            <CardTitle>Memory Stats</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                <Brain className="size-6 text-muted-foreground" />
                <span className="text-2xl font-bold">
                  {stats?.total_memories ?? 0}
                </span>
                <span className="text-xs text-muted-foreground">
                  Total Memories
                </span>
              </div>
              <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                <Database className="size-6 text-muted-foreground" />
                <span className="text-2xl font-bold">
                  {stats?.vector_count ?? 0}
                </span>
                <span className="text-xs text-muted-foreground">
                  Vector Count
                </span>
              </div>
              <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                <Radio className="size-6 text-muted-foreground" />
                <span className="text-2xl font-bold">{sources.length}</span>
                <span className="text-xs text-muted-foreground">
                  Active Sources
                </span>
              </div>
              <div className="flex flex-col items-center gap-2 rounded-lg border p-4">
                <HardDrive className="size-6 text-muted-foreground" />
                <span className="text-2xl font-bold text-center text-sm">
                  {stats?.store_status ?? "unknown"}
                </span>
                <span className="text-xs text-muted-foreground">
                  Store Status
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Chart 3: Top Sources Bar Chart */}
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Top Sources</CardTitle>
          </CardHeader>
          <CardContent>
            {barData.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No source data available.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart
                  data={barData}
                  layout="vertical"
                  margin={{ left: 80, right: 20, top: 5, bottom: 5 }}
                >
                  <XAxis type="number" />
                  <YAxis type="category" dataKey="name" width={70} />
                  <Tooltip />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                    {barData.map((entry, index) => (
                      <Cell key={`bar-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
