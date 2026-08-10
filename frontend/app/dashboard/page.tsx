"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Dashboard } from "@/types";

function fmtMoney(amount: number, currency: string) {
  const symbol = currency === "USD" ? "$" : currency === "NGN" ? "₦" : currency + " ";
  return `${symbol}${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

type Tone = "alert" | "warn" | undefined;

function StatTile({ label, value, sub, tone }: { label: string; value: string | number; sub?: React.ReactNode; tone?: Tone }) {
  return (
    <div className="relative bg-white rounded-xl border border-gray-200/80 p-4 shadow-sm hover:shadow-md transition-shadow duration-200 overflow-hidden">
      {tone === "alert" && <span className="absolute left-0 top-3 bottom-3 w-1 rounded-r-full bg-red-500" />}
      {tone === "warn" && <span className="absolute left-0 top-3 bottom-3 w-1 rounded-r-full bg-amber-400" />}
      <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">{label}</p>
      <p className={`mt-2 text-[28px] leading-none font-semibold tracking-tight tabular-nums ${tone === "alert" ? "text-red-600" : "text-gray-900"}`}>
        {value}
      </p>
      {sub && <p className="mt-2 text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

const RISK_BAR: Record<string, string> = {
  LOW: "bg-emerald-500",
  MEDIUM: "bg-amber-400",
  HIGH: "bg-orange-500",
  CRITICAL: "bg-red-500",
};

function riskChip(score: number | null | undefined) {
  const s = score ?? 0;
  const cls = s > 75 ? "text-red-600" : s > 55 ? "text-orange-600" : "text-amber-600";
  const bar = s > 75 ? "bg-red-500" : s > 55 ? "bg-orange-500" : "bg-amber-400";
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-10 rounded-full bg-gray-100 overflow-hidden">
        <span className={`block h-full rounded-full ${bar}`} style={{ width: `${Math.min(100, s)}%` }} />
      </span>
      <span className={`text-sm font-semibold tabular-nums ${cls}`}>{score ?? "—"}</span>
    </span>
  );
}

function stripeFor(score: number | null | undefined) {
  const s = score ?? 0;
  return s > 75 ? "bg-red-500" : s > 55 ? "bg-orange-500" : "bg-amber-400";
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getDashboard().then(setData).catch((e) => setError(String(e)));
    const id = setInterval(() => api.getDashboard().then(setData).catch(() => {}), 30000);
    return () => clearInterval(id);
  }, []);

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>;
  if (!data) return <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">Loading dashboard…</div>;

  const { totals, activity, fraud_types, risk_levels, amounts_open, attention } = data;
  const maxDay = Math.max(1, ...activity.map((d) => d.flagged + d.clean));
  const maxType = Math.max(1, ...fraud_types.map((t) => t.count));
  const riskTotal = Math.max(1, risk_levels.reduce((s, r) => s + r.count, 0));

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Monitoring overview · refreshes every 30 seconds</p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatTile label="Open cases" value={totals.open_cases} sub={`of ${totals.total_cases} analyzed`} />
        <StatTile label="Flagged today" value={totals.flagged_today} />
        <StatTile
          label="Sanctions hits"
          value={totals.sanctions_hits}
          tone={totals.sanctions_hits > 0 ? "alert" : undefined}
          sub={totals.sanctions_hits > 0 ? "block or reject" : undefined}
        />
        <StatTile
          label="SARs open"
          value={totals.sar_open}
          tone={totals.sar_soonest_deadline_days != null && totals.sar_soonest_deadline_days <= 7 ? "warn" : undefined}
          sub={totals.sar_soonest_deadline_days != null ? `soonest · ${totals.sar_soonest_deadline_days}d` : undefined}
        />
        <StatTile label="CTR required" value={totals.ctr_required} />
        <StatTile label="Confirmed fraud" value={totals.confirmed_fraud} />
      </div>

      {/* Amount under investigation */}
      {amounts_open.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200/80 p-5 shadow-sm">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">Amount under investigation · open cases</p>
          <div className="flex flex-wrap gap-x-10 gap-y-2 mt-3">
            {amounts_open.map((a) => (
              <p key={a.currency} className="text-[32px] leading-none font-semibold tracking-tight text-gray-900 tabular-nums">
                {fmtMoney(a.total, a.currency)}
                <span className="text-sm font-medium text-gray-400 ml-2 align-middle">{a.currency}</span>
              </p>
            ))}
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* 14-day activity */}
        <section className="bg-white rounded-xl border border-gray-200/80 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-sm font-semibold text-gray-800">Activity · last 14 days</h2>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-red-400 inline-block" /> flagged</span>
              <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-gray-200 inline-block" /> clean</span>
            </div>
          </div>
          <div className="flex items-end gap-1.5 h-36">
            {activity.map((d) => {
              const total = d.flagged + d.clean;
              return (
                <div key={d.date} className="flex-1 flex flex-col justify-end h-full group relative">
                  <div className="absolute -top-7 left-1/2 -translate-x-1/2 hidden group-hover:block text-[11px] bg-slate-900 text-white rounded-md px-2 py-1 whitespace-nowrap z-10 shadow-lg">
                    {d.date.slice(5)} · <span className="tabular-nums">{d.flagged}</span> flagged, <span className="tabular-nums">{d.clean}</span> clean
                  </div>
                  {total === 0 ? (
                    <div className="bg-gray-100 rounded-full" style={{ height: "3px" }} />
                  ) : (
                    <div className="flex flex-col justify-end rounded-md overflow-hidden transition-opacity group-hover:opacity-90" style={{ height: `${(total / maxDay) * 100}%` }}>
                      {d.clean > 0 && <div className="bg-gray-200" style={{ height: `${(d.clean / total) * 100}%` }} />}
                      {d.flagged > 0 && <div className="bg-red-400" style={{ height: `${(d.flagged / total) * 100}%` }} />}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-2.5 tabular-nums">
            <span>{activity[0]?.date.slice(5)}</span>
            <span>today</span>
          </div>
        </section>

        {/* Fraud types */}
        <section className="bg-white rounded-xl border border-gray-200/80 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-800 mb-5">Fraud types detected</h2>
          {fraud_types.length === 0 ? (
            <p className="text-sm text-gray-400">No flagged cases yet.</p>
          ) : (
            <div className="space-y-3.5">
              {fraud_types.map((t) => (
                <div key={t.type}>
                  <div className="flex justify-between text-sm mb-1.5">
                    <span className="text-gray-700 capitalize">{t.type}</span>
                    <span className="text-gray-500 font-semibold tabular-nums">{t.count}</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${(t.count / maxType) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Risk distribution */}
      <section className="bg-white rounded-xl border border-gray-200/80 p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-gray-800 mb-4">Risk distribution</h2>
        <div className="flex h-4 rounded-full overflow-hidden gap-0.5">
          {risk_levels.filter((r) => r.count > 0).map((r) => (
            <div key={r.level} className={`${RISK_BAR[r.level]} first:rounded-l-full last:rounded-r-full`} style={{ width: `${(r.count / riskTotal) * 100}%` }} title={`${r.level}: ${r.count}`} />
          ))}
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-2 mt-4 text-xs">
          {risk_levels.map((r) => (
            <span key={r.level} className="inline-flex items-center gap-2 text-gray-600">
              <span className={`w-2.5 h-2.5 rounded-sm inline-block ${RISK_BAR[r.level]}`} />
              <span className="font-medium">{r.level}</span>
              <span className="text-gray-400 tabular-nums">{r.count}</span>
            </span>
          ))}
        </div>
      </section>

      {/* Needs attention */}
      <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800">Needs attention · highest-risk open cases</h2>
          <Link href="/cases" className="text-xs text-blue-600 hover:text-blue-800 font-medium">All cases →</Link>
        </div>
        {attention.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-gray-400">Nothing open. All clear.</p>
        ) : (
          <div className="divide-y divide-gray-50">
            {attention.map((c) => (
              <Link
                key={c.id}
                href={`/cases/${c.id}`}
                className="group grid grid-cols-[3px_1.1fr_auto_1.3fr_auto_auto] items-center gap-4 pr-5 hover:bg-gray-50/70 transition-colors"
              >
                <span className={`self-stretch ${stripeFor(c.risk_score)}`} />
                <div className="py-3.5 font-mono text-[13px] text-gray-800">{c.account_id}</div>
                <div className="py-3.5 text-right font-semibold text-gray-900 tabular-nums whitespace-nowrap">{fmtMoney(c.amount, c.currency)}</div>
                <div className="py-3.5 text-sm text-gray-500 capitalize">{c.fraud_type ?? "—"}</div>
                <div className="py-3.5 flex gap-1.5 justify-end">
                  {c.sanctions_hit && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide text-white bg-red-500">OFAC</span>}
                  {c.sar_recommended && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide text-orange-700 bg-orange-50 border border-orange-200">SAR</span>}
                </div>
                <div className="py-3.5 pl-2 justify-self-end">{riskChip(c.risk_score)}</div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
