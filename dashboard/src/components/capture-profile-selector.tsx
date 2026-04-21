"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { CaptureProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Copy for each capture profile — kept next to the selector so the
 *  settings page and the per-action dropdowns tell the same story. */
export const CAPTURE_PROFILE_META: Record<
  CaptureProfile,
  { label: string; description: string; storage: string; llm: string }
> = {
  raw: {
    label: "Raw",
    description: "Verbatim chunks, zero LLM calls. Maximum fidelity, minimum cost.",
    storage: "1x",
    llm: "none",
  },
  enriched: {
    label: "Enriched",
    description: "LLM topics/entities/importance. Current default.",
    storage: "~1.3x",
    llm: "~1 call",
  },
  dual: {
    label: "Dual",
    description: "Both raw and enriched rows, paired. No compromises.",
    storage: "~2.1x",
    llm: "~1 call",
  },
};

const PROFILES: CaptureProfile[] = ["raw", "enriched", "dual"];

interface CaptureProfileSelectorProps {
  value: CaptureProfile;
  onChange: (profile: CaptureProfile) => void;
  disabled?: boolean;
  /** Compact variant for per-action dropdowns (upload modal). */
  compact?: boolean;
  id?: string;
}

export function CaptureProfileSelector({
  value,
  onChange,
  disabled,
  compact,
  id,
}: CaptureProfileSelectorProps) {
  if (compact) {
    return (
      <div
        id={id}
        role="radiogroup"
        aria-label="Capture profile"
        className="inline-flex rounded-md border bg-muted/40 p-0.5"
      >
        {PROFILES.map((profile) => {
          const active = profile === value;
          return (
            <button
              key={profile}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => onChange(profile)}
              className={cn(
                "rounded px-3 py-1 text-xs font-medium capitalize transition-colors",
                active
                  ? "bg-background shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
                disabled && "opacity-50 cursor-not-allowed",
              )}
            >
              {CAPTURE_PROFILE_META[profile].label}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div
      id={id}
      role="radiogroup"
      aria-label="Capture profile"
      className="grid gap-3 sm:grid-cols-3"
    >
      {PROFILES.map((profile) => {
        const meta = CAPTURE_PROFILE_META[profile];
        const active = profile === value;
        return (
          <button
            key={profile}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(profile)}
            className={cn(
              "flex flex-col items-start gap-2 rounded-lg border p-4 text-left transition-colors",
              active
                ? "border-primary bg-primary/5 ring-1 ring-primary/30"
                : "hover:border-muted-foreground/40",
              disabled && "opacity-60 cursor-not-allowed",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="font-semibold capitalize">{meta.label}</span>
              {profile === "enriched" && (
                <Badge variant="secondary" className="text-[10px]">default</Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{meta.description}</p>
            <div className="mt-auto flex items-center gap-2 text-xs">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                {meta.storage} storage
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono">
                {meta.llm}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

interface ApplyButtonProps {
  current: CaptureProfile;
  pending: CaptureProfile;
  saving: boolean;
  onApply: () => void;
}

export function ApplyCaptureProfileButton({
  current,
  pending,
  saving,
  onApply,
}: ApplyButtonProps) {
  const dirty = pending !== current;
  return (
    <Button
      size="sm"
      variant={dirty ? "default" : "outline"}
      disabled={!dirty || saving}
      onClick={onApply}
    >
      {saving ? "Applying..." : dirty ? "Apply going forward" : "Up to date"}
    </Button>
  );
}
