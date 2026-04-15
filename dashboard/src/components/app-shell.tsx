"use client";

import { useState, useCallback, type ReactNode } from "react";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";
import { useWebSocket } from "@/hooks/use-websocket";
import { KeyboardShortcutsDialog } from "@/components/keyboard-shortcuts-dialog";
import { CommandPalette } from "@/components/command-palette";
import { IngestionProgress } from "@/components/ingestion/ingestion-progress";

export function AppShell({ children }: { children: ReactNode }) {
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  useWebSocket();

  const focusSearch = useCallback(() => {
    const searchInput = document.querySelector<HTMLInputElement>(
      'input[placeholder*="Search"], input[placeholder*="search"]'
    );
    if (searchInput) {
      searchInput.focus();
      searchInput.select();
    }
  }, []);

  const handleEscape = useCallback(() => {
    setShortcutsOpen(false);
    const active = document.activeElement;
    if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) {
      active.blur();
    }
  }, []);

  useKeyboardShortcuts([
    { key: "/", description: "Focus search", action: focusSearch },
    { key: "Escape", description: "Clear / close", action: handleEscape },
    {
      key: "?",
      description: "Show keyboard shortcuts",
      action: () => setShortcutsOpen(true),
    },
  ]);

  return (
    <>
      {children}
      <CommandPalette />
      <IngestionProgress />
      <KeyboardShortcutsDialog
        open={shortcutsOpen}
        onOpenChange={setShortcutsOpen}
      />
    </>
  );
}
