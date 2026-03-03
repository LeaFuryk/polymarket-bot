"use client";

import dynamic from "next/dynamic";

// Skip SSR entirely — the dashboard is a real-time client-side app
// that depends on WebSocket state which doesn't exist on the server.
const AppShell = dynamic(
  () => import("@/components/layout/AppShell").then((m) => m.AppShell),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-screen items-center justify-center bg-[#080a0e]">
        <div className="animate-pulse text-sm text-zinc-500">
          Loading dashboard...
        </div>
      </div>
    ),
  },
);

export default function Template({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
