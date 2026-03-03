"use client";

import { useEffect, useState } from "react";
import type { SnapshotData } from "@/lib/types";

/**
 * Fetch dashboard_data.json as fallback when WS is disconnected.
 * Polls every 5s while active.
 */
export function useFallbackData(active: boolean) {
  const [data, setData] = useState<SnapshotData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;

    let cancelled = false;

    const fetchData = async () => {
      try {
        const res = await fetch("/api/fallback");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to fetch");
        }
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [active]);

  return { data, error };
}
