"use client";

import { useMemo, useState } from "react";
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
  getWatcherLogs,
  installWatcher,
  listWatchers,
  uninstallWatcher,
  updateWatcher,
} from "@/lib/api";
import type { WatcherRow } from "@/lib/types";
import { Activity, CheckCircle2, Pause, Play, XCircle } from "lucide-react";

const MECHANISM_LABEL: Record<string, string> = {
  hook: "Hook",
  file_watcher: "File watcher",
  mcp: "MCP",
  import: "Import only",
  unknown: "—",
};

// Tools where install/uninstall buttons make sense (others are MCP/import-only).
const INSTALLABLE = new Set([
  "claude_code",
  "codex",
  "gemini_cli",
  "antigravity",
  "aider",
  "copilot_cli",
]);

function formatRelative(ts: string | null): string {
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

function StatusDot({ row }: { row: WatcherRow }) {
  if (!row.installed_at) {
    return <span className="size-2 rounded-full bg-muted-foreground/40" />;
  }
  if (row.last_error) {
    return <span className="size-2 rounded-full bg-destructive" />;
  }
  if (row.enabled) {
    return <span className="size-2 rounded-full bg-emerald-500" />;
  }
  return <span className="size-2 rounded-full bg-amber-500" />;
}

export default function WatchersPage() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);

  const watchersQuery = useQuery({
    queryKey: ["watchers"],
    queryFn: listWatchers,
    refetchInterval: 10_000,
  });

  const rows: WatcherRow[] = useMemo(
    () => watchersQuery.data?.watchers ?? [],
    [watchersQuery.data],
  );

  const logsQuery = useQuery({
    queryKey: ["watcher-logs", selected],
    queryFn: () => getWatcherLogs(selected!, 50),
    enabled: !!selected,
    refetchInterval: 5_000,
  });

  const installMut = useMutation({
    mutationFn: installWatcher,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchers"] }),
  });

  const uninstallMut = useMutation({
    mutationFn: uninstallWatcher,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchers"] }),
  });

  const toggleMut = useMutation({
    mutationFn: ({ tool, enabled }: { tool: string; enabled: boolean }) =>
      updateWatcher(tool, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["watchers"] }),
  });

  return (
    <>
      <Header title="Watchers" />
      <div className="flex-1 p-6 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="size-4" />
              Cross-tool automatic capture
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Memgentic captures memory from each AI tool using the mechanism
              native to it: hooks (Claude Code, Codex), file watchers
              (Gemini CLI, Antigravity, Aider, Copilot CLI), MCP (Cursor,
              OpenCode), and one-shot imports (ChatGPT, Claude Web).
            </p>
          </CardContent>
        </Card>

        {watchersQuery.isLoading && (
          <div className="grid gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        )}

        {watchersQuery.error && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            Failed to load watchers: {(watchersQuery.error as Error).message}
          </div>
        )}

        {!watchersQuery.isLoading && rows.length > 0 && (
          <div className="rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Tool</th>
                  <th className="px-3 py-2 font-medium">Mechanism</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Captured</th>
                  <th className="px-3 py-2 font-medium">Last capture</th>
                  <th className="px-3 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.tool}
                    className={`border-b last:border-b-0 hover:bg-muted/30 ${
                      selected === row.tool ? "bg-muted/40" : ""
                    }`}
                    onClick={() =>
                      setSelected(selected === row.tool ? null : row.tool)
                    }
                  >
                    <td className="px-3 py-2 font-medium">{row.tool}</td>
                    <td className="px-3 py-2">
                      <Badge variant="secondary" className="text-xs">
                        {MECHANISM_LABEL[row.mechanism] ?? row.mechanism}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <StatusDot row={row} />
                        <span className="text-xs text-muted-foreground">
                          {row.installed_at
                            ? row.enabled
                              ? row.last_error
                                ? "error"
                                : "capturing"
                              : "disabled"
                            : "not installed"}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2">{row.captured_count}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {formatRelative(row.last_captured_at)}
                    </td>
                    <td
                      className="px-3 py-2 text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {INSTALLABLE.has(row.tool) ? (
                        row.installed_at ? (
                          <div className="inline-flex gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() =>
                                toggleMut.mutate({
                                  tool: row.tool,
                                  enabled: !row.enabled,
                                })
                              }
                              disabled={toggleMut.isPending}
                            >
                              {row.enabled ? (
                                <>
                                  <Pause className="size-3.5 mr-1" />
                                  Disable
                                </>
                              ) : (
                                <>
                                  <Play className="size-3.5 mr-1" />
                                  Enable
                                </>
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => uninstallMut.mutate(row.tool)}
                              disabled={uninstallMut.isPending}
                            >
                              <XCircle className="size-3.5 mr-1" />
                              Uninstall
                            </Button>
                          </div>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => installMut.mutate(row.tool)}
                            disabled={installMut.isPending}
                          >
                            <CheckCircle2 className="size-3.5 mr-1" />
                            Install
                          </Button>
                        )
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          via {MECHANISM_LABEL[row.mechanism]}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {selected && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Recent activity — {selected}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {logsQuery.isLoading && (
                <Skeleton className="h-32 w-full" />
              )}
              {logsQuery.data &&
                (logsQuery.data.entries.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No log entries yet.
                  </p>
                ) : (
                  <ul className="space-y-1 text-xs font-mono">
                    {logsQuery.data.entries.map((entry, idx) => (
                      <li
                        key={idx}
                        className="flex gap-3 text-muted-foreground"
                      >
                        <span className="shrink-0">{entry.created_at}</span>
                        <span className="shrink-0 uppercase">
                          [{entry.level}]
                        </span>
                        <span className="text-foreground">
                          {entry.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                ))}
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
