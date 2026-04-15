"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { Header } from "@/components/layout/header";
import { SkillList } from "@/components/skills/skill-list";
import { SkillEditor } from "@/components/skills/skill-editor";
import { CreateSkillDialog } from "@/components/skills/create-skill-dialog";
import { useSkills } from "@/hooks/use-skills";

export default function SkillsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const { data, isLoading } = useSkills();

  const skills = data?.skills ?? [];

  return (
    <>
      <Header title="Skills" />
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel: skill list */}
        <div className="w-[300px] shrink-0 overflow-hidden">
          <SkillList
            skills={skills}
            isLoading={isLoading}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onCreateClick={() => setCreateOpen(true)}
          />
        </div>

        {/* Right panel: skill editor or empty state */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {selectedId ? (
            <SkillEditor
              key={selectedId}
              skillId={selectedId}
              onDeleted={() => setSelectedId(null)}
            />
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center text-center p-6">
              <Sparkles className="size-12 text-muted-foreground mb-4" />
              <h2 className="text-lg font-semibold">Select a skill</h2>
              <p className="text-sm text-muted-foreground mt-1">
                Choose a skill from the list or create a new one.
              </p>
            </div>
          )}
        </div>
      </div>

      <CreateSkillDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => setSelectedId(id)}
      />
    </>
  );
}
