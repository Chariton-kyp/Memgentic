"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SHORTCUT_DEFINITIONS } from "@/hooks/use-keyboard-shortcuts";

interface KeyboardShortcutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center rounded border bg-muted px-1.5 py-0.5 text-xs font-mono font-medium text-muted-foreground">
      {children}
    </kbd>
  );
}

function formatKey(shortcut: (typeof SHORTCUT_DEFINITIONS)[number]) {
  const parts: React.ReactNode[] = [];
  if ("ctrl" in shortcut && shortcut.ctrl) {
    parts.push(<Kbd key="ctrl">Ctrl</Kbd>);
    parts.push(
      <span key="plus" className="text-xs text-muted-foreground mx-0.5">
        +
      </span>
    );
  }
  parts.push(<Kbd key="key">{shortcut.key}</Kbd>);
  return parts;
}

export function KeyboardShortcutsDialog({
  open,
  onOpenChange,
}: KeyboardShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          {SHORTCUT_DEFINITIONS.map((shortcut) => (
            <div
              key={shortcut.key + (("ctrl" in shortcut && shortcut.ctrl) ? "-ctrl" : "")}
              className="flex items-center justify-between"
            >
              <span className="text-sm text-foreground">
                {shortcut.description}
              </span>
              <div className="flex items-center">{formatKey(shortcut)}</div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
