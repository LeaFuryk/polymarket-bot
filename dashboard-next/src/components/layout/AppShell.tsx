"use client";

import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useFallbackData } from "@/hooks/useFallbackData";
import { createContext, useContext } from "react";
import type { WSData } from "@/hooks/useWebSocket";
import type { SnapshotData } from "@/lib/types";

// Context to share WS data across pages
const WSContext = createContext<WSData | null>(null);

export function useWSContext(): WSData {
  const ctx = useContext(WSContext);
  if (!ctx) throw new Error("useWSContext must be used within AppShell");
  return ctx;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const ws = useWebSocket();

  // Fallback: fetch dashboard_data.json when WS is offline
  const isOffline = ws.state === "disconnected";
  const fallback = useFallbackData(isOffline && !ws.snapshot);

  // Merge fallback data into snapshot if WS hasn't sent one yet
  const effectiveWs: WSData = {
    ...ws,
    snapshot: ws.snapshot ?? fallback.data,
  };

  return (
    <WSContext.Provider value={effectiveWs}>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Header
            wsState={ws.state}
            botVersion={effectiveWs.snapshot?.bot_version}
          />
          <main className="flex-1 overflow-y-auto p-4 lg:p-6">
            {children}
          </main>
        </div>
      </div>
    </WSContext.Provider>
  );
}
