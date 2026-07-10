"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { StatsBar } from "@/components/StatsBar";
import { LiveFeed } from "@/components/LiveFeed";
import { CasesTable } from "@/components/CasesTable";
import { api } from "@/lib/api";

export default function CasesPage() {
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState("");
  const router = useRouter();

  function runSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q.length >= 2) router.push(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="p-6 space-y-6 max-w-screen-xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900">Transaction Monitor</h1>
        <div className="flex items-center gap-2">
          <form onSubmit={runSearch} className="relative">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search account, counterparty, case…"
              className="text-sm w-64 border border-gray-200 rounded-lg pl-8 pr-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <svg className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </form>
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
