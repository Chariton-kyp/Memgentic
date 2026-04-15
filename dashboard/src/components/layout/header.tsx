"use client";

import { useState } from "react";
import { useTheme } from "next-themes";
import { Sun, Moon, Activity } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { ActivityFeed } from "@/components/activity/activity-feed";

interface HeaderProps {
  title: string;
  children?: React.ReactNode;
}

export function Header({ title, children }: HeaderProps) {
  const { theme, setTheme } = useTheme();
  const [activityOpen, setActivityOpen] = useState(false);

  return (
    <>
      <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-2 h-4" />
        <h1 className="text-lg font-semibold">{title}</h1>
        <div className="ml-auto flex items-center gap-2">
          {children}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setActivityOpen(true)}
            aria-label="Open activity feed"
          >
            <Activity className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle theme"
          >
            <Sun className="size-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute size-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
          </Button>
        </div>
      </header>
      <ActivityFeed open={activityOpen} onOpenChange={setActivityOpen} />
    </>
  );
}
