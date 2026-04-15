"use client";

import { useSources } from "@/hooks/use-memories";
import { getPlatformConfig } from "@/lib/constants";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Database } from "lucide-react";

export default function SourcesPage() {
  const { data, isLoading, error } = useSources();

  return (
    <>
      <Header title="Sources" />
      <div className="flex-1 p-6 space-y-6">
        {error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            Failed to load sources: {(error as Error).message}
          </div>
        )}

        {isLoading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-5 w-28" />
                </CardHeader>
                <CardContent className="space-y-3">
                  <Skeleton className="h-8 w-16" />
                  <Skeleton className="h-3 w-full" />
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {!isLoading && !error && data && data.sources.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Database className="size-12 text-muted-foreground mb-4" />
            <h2 className="text-lg font-semibold">No sources yet</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Connect AI tools to start capturing memories.
            </p>
          </div>
        )}

        {!isLoading && !error && data && data.sources.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.sources.map((source) => {
              const config = getPlatformConfig(source.platform);
              return (
                <Card key={source.platform}>
                  <CardHeader className="flex-row items-center gap-3 space-y-0">
                    <div
                      className="flex size-10 items-center justify-center rounded-lg"
                      style={{ backgroundColor: `${config.color}20` }}
                    >
                      <Database
                        className="size-5"
                        style={{ color: config.color }}
                      />
                    </div>
                    <CardTitle className="text-base">{config.label}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex items-baseline gap-2">
                      <span className="text-3xl font-bold">{source.count}</span>
                      <span className="text-sm text-muted-foreground">
                        memories
                      </span>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span>{source.percentage.toFixed(1)}% of total</span>
                        <span>{data.total} total</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${source.percentage}%`,
                            backgroundColor: config.color,
                          }}
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
