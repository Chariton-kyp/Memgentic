/** TanStack Query hooks for memories, sources, stats. */

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";

export function useMemories(params: {
  page?: number;
  page_size?: number;
  source?: string;
  content_type?: string;
}) {
  return useQuery({
    queryKey: ["memories", params],
    queryFn: () => api.listMemories(params),
  });
}

export function useMemory(id: string) {
  return useQuery({
    queryKey: ["memory", id],
    queryFn: () => api.getMemory(id),
    enabled: !!id,
  });
}

export function useSearch(query: string, options?: { sources?: string[]; content_types?: string[]; limit?: number }) {
  return useQuery({
    queryKey: ["search", query, options],
    queryFn: () => api.searchMemories({ query, ...options }),
    enabled: query.length >= 2,
  });
}

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: api.getSources,
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: api.getStats,
  });
}

export function useGraphData(minWeight?: number) {
  return useQuery({
    queryKey: ["graph", minWeight],
    queryFn: () => api.getGraphData(minWeight),
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useCreateMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function usePinnedMemories() {
  return useQuery({
    queryKey: ["memories", "pinned"],
    queryFn: api.getPinnedMemories,
  });
}

export function usePinMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.pinMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      qc.invalidateQueries({ queryKey: ["memories", "pinned"] });
      qc.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}

export function useUnpinMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.unpinMemory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      qc.invalidateQueries({ queryKey: ["memories", "pinned"] });
      qc.invalidateQueries({ queryKey: ["memory"] });
    },
  });
}

export function useUploadText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.uploadText,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useUploadFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      metadata,
    }: {
      file: File;
      metadata?: { topics?: string[]; content_type?: string };
    }) => api.uploadFile(file, metadata),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memories"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}

export function useTopics() {
  return useQuery({
    queryKey: ["topics"],
    queryFn: api.listTopics,
  });
}
