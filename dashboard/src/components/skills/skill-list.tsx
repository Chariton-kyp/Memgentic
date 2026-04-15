"use client";

import { useState } from "react";
import { Search, Plus, FileText, Globe } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { Skill } from "@/lib/types";

interface SkillListProps {
  skills: Skill[];
  isLoading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreateClick: () => void;
}

export function SkillList({
  skills,
  isLoading,
  selectedId,
  onSelect,
  onCreateClick,
}: SkillListProps) {
  const [search, setSearch] = useState("");

  const filtered = search
    ? skills.filter(
        (s) =>
          s.name.toLowerCase().includes(search.toLowerCase()) ||
          s.description.toLowerCase().includes(search.toLowerCase()) ||
          s.tags.some((t) => t.toLowerCase().includes(search.toLowerCase()))
      )
    : skills;

  return (
    <div className="flex h-full flex-col border-r">
      {/* Header */}
      <div className="flex items-center justify-between border-b p-3">
        <h2 className="text-sm font-semibold">Skills</h2>
        <Button size="xs" onClick={onCreateClick}>
          <Plus className="size-3 mr-1" />
          Create
        </Button>
      </div>

      {/* Search */}
      <div className="p-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
          <Input
            placeholder="Search skills..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-xs"
            aria-label="Search skills"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="space-y-2 p-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        )}

        {!isLoading && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-center px-3">
            <p className="text-xs text-muted-foreground">
              {search ? "No skills match your search." : "No skills yet. Create one to get started."}
            </p>
          </div>
        )}

        {!isLoading &&
          filtered.map((skill) => (
            <button
              key={skill.id}
              onClick={() => onSelect(skill.id)}
              className={`w-full text-left px-3 py-3 border-b transition-colors hover:bg-muted/50 ${
                selectedId === skill.id ? "bg-muted" : ""
              }`}
            >
              <p className="text-sm font-medium truncate">{skill.name}</p>
              {skill.description && (
                <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                  {skill.description}
                </p>
              )}
              <div className="flex items-center gap-2 mt-1.5">
                {skill.files.length > 0 && (
                  <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                    <FileText className="size-2.5" />
                    {skill.files.length}
                  </span>
                )}
                {skill.distributions.length > 0 && (
                  <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                    <Globe className="size-2.5" />
                    {skill.distributions.length}
                  </span>
                )}
                {skill.tags.slice(0, 2).map((tag) => (
                  <Badge key={tag} variant="secondary" className="text-[10px] px-1 py-0">
                    {tag}
                  </Badge>
                ))}
              </div>
            </button>
          ))}
      </div>
    </div>
  );
}
