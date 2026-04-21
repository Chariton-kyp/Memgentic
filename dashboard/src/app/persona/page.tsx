"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Header } from "@/components/layout/header";
import {
  acceptPersonaBootstrap,
  bootstrapPersona,
  getPersona,
  putPersona,
} from "@/lib/api";
import type {
  Persona,
  PersonaPerson,
  PersonaProject,
} from "@/lib/types";
import {
  Plus,
  Sparkles,
  Save,
  RotateCcw,
  CheckCircle2,
  XCircle,
  ShieldCheck,
} from "lucide-react";

function emptyPersona(): Persona {
  return {
    version: 1,
    identity: {
      name: "Assistant",
      role: "Memory-enabled AI assistant",
      tone: "helpful, concise",
      pronouns: null,
      voice_sample: null,
    },
    people: [],
    projects: [],
    preferences: { remember: [], avoid: [] },
    metadata: {
      workspace_inherit: false,
      updated_at: null,
      generated_by: "manual",
    },
  };
}

function linesToList(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

function listToLines(items: string[] | undefined): string {
  return (items ?? []).join("\n");
}

export default function PersonaPage() {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [rememberText, setRememberText] = useState("");
  const [avoidText, setAvoidText] = useState("");

  const [bootstrapOpen, setBootstrapOpen] = useState(false);
  const [bootstrapLoading, setBootstrapLoading] = useState(false);
  const [proposed, setProposed] = useState<Persona | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const current = await getPersona();
      setPersona(current);
      setRememberText(listToLines(current.preferences.remember));
      setAvoidText(listToLines(current.preferences.avoid));
    } catch (err) {
      toast.error(`Failed to load persona: ${(err as Error).message}`);
      const fallback = emptyPersona();
      setPersona(fallback);
      setRememberText("");
      setAvoidText("");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSave = useCallback(async () => {
    if (!persona) return;
    const payload: Persona = {
      ...persona,
      preferences: {
        remember: linesToList(rememberText),
        avoid: linesToList(avoidText),
      },
    };
    setSaving(true);
    try {
      const saved = await putPersona(payload);
      setPersona(saved);
      toast.success("Persona saved");
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [persona, rememberText, avoidText]);

  const handleBootstrap = useCallback(async () => {
    setBootstrapLoading(true);
    try {
      const resp = await bootstrapPersona({ source: "recent", limit: 100 });
      setProposed(resp.persona);
      setBootstrapOpen(true);
    } catch (err) {
      toast.error(`Bootstrap failed: ${(err as Error).message}`);
    } finally {
      setBootstrapLoading(false);
    }
  }, []);

  const handleAcceptBootstrap = useCallback(async () => {
    if (!proposed) return;
    try {
      const saved = await acceptPersonaBootstrap(proposed);
      setPersona(saved);
      setRememberText(listToLines(saved.preferences.remember));
      setAvoidText(listToLines(saved.preferences.avoid));
      setProposed(null);
      setBootstrapOpen(false);
      toast.success("Persona bootstrapped");
    } catch (err) {
      toast.error(`Accept failed: ${(err as Error).message}`);
    }
  }, [proposed]);

  const handleReset = useCallback(async () => {
    const fallback = emptyPersona();
    try {
      const saved = await putPersona(fallback);
      setPersona(saved);
      setRememberText("");
      setAvoidText("");
      toast.success("Reset to defaults");
    } catch (err) {
      toast.error(`Reset failed: ${(err as Error).message}`);
    }
  }, []);

  const rawYaml = useMemo(
    () => (persona ? JSON.stringify(persona, null, 2) : ""),
    [persona],
  );
  const proposedYaml = useMemo(
    () => (proposed ? JSON.stringify(proposed, null, 2) : ""),
    [proposed],
  );

  // Line-by-line unified-diff approximation. Keeps us dependency-free —
  // vitest isn't runnable without node_modules, so we avoid pulling in
  // jsdiff just for this view.
  const bootstrapDiff = useMemo(() => {
    if (!persona || !proposed) return "";
    const oldLines = rawYaml.split("\n");
    const newLines = proposedYaml.split("\n");
    const max = Math.max(oldLines.length, newLines.length);
    const out: string[] = ["--- current", "+++ proposed"];
    for (let i = 0; i < max; i += 1) {
      const a = oldLines[i] ?? "";
      const b = newLines[i] ?? "";
      if (a === b) {
        out.push("  " + a);
      } else {
        if (a) out.push("- " + a);
        if (b) out.push("+ " + b);
      }
    }
    return out.join("\n");
  }, [persona, proposed, rawYaml, proposedYaml]);

  const validatePersona = useCallback(() => {
    if (!persona) return;
    const issues: string[] = [];
    if (!persona.identity.name?.trim()) {
      issues.push("identity.name is required");
    }
    for (const [idx, person] of persona.people.entries()) {
      if (!person.name?.trim()) {
        issues.push(`people[${idx}].name is required`);
      }
    }
    for (const [idx, proj] of persona.projects.entries()) {
      if (!proj.name?.trim()) {
        issues.push(`projects[${idx}].name is required`);
      }
      if (!["active", "paused", "archived"].includes(proj.status)) {
        issues.push(`projects[${idx}].status must be active|paused|archived`);
      }
    }
    if (issues.length === 0) {
      toast.success("Persona is valid");
    } else {
      toast.error(`Invalid: ${issues.join("; ")}`);
    }
  }, [persona]);

  function updateIdentity<K extends keyof Persona["identity"]>(
    key: K,
    value: Persona["identity"][K],
  ) {
    if (!persona) return;
    setPersona({ ...persona, identity: { ...persona.identity, [key]: value } });
  }

  function updatePerson(idx: number, patch: Partial<PersonaPerson>) {
    if (!persona) return;
    const people = persona.people.map((p, i) =>
      i === idx ? { ...p, ...patch } : p,
    );
    setPersona({ ...persona, people });
  }

  function removePerson(idx: number) {
    if (!persona) return;
    setPersona({
      ...persona,
      people: persona.people.filter((_, i) => i !== idx),
    });
  }

  function addPerson() {
    if (!persona) return;
    setPersona({
      ...persona,
      people: [
        ...persona.people,
        { name: "", relationship: "", preferences: [], do_not: [] },
      ],
    });
  }

  function updateProject(idx: number, patch: Partial<PersonaProject>) {
    if (!persona) return;
    const projects = persona.projects.map((p, i) =>
      i === idx ? { ...p, ...patch } : p,
    );
    setPersona({ ...persona, projects });
  }

  function removeProject(idx: number) {
    if (!persona) return;
    setPersona({
      ...persona,
      projects: persona.projects.filter((_, i) => i !== idx),
    });
  }

  function addProject() {
    if (!persona) return;
    setPersona({
      ...persona,
      projects: [
        ...persona.projects,
        { name: "", status: "active", stack: [], tldr: "" },
      ],
    });
  }

  if (loading || !persona) {
    return (
      <>
        <Header title="Persona" />
        <div className="p-6 text-sm text-muted-foreground">Loading persona...</div>
      </>
    );
  }

  return (
    <>
      <Header title="Persona" />
      <div className="flex-1 overflow-auto p-6 space-y-6 max-w-4xl">
        {/* Identity */}
        <Card>
          <CardHeader>
            <CardTitle>Identity</CardTitle>
            <CardDescription>
              The agent&apos;s self-concept — used at the top of every session.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="text-sm font-medium" htmlFor="name">
                Name
              </label>
              <Input
                id="name"
                value={persona.identity.name}
                onChange={(e) => updateIdentity("name", e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium" htmlFor="role">
                Role
              </label>
              <Input
                id="role"
                value={persona.identity.role ?? ""}
                onChange={(e) => updateIdentity("role", e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium" htmlFor="tone">
                Tone
              </label>
              <Input
                id="tone"
                value={persona.identity.tone ?? ""}
                onChange={(e) => updateIdentity("tone", e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium" htmlFor="voice">
                Voice sample
              </label>
              <Textarea
                id="voice"
                rows={3}
                value={persona.identity.voice_sample ?? ""}
                onChange={(e) => updateIdentity("voice_sample", e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        {/* People */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>People</CardTitle>
              <CardDescription>Humans this agent knows about.</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={addPerson}>
              <Plus className="size-4 mr-1" /> Add
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            {persona.people.length === 0 ? (
              <p className="text-sm text-muted-foreground">No people yet.</p>
            ) : (
              persona.people.map((person, idx) => (
                <div key={idx} className="space-y-2 border rounded-md p-3">
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      placeholder="Name"
                      value={person.name}
                      onChange={(e) =>
                        updatePerson(idx, { name: e.target.value })
                      }
                    />
                    <Input
                      placeholder="Relationship"
                      value={person.relationship ?? ""}
                      onChange={(e) =>
                        updatePerson(idx, { relationship: e.target.value })
                      }
                    />
                  </div>
                  <Input
                    placeholder="Preferences (comma separated)"
                    value={(person.preferences ?? []).join(", ")}
                    onChange={(e) =>
                      updatePerson(idx, {
                        preferences: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                  <Input
                    placeholder="Do-not (comma separated)"
                    value={(person.do_not ?? []).join(", ")}
                    onChange={(e) =>
                      updatePerson(idx, {
                        do_not: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                  <div className="flex justify-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removePerson(idx)}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Projects */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Projects</CardTitle>
              <CardDescription>Active work the agent tracks.</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={addProject}>
              <Plus className="size-4 mr-1" /> Add
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            {persona.projects.length === 0 ? (
              <p className="text-sm text-muted-foreground">No projects yet.</p>
            ) : (
              persona.projects.map((project, idx) => (
                <div key={idx} className="space-y-2 border rounded-md p-3">
                  <div className="grid grid-cols-2 gap-2">
                    <Input
                      placeholder="Name"
                      value={project.name}
                      onChange={(e) =>
                        updateProject(idx, { name: e.target.value })
                      }
                    />
                    <select
                      className="h-9 rounded-md border bg-background px-3 text-sm"
                      value={project.status}
                      onChange={(e) =>
                        updateProject(idx, {
                          status: e.target.value as PersonaProject["status"],
                        })
                      }
                    >
                      <option value="active">active</option>
                      <option value="paused">paused</option>
                      <option value="archived">archived</option>
                    </select>
                  </div>
                  <Input
                    placeholder="Stack (comma separated)"
                    value={(project.stack ?? []).join(", ")}
                    onChange={(e) =>
                      updateProject(idx, {
                        stack: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                  <Input
                    placeholder="TL;DR"
                    value={project.tldr ?? ""}
                    onChange={(e) =>
                      updateProject(idx, { tldr: e.target.value })
                    }
                  />
                  <div className="flex justify-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeProject(idx)}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Preferences */}
        <Card>
          <CardHeader>
            <CardTitle>Preferences</CardTitle>
            <CardDescription>
              One item per line. The agent reads these at session start.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium" htmlFor="remember">
                Remember
              </label>
              <Textarea
                id="remember"
                rows={6}
                value={rememberText}
                onChange={(e) => setRememberText(e.target.value)}
                placeholder={"decisions with rationale\nnaming conventions"}
              />
            </div>
            <div>
              <label className="text-sm font-medium" htmlFor="avoid">
                Avoid
              </label>
              <Textarea
                id="avoid"
                rows={6}
                value={avoidText}
                onChange={(e) => setAvoidText(e.target.value)}
                placeholder={"apology-heavy responses\nunrelated refactors during bug fixes"}
              />
            </div>
          </CardContent>
        </Card>

        {/* Advanced */}
        <Card>
          <CardHeader>
            <CardTitle>Advanced</CardTitle>
            <CardDescription>
              Workspace inheritance (active when Phase C ships) and raw view.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={persona.metadata.workspace_inherit}
                onCheckedChange={(v) =>
                  setPersona({
                    ...persona,
                    metadata: {
                      ...persona.metadata,
                      workspace_inherit: Boolean(v),
                    },
                  })
                }
              />
              Inherit workspace persona (no-op until Phase C)
            </label>
            <div>
              <label className="text-sm font-medium" htmlFor="raw">
                Raw view (read-only)
              </label>
              <Textarea
                id="raw"
                rows={10}
                readOnly
                value={rawYaml}
                className="font-mono text-xs"
              />
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline">
                generated_by: {persona.metadata.generated_by}
              </Badge>
              {persona.metadata.updated_at && (
                <Badge variant="outline">
                  updated_at: {persona.metadata.updated_at}
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Actions */}
        <Card>
          <CardHeader>
            <CardTitle>Actions</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={handleSave} disabled={saving}>
              <Save className="size-4 mr-1" />
              {saving ? "Saving..." : "Save"}
            </Button>
            <Button
              variant="outline"
              onClick={handleBootstrap}
              disabled={bootstrapLoading}
            >
              <Sparkles className="size-4 mr-1" />
              {bootstrapLoading ? "Asking LLM..." : "Bootstrap from memories"}
            </Button>
            <Button variant="outline" onClick={validatePersona}>
              <ShieldCheck className="size-4 mr-1" />
              Validate
            </Button>
            <Button variant="outline" onClick={refresh}>
              <RotateCcw className="size-4 mr-1" />
              Revert
            </Button>
            <Button variant="ghost" onClick={handleReset}>
              Reset to default
            </Button>
          </CardContent>
        </Card>
      </div>

      <Dialog open={bootstrapOpen} onOpenChange={setBootstrapOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Review proposed persona</DialogTitle>
            <DialogDescription>
              The LLM scanned your recent memories and proposed the card
              below. The diff is relative to the persona currently on disk;
              nothing is saved until you accept.
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-3">
            <div>
              <label className="text-sm font-medium">Diff (current vs. proposed)</label>
              <Textarea
                rows={14}
                readOnly
                value={bootstrapDiff}
                className="font-mono text-xs"
              />
            </div>
            <div>
              <label className="text-sm font-medium">Proposed persona</label>
              <Textarea
                rows={10}
                readOnly
                value={proposedYaml}
                className="font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setBootstrapOpen(false);
                setProposed(null);
              }}
            >
              <XCircle className="size-4 mr-1" />
              Discard
            </Button>
            <Button onClick={handleAcceptBootstrap}>
              <CheckCircle2 className="size-4 mr-1" />
              Accept
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Separator />
    </>
  );
}
