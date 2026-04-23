"use client";

import { Header } from "./Header";
import { useWebSocket } from "@/hooks/useWebSocket";
import { DashboardContext } from "@/context/DashboardContext";

export function AppShell({ children }: { children: React.ReactNode }) {
  const data = useWebSocket();

  return (
    <DashboardContext.Provider value={data}>
      <div className="flex h-screen flex-col overflow-hidden bg-[#080a0e]">
        <Header wsState={data.wsState} />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">{children}</main>
      </div>
    </DashboardContext.Provider>
  );
}
