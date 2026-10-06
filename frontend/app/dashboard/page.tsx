"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import type { Dashboard } from "@/types";
import { LoadError, money, RefreshButton, ReviewTable, words } from "@/components/ReviewUI";

const riskColours: Record<string, string> = { LOW: "bg-emerald-500", MEDIUM: "bg-amber-400", HIGH: "bg-orange-500", CRITICAL: "bg-red-600" };

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [updated, setUpdated] = useState<Date | null>(null);
  useEffect(() => {
    let active = true;
    let pending = false;
    async function load() {
      if (pending) return;
      pending = true;
      try {
        const next = await api.getDashboard();
        if (active) { setData(next); setError(""); setUpdated(new Date()); }
      } catch (e) { if (active) setError(String(e)); }
      finally { pending = false; if (active) setLoading(false); }
    }
    void load();
    const timer = setInterval(load, 30000);
    return () => { active = false; clearInterval(timer); };
  }, [refresh]);
  function reload() { setLoading(true); setRefresh(v => v + 1); }
  const maxActivity = Math.max(1, ...(data?.activity.map(day => day.flagged + day.clean) ?? []));
  const rated = data?.risk_levels.reduce((sum, level) => sum + level.count, 0) ?? 0;

  return <div className="review-page space-y-7">
    <header className="flex items-start justify-between gap-4">
      <div><p className="mb-1 text-xs font-medium text-gray-500">Overview</p><h1>Dashboard</h1>
        <p className="mt-2 text-xs text-gray-500" role="status">{updated ? `Updated ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}${error ? " - refresh failed" : ""}` : error ? "Overview unavailable" : "Loading overview..."}</p></div>
      <RefreshButton loading={loading} onClick={reload} />
    </header>
    {error && <LoadError message={error} retry={reload} />}
    {!data && !error && <div role="status" className="h-48 animate-pulse border-y border-gray-200 bg-white p-6 text-sm text-gray-500">Loading dashboard...</div>}
    {data && <>
      <dl className="grid grid-cols-2 border-y border-gray-200 bg-white lg:grid-cols-4">
        {[
          ["Awaiting review", data.totals.open_cases, "Current queue", "text-blue-700"],
          ["Flagged today", data.totals.flagged_today, "Created today", "text-gray-900"],
          ["SAR recommendations", data.totals.sar_open, "Open cases", "text-amber-700"],
          ["Confirmed fraud", data.totals.confirmed_fraud, "All time", "text-red-700"],
        ].map(([label, value, scope, colour]) => <div key={label} className="min-w-0 border-b border-r border-gray-100 p-4 last:border-r-0 lg:border-b-0 lg:p-5">
          <dt className="text-xs font-medium text-gray-500">{label}</dt><dd className={`mt-2 text-3xl font-semibold tabular-nums ${colour}`}>{Number(value).toLocaleString()}</dd><dd className="mt-1 text-xs text-gray-500">{scope}</dd>
        </div>)}
      </dl>
      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2>Priority queue <span className="ml-2 text-xs font-normal text-gray-500">Highest risk first</span></h2>
          <Link href="/alerts" className="inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:underline">All alerts <ArrowRight size={15} /></Link></div>
        <ReviewTable items={data.attention} loading={loading} empty="No transactions awaiting review." />
      </section>
      <section className="grid gap-6 border-y border-gray-200 py-5 lg:grid-cols-[2fr_1fr]">
        <div><h2 className="mb-4">Value awaiting review</h2><dl className="flex flex-wrap gap-x-10 gap-y-4">
          {data.amounts_open.length ? data.amounts_open.map(amount => <div key={amount.currency} className="min-w-0"><dt className="text-xs text-gray-500">{amount.currency}</dt><dd className="mt-1 break-words text-lg font-semibold tabular-nums">{money(amount.total, amount.currency)}</dd></div>) : <div className="text-sm text-gray-500"><dt>No open exposure</dt></div>}
        </dl></div>
        <div className="space-y-3 text-sm lg:border-l lg:border-gray-200 lg:pl-6"><h2>Review indicators <span className="text-xs font-normal text-gray-500">All time</span></h2>
          <div className="flex justify-between gap-3"><span className="text-gray-600">CTR flags</span><strong className="tabular-nums text-blue-700">{data.totals.ctr_required}</strong></div>
          <div className="flex justify-between gap-3"><span className="text-gray-600">Possible sanctions matches</span><strong className="tabular-nums text-red-700">{data.totals.sanctions_hits}</strong></div>
        </div>
      </section>
      <div className="grid gap-8 xl:grid-cols-[2fr_1fr]">
        <section className="min-w-0"><div className="flex flex-wrap justify-between gap-3"><h2>Transaction activity <span className="text-xs font-normal text-gray-500">14 days</span></h2>
          <div className="flex gap-4 text-xs text-gray-500"><span className="flex items-center gap-1.5"><i className="h-2 w-2 bg-red-400" />Flagged</span><span className="flex items-center gap-1.5"><i className="h-2 w-2 bg-gray-200" />Unflagged</span></div></div>
          <div className="mt-6 flex h-44 items-end gap-1.5 border-b border-gray-200 sm:gap-3" aria-label="Daily transaction counts">
            {data.activity.map(day => <div key={day.date} tabIndex={0} aria-label={`${day.date}: ${day.flagged} flagged, ${day.clean} unflagged`} title={`${day.date}: ${day.flagged} flagged, ${day.clean} unflagged`} className="group flex h-full min-w-0 flex-1 flex-col justify-end outline-offset-2">
              <div className="bg-gray-200" style={{ height: `${day.clean / maxActivity * 100}%` }} /><div className="bg-red-400 group-hover:bg-red-500" style={{ height: `${day.flagged / maxActivity * 100}%` }} />
            </div>)}
          </div>
          <div className="mt-2 flex justify-between text-xs text-gray-500"><span>{data.activity[0]?.date}</span><span>{data.activity.at(-1)?.date}</span></div>
        </section>
        <section><h2 className="mb-5">Risk distribution <span className="text-xs font-normal text-gray-500">All time</span></h2>
          <div className="space-y-4">{data.risk_levels.map(level => <div key={level.level}><div className="mb-1.5 flex justify-between text-xs"><span className="text-gray-600">{words(level.level)}</span><span className="font-medium tabular-nums">{level.count}</span></div><div className="h-1.5 overflow-hidden rounded bg-gray-100"><div className={`h-full ${riskColours[level.level]}`} style={{ width: `${rated ? level.count / rated * 100 : 0}%` }} /></div></div>)}</div>
        </section>
      </div>
      <section className="review-section"><h2 className="mb-4">Detection categories <span className="text-xs font-normal text-gray-500">All time</span></h2>
        <ul className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">{data.fraud_types.map(type => <li key={type.type} className="flex justify-between gap-4 border-b border-gray-100 py-3 text-sm"><span className="break-words text-gray-600">{words(type.type)}</span><span className="font-medium tabular-nums">{type.count}</span></li>)}</ul>
        {!data.fraud_types.length && <p className="text-sm text-gray-500">No detection categories recorded.</p>}
      </section>
    </>}
  </div>;
}
