"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { hasApiKey } from "@/lib/api";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { ErrorBoundary } from "@/components/error-boundary";
import { AppShell } from "@/components/app-shell";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100/api/v1";

export function AuthLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  const isLoginPage = pathname === "/login";
  // `/welcome` is the public pitch page — no sidebar, no auth probe.
  // Mirrors the login page's chrome-less treatment.
  const isWelcomePage = pathname === "/welcome";
  const isPublicPage = isLoginPage || isWelcomePage;

  useEffect(() => {
    if (isPublicPage) {
      setChecked(true);
      return;
    }

    // Already have an API key — proceed
    if (hasApiKey()) {
      setChecked(true);
      return;
    }

    // No API key — check if the API requires one
    // If health endpoint responds OK without a key, we're in local mode
    fetch(`${API_BASE}/health`)
      .then((res) => {
        if (res.ok) {
          // Local mode — no auth required
          setChecked(true);
        } else if (res.status === 401) {
          // API requires auth — redirect to login
          router.replace("/login");
        } else {
          // Other error — let through, pages will show errors
          setChecked(true);
        }
      })
      .catch(() => {
        // API unreachable — let through, pages will show connection errors
        setChecked(true);
      });
  }, [isPublicPage, router]);

  // Public pages (login, welcome pitch): render without sidebar chrome
  if (isPublicPage) {
    return <>{children}</>;
  }

  // Not yet checked: render nothing to prevent flash
  if (!checked) {
    return null;
  }

  // Render full app shell with sidebar
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <ErrorBoundary>
          <AppShell>{children}</AppShell>
        </ErrorBoundary>
      </SidebarInset>
    </SidebarProvider>
  );
}
