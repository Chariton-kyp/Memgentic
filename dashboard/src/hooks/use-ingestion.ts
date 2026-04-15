/** TanStack Query hooks for ingestion jobs. */

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";

export function useIngestionJobs() {
  return useQuery({
    queryKey: ["ingestion-jobs"],
    queryFn: () => api.listIngestionJobs(),
    refetchInterval: 3000, // Poll for progress updates
  });
}

export function useIngestionJob(id: string) {
  return useQuery({
    queryKey: ["ingestion-job", id],
    queryFn: () => api.getIngestionJob(id),
    enabled: !!id,
    refetchInterval: 2000,
  });
}

export function useCancelIngestionJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.cancelIngestionJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ingestion-jobs"] });
    },
  });
}
