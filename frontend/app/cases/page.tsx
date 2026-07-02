"use client";
import { useState } from "react";
import { StatsBar } from "@/components/StatsBar";
import { LiveFeed } from "@/components/LiveFeed";
import { CasesTable } from "@/components/CasesTable";
import { api } from "@/lib/api";

export default function CasesPage() {
  const [refresh, setRefresh] = useState(0);

  return (
    <div className="p-6 space-y-6 max-w-screen-xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Transaction Monitor</h1>
        <div className="flex items-center gap-2">
          <a
            href={api.ctrReportUrl()}
            className="text-xs font-medium px-3 py-1.5 rounded border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100"
          >
            Export CTR (CSV)
          </a>
          <a
            href={api.sarReportUrl()}
            className="text-xs font-medium px-3 py-1.5 rounded border border-amber-200 text-amber-700 bg-amber-50 hover:bg-amber-100"
          >
            Export SAR (CSV)
          </a>
        </div>
      </div>

      {/* Stats */}
      <StatsBar />

      {/* Live feed */}
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Live Alerts</p>
        <LiveFeed onNewCase={() => setRefresh((n) => n + 1)} />
      </div>

      {/* Cases table */}
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">All Cases</p>
        <CasesTable refresh={refresh} />
      </div>
    </div>
  );
}
