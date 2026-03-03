"use client";

import { useState } from "react";
import { useWSContext } from "@/components/layout/AppShell";
import { useStatusData } from "@/hooks/useStatusData";
import { InfraHealth } from "@/components/status/InfraHealth";
import { ExecutionQuality } from "@/components/status/ExecutionQuality";

type Tab = "infra" | "execution";

export default function StatusPage() {
  const ws = useWSContext();
  const { infra, execution } = useStatusData(ws);
  const [tab, setTab] = useState<Tab>("infra");

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-200">Live Status</h1>
        <div className="flex rounded-lg border border-white/5 bg-[#0d1017] p-0.5">
          {(["infra", "execution"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-4 py-1.5 text-xs font-medium transition-colors ${
                tab === t
                  ? "bg-white/5 text-zinc-100"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {t === "infra" ? "Infrastructure" : "Execution"}
            </button>
          ))}
        </div>
      </div>

      {tab === "infra" ? (
        <InfraHealth
          apiLatencies={infra.api_latencies}
          wsClients={infra.ws_clients}
          sqliteQueueDepth={infra.sqlite_queue_depth}
          prefilter={infra.prefilter}
          monitor={infra.monitor}
        />
      ) : (
        <ExecutionQuality
          risk={execution.risk}
          ensemble={execution.ensemble}
          aiCooldown={execution.ai_cooldown}
          lastTrigger={execution.last_trigger}
          gatePipeline={execution.gate_pipeline}
        />
      )}
    </div>
  );
}
