"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { Search, Brain, Sparkles, FileText } from "lucide-react";
import { searchMemories } from "@/lib/api";
import { getPlatformConfig } from "@/lib/constants";
import type { SearchResult } from "@/lib/types";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Global Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      // Small delay for the dialog animation
      const timer = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    } else {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
    }
  }, [open]);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (query.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await searchMemories({ query, limit: 10 });
        setResults(data.results);
        setSelectedIndex(0);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const navigateTo = useCallback(
    (id: string) => {
      setOpen(false);
      router.push(`/memories/${id}`);
    },
    [router]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter" && results.length > 0) {
        e.preventDefault();
        navigateTo(results[selectedIndex].memory.id);
      }
    },
    [results, selectedIndex, navigateTo]
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-label="Command palette">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 supports-backdrop-filter:backdrop-blur-xs"
        onClick={() => setOpen(false)}
      />

      {/* Palette */}
      <div className="absolute left-1/2 top-[20%] z-50 w-full max-w-lg -translate-x-1/2">
        <div className="rounded-xl border bg-popover text-popover-foreground shadow-2xl ring-1 ring-foreground/10">
          {/* Search input */}
          <div className="flex items-center gap-2 border-b px-4 py-3">
            <Search className="size-4 text-muted-foreground shrink-0" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search memories, skills..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              aria-label="Search"
            />
            <kbd className="hidden rounded border bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground sm:inline-block">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div className="max-h-80 overflow-y-auto p-2">
            {loading && (
              <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
                Searching...
              </div>
            )}

            {!loading && query.length >= 2 && results.length === 0 && (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <Brain className="size-8 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">No results found</p>
              </div>
            )}

            {!loading && results.length > 0 && (
              <div>
                <p className="px-2 py-1 text-xs font-medium text-muted-foreground">
                  Memories
                </p>
                {results.map((result, index) => {
                  const platform = getPlatformConfig(result.memory.platform);
                  return (
                    <button
                      key={result.memory.id}
                      onClick={() => navigateTo(result.memory.id)}
                      onMouseEnter={() => setSelectedIndex(index)}
                      className={`flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors ${
                        index === selectedIndex
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:bg-muted/50"
                      }`}
                    >
                      <FileText className="size-4 mt-0.5 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm line-clamp-2">
                          {result.memory.content.slice(0, 150)}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <span
                            className="text-[10px] font-medium"
                            style={{ color: platform.color }}
                          >
                            {platform.label}
                          </span>
                          <span className="text-[10px]">
                            {(result.score * 100).toFixed(0)}% match
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            {!loading && query.length < 2 && (
              <div className="py-6 text-center">
                <p className="text-sm text-muted-foreground">
                  Type at least 2 characters to search
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  <QuickLink
                    icon={<Brain className="size-3" />}
                    label="Memories"
                    onClick={() => {
                      setOpen(false);
                      router.push("/");
                    }}
                  />
                  <QuickLink
                    icon={<Sparkles className="size-3" />}
                    label="Skills"
                    onClick={() => {
                      setOpen(false);
                      router.push("/skills");
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function QuickLink({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
    >
      {icon}
      {label}
    </button>
  );
}
