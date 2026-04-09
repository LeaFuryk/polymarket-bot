"use client";

import { createContext, useContext } from "react";
import type { DashboardData } from "@/hooks/useWebSocket";

const DashboardContext = createContext<DashboardData | null>(null);

export function useDashboard(): DashboardData {
  const ctx = useContext(DashboardContext);
  if (!ctx)
    throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}

export { DashboardContext };
