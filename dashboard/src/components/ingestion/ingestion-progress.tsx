"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle, Loader, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  useCancelIngestionJob,
  useIngestionJobs,
} from "@/hooks/use-ingestion";
import type { IngestionJob } from "@/lib/types";

/**
 * Compact widget showing active ingestion jobs with live progress.
 * Completed jobs auto-hide after 5 seconds.
 * Only renders if there are active or recently-completed jobs.
 */
export function IngestionProgress() {
  const { data, isError } = useIngestionJobs();
  const cancelJob = useCancelIngestionJob();
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());

  const allJobs: IngestionJob[] = data?.jobs ?? [];

  // Active jobs: queued or running
  const activeJobs = allJobs.filter(
    (j) => (j.status === "queued" || j.status === "running") && !hiddenIds.has(j.id)
  );

  // Recently completed/failed/cancelled jobs: auto-hide after 5 seconds
  const recentlyFinishedJobs = allJobs.filter(
    (j) =>
      (j.status === "completed" ||
        j.status === "failed" ||
        j.status === "cancelled") &&
      !hiddenIds.has(j.id)
  );

  useEffect(() => {
    if (recentlyFinishedJobs.length === 0) return;
    const timers = recentlyFinishedJobs.map((job) =>
      setTimeout(() => {
        setHiddenIds((prev) => {
          const next = new Set(prev);
          next.add(job.id);
          return next;
        });
      }, 5000)
    );
    return () => {
      timers.forEach(clearTimeout);
    };
  }, [recentlyFinishedJobs]);

  if (isError) return null;
  if (activeJobs.length === 0 && recentlyFinishedJobs.length === 0) return null;

  const visibleJobs = [...activeJobs, ...recentlyFinishedJobs];

  async function handleCancel(jobId: string) {
    try {
      await cancelJob.mutateAsync(jobId);
      toast.success("Job cancelled");
    } catch (err) {
      toast.error("Failed to cancel", {
        description: (err as Error).message,
      });
    }
  }

  return (
    <div
      className="fixed bottom-4 right-4 z-40 w-80 space-y-2"
      aria-live="polite"
      aria-label="Ingestion progress"
    >
      {visibleJobs.map((job) => (
        <IngestionJobCard
          key={job.id}
          job={job}
          onCancel={() => handleCancel(job.id)}
          cancelling={cancelJob.isPending}
        />
      ))}
    </div>
  );
}

interface IngestionJobCardProps {
  job: IngestionJob;
  onCancel: () => void;
  cancelling: boolean;
}

function IngestionJobCard({ job, onCancel, cancelling }: IngestionJobCardProps) {
  const isActive = job.status === "queued" || job.status === "running";
  const pct =
    job.total_items > 0
      ? Math.min(100, Math.round((job.processed_items / job.total_items) * 100))
      : 0;

  const title = job.source_path
    ? job.source_path.split("/").pop() || job.source_type
    : job.source_type;

  return (
    <Card className="shadow-lg">
      <CardContent className="p-3 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium truncate" title={title}>
              {title}
            </p>
            <p className="text-[10px] text-muted-foreground">
              {job.source_type}
            </p>
          </div>
          <StatusBadge status={job.status} />
        </div>

        {isActive && (
          <>
            <Progress value={pct} className="h-1.5" />
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>
                {job.processed_items} of {job.total_items} items
              </span>
              <span>{pct}%</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={onCancel}
              disabled={cancelling}
              className="h-6 w-full justify-center"
            >
              <X className="size-3" />
              Cancel
            </Button>
          </>
        )}

        {job.status === "completed" && (
          <p className="text-[10px] text-muted-foreground">
            Processed {job.processed_items} items
            {job.failed_items > 0 ? `, ${job.failed_items} failed` : ""}
          </p>
        )}

        {job.status === "failed" && job.error_message && (
          <p className="text-[10px] text-destructive line-clamp-2">
            {job.error_message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: IngestionJob["status"] }) {
  if (status === "running" || status === "queued") {
    return (
      <Badge variant="secondary" className="gap-1 text-[10px]">
        <Loader className="size-2.5 animate-spin" />
        {status}
      </Badge>
    );
  }
  if (status === "completed") {
    return (
      <Badge variant="secondary" className="gap-1 text-[10px] bg-green-500/10 text-green-600">
        <CheckCircle className="size-2.5" />
        Done
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="destructive" className="gap-1 text-[10px]">
        <XCircle className="size-2.5" />
        Failed
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="gap-1 text-[10px]">
      {status}
    </Badge>
  );
}
