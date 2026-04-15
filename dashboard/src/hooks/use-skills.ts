/** TanStack Query hooks for skills. */

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api";
import type { CreateSkillRequest, UpdateSkillRequest } from "@/lib/types";

export function useSkills() {
  return useQuery({
    queryKey: ["skills"],
    queryFn: api.listSkills,
  });
}

export function useSkill(id: string | null) {
  return useQuery({
    queryKey: ["skill", id],
    queryFn: () => api.getSkill(id!),
    enabled: !!id,
  });
}

export function useCreateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateSkillRequest) => api.createSkill(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useUpdateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateSkillRequest }) =>
      api.updateSkill(id, body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["skills"] });
      qc.invalidateQueries({ queryKey: ["skill", variables.id] });
    },
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteSkill(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useDistributeSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, tools }: { id: string; tools: string[] }) =>
      api.distributeSkill(id, tools),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["skill", variables.id] });
    },
  });
}

export function useCreateSkillFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      skillId,
      body,
    }: {
      skillId: string;
      body: { path: string; content: string };
    }) => api.createSkillFile(skillId, body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["skill", variables.skillId] });
    },
  });
}

export function useDeleteSkillFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      skillId,
      fileId,
    }: {
      skillId: string;
      fileId: string;
    }) => api.deleteSkillFile(skillId, fileId),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["skill", variables.skillId] });
    },
  });
}

export function useImportSkillFromGitHub() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (github_url: string) => api.importSkillFromGitHub(github_url),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useRemoveSkillFromTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, tool }: { skillId: string; tool: string }) =>
      api.removeSkillFromTool(skillId, tool),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["skill", variables.skillId] });
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}
