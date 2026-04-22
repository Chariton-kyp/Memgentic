"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { hasApiKey } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100/api/v1";

export function AuthGuard({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  // ``setChecked`` is called from an async probe of the API health endpoint
  // — a legitimate React→external-system sync that
  // ``react-hooks/set-state-in-effect`` flags by default. The flag is
  // one-way (false → true only), so the cascading-renders failure mode
  // the rule warns about cannot occur.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (pathname === "/login") {
      setChecked(true);
      return;
    }

    // If we already have an API key, proceed
    if (hasApiKey()) {
      setChecked(true);
      return;
    }

    // No API key — check if the API requires one (local mode = no auth needed)
    fetch(`${API_BASE}/health`)
      .then((res) => {
        if (res.ok) {
          // API responds without key — local mode, no auth needed
          setChecked(true);
        } else if (res.status === 401) {
          // API requires auth — redirect to login
          router.replace("/login");
        } else {
          // API unreachable or error — let user through, pages will show errors
          setChecked(true);
        }
      })
      .catch(() => {
        // API unreachable — let user through
        setChecked(true);
      });
  }, [pathname, router]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (!checked && pathname !== "/login") {
    return null;
  }

  return <>{children}</>;
}
