"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Dashboard } from "@/types";

function fmtMoney(amount: number, currency: string) {
  const symbol = currency === "USD" ? "$" : currency === "NGN" ? "₦" : currency + " ";
  return `${symbol}${amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className={`bg-white rounded-lg border border-gray-200 p-4 ${accent ?? ""}`}>
      <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

const RISK_COLORS: Record<string, string> = {
  LOW: "bg-green-400",
  MEDIUM: "bg-amber-400",
  HIGH: "bg-orange-500",
  CRITICAL: "bg-red-500",
};

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
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Monitoring overview — refreshes every 30 seconds.</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard label="Open cases" value={totals.open_cases} sub={`${totals.total_cases} total analyzed`} />
        <StatCard label="Flagged today" value={totals.flagged_today} />
        <StatCard
          label="Sanctions hits"
          value={totals.sanctions_hits}
          accent={totals.sanctions_hits > 0 ? "border-l-4 border-l-red-400" : ""}
        />
        <StatCard
          label="SARs open"
          value={totals.sar_open}
          sub={totals.sar_soonest_deadline_days != null ? `soonest deadline in ${totals.sar_soonest_deadline_days}d` : undefined}
          accent={
            totals.sar_soonest_deadline_days != null && totals.sar_soonest_deadline_days <= 7
              ? "border-l-4 border-l-amber-400"
              : ""
          }
        />
        <StatCard label="CTR required" value={totals.ctr_required} />
        <StatCard label="Confirmed fraud" value={totals.confirmed_fraud} />
      </div>

      {/* Amount under investigation */}
      {amounts_open.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide mb-2">Amount under investigation (open cases)</p>
          <div className="flex flex-wrap gap-6">
            {amounts_open.map((a) => (
              <p key={a.currency} className="text-3xl font-bold text-gray-900">
                {fmtMoney(a.total, a.currency)}
                <span className="text-sm font-medium text-gray-400 ml-2">{a.currency}</span>
              </p>
            ))}
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        {/* 14-day activity */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700">Activity — last 14 days</h2>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-red-400 inline-block" /> flagged</span>
              <span className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-gray-300 inline-block" /> clean</span>
            </div>
          </div>
          <div className="flex items-end gap-1.5 h-36">
            {activity.map((d) => {
              const total = d.flagged + d.clean;
              return (
                <div key={d.date} className="flex-1 flex flex-col justify-end h-full group relative">
                  <div className="absolute -top-6 left-1/2 -translate-x-1/2 hidden group-hover:block text-xs bg-slate-900 text-white rounded px-1.5 py-0.5 whitespace-nowrap z-10">
                    {d.date.slice(5)}: {d.flagged} flagged, {d.clean} clean
                  </div>
                  {total === 0 ? (
                    <div className="bg-gray-100 rounded-sm" style={{ height: "2px" }} />
                  ) : (
                    <>
                      {d.clean > 0 && <div className="bg-gray-300 rounded-t-sm" style={{ height: `${(d.clean / maxDay) * 100}%` }} />}
                      {d.flagged > 0 && <div className={`bg-red-400 ${d.clean === 0 ? "rounded-t-sm" : ""}`} style={{ height: `${(d.flagged / maxDay) * 100}%` }} />}
                    </>
                  )}
                </div>
              );
            })}
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-2">
            <span>{activity[0]?.date.slice(5)}</span>
            <span>today</span>
          </div>
        </section>

        {/* Fraud types */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Fraud types detected</h2>
          {fraud_types.length === 0 ? (
            <p className="text-sm text-gray-400">No flagged cases yet.</p>
          ) : (
            <div className="space-y-3">
              {fraud_types.map((t) => (
                <div key={t.type}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-700 capitalize">{t.type}</span>
                    <span className="text-gray-500 font-medium">{t.count}</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${(t.count / maxType) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Risk distribution */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Risk distribution</h2>
        <div className="flex h-4 rounded-full overflow-hidden">
          {risk_levels.filter((r) => r.count > 0).map((r) => (
            <div key={r.level} className={RISK_COLORS[r.level]} style={{ width: `${(r.count / riskTotal) * 100}%` }} title={`${r.level}: ${r.count}`} />
          ))}
        </div>
        <div className="flex flex-wrap gap-4 mt-3 text-xs text-gray-500">
          {risk_levels.map((r) => (
            <span key={r.level} className="inline-flex items-center gap-1.5">
              <span className={`w-2.5 h-2.5 rounded-sm inline-block ${RISK_COLORS[r.level]}`} />
              {r.level} · {r.count}
            </span>
          ))}
        </div>
      </section>

      {/* Needs attention */}
      <section className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Needs attention — highest risk open cases</h2>
          <Link href="/cases" className="text-xs text-blue-600 hover:text-blue-800 font-medium">All cases →</Link>
        </div>
        {attention.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-gray-400">Nothing open. All clear.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {attention.map((c) => (
                <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-3 font-mono text-gray-800">{c.account_id}</td>
                  <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">{fmtMoney(c.amount, c.currency)}</td>
                  <td className="px-4 py-3 text-gray-600">{c.fraud_type ?? "—"}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {c.sanctions_hit && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-red-50 text-red-700 border border-red-200">OFAC</span>}
                      {c.sar_recommended && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">SAR</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded text-white ${
                      (c.risk_score ?? 0) > 75 ? "bg-red-500" : (c.risk_score ?? 0) > 55 ? "bg-orange-500" : "bg-amber-400"
                    }`}>
                      {c.risk_score}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/cases/${c.id}`} className="text-blue-600 hover:text-blue-800 font-medium text-xs">View →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
