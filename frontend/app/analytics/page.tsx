"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Dashboard, AnalyticsKpis } from "@/types";

const RISK_COLORS: Record<string, string> = {
  LOW: "bg-green-400", MEDIUM: "bg-amber-400", HIGH: "bg-orange-500", CRITICAL: "bg-red-500",
};

function money(a: number, c: string) {
  const s = c === "USD" ? "$" : c === "NGN" ? "₦" : c + " ";
  return `${s}${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function AnalyticsPage() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [k, setK] = useState<AnalyticsKpis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getDashboard().then(setD).catch((e) => setError(String(e)));
    api.getAnalyticsKpis().then(setK).catch(() => {});
  }, []);

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>;
  if (!d) return <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">Loading…</div>;

  const typeTotal = Math.max(1, d.fraud_types.reduce((s, t) => s + t.count, 0));
  const riskTotal = Math.max(1, d.risk_levels.reduce((s, r) => s + r.count, 0));
  const maxDay = Math.max(1, ...d.activity.map((x) => x.flagged + x.clean));

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
        <p className="text-sm text-gray-500 mt-1">Key indicators and breakdowns across all analyzed activity.</p>
      </div>

      {/* KPIs */}
      {k && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <Kpi
            label="Fraud Loss Prevented"
            value={k.value_flagged.length ? money(k.value_flagged[0].amount, k.value_flagged[0].currency) : "$0"}
            sub="value of flagged transactions"
          />
          <Kpi label="Transactions Processed" value={k.transactions_processed.toLocaleString()} sub={`${k.flagged_total} flagged`} />
          <Kpi label="Alerts Today" value={String(k.alerts_today)} />
          <Kpi label="Open Cases" value={String(k.open_cases)} />
          <Kpi
            label="False Positive Rate"
            value={k.false_positive_rate === null ? "—" : `${Math.round(k.false_positive_rate * 100)}%`}
            sub={k.resolved.total === 0 ? "no reviewed alerts yet" : `${k.resolved.dismissed}/${k.resolved.total} reviewed dismissed`}
          />
        </div>
      )}

      {/* Filing obligations */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white rounded-lg border border-gray-200 p-4"><p className="text-xs text-gray-500 uppercase">CTRs required</p><p className="text-2xl font-bold text-gray-900 mt-1">{d.totals.ctr_required}</p></div>
        <div className="bg-white rounded-lg border border-gray-200 p-4"><p className="text-xs text-gray-500 uppercase">SARs open</p><p className="text-2xl font-bold text-gray-900 mt-1">{d.totals.sar_open}</p></div>
        <div className="bg-white rounded-lg border border-gray-200 p-4"><p className="text-xs text-gray-500 uppercase">Sanctions hits</p><p className="text-2xl font-bold text-gray-900 mt-1">{d.totals.sanctions_hits}</p></div>
        <div className="bg-white rounded-lg border border-gray-200 p-4"><p className="text-xs text-gray-500 uppercase">Confirmed fraud</p><p className="text-2xl font-bold text-gray-900 mt-1">{d.totals.confirmed_fraud}</p></div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Fraud type share */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Fraud type distribution</h2>
          {d.fraud_types.length === 0 ? <p className="text-sm text-gray-400">No flagged cases.</p> : (
            <div className="space-y-3">
              {d.fraud_types.map((t) => (
                <div key={t.type}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-700 capitalize">{t.type}</span>
                    <span className="text-gray-500 font-medium">{t.count} · {Math.round((t.count / typeTotal) * 100)}%</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden"><div className="h-full bg-blue-500 rounded-full" style={{ width: `${(t.count / typeTotal) * 100}%` }} /></div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Risk distribution */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Risk distribution</h2>
          <div className="flex h-4 rounded-full overflow-hidden mb-3">
            {d.risk_levels.filter((r) => r.count > 0).map((r) => (
              <div key={r.level} className={RISK_COLORS[r.level]} style={{ width: `${(r.count / riskTotal) * 100}%` }} title={`${r.level}: ${r.count}`} />
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
            {d.risk_levels.map((r) => (
              <span key={r.level} className="inline-flex items-center gap-1.5">
                <span className={`w-2.5 h-2.5 rounded-sm ${RISK_COLORS[r.level]}`} />{r.level} · {r.count} ({Math.round((r.count / riskTotal) * 100)}%)
              </span>
            ))}
          </div>
        </section>
      </div>

      {/* Activity trend */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Activity — last 14 days</h2>
        <div className="flex items-end gap-1.5 h-36">
          {d.activity.map((x) => {
            const total = x.flagged + x.clean;
            return (
              <div key={x.date} className="flex-1 flex flex-col justify-end h-full group relative">
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 hidden group-hover:block text-xs bg-slate-900 text-white rounded px-1.5 py-0.5 whitespace-nowrap z-10">
                  {x.date.slice(5)}: {x.flagged} flagged, {x.clean} clean
                </div>
                {total === 0 ? <div className="bg-gray-100 rounded-sm" style={{ height: "2px" }} /> : (
                  <>
                    {x.clean > 0 && <div className="bg-gray-300 rounded-t-sm" style={{ height: `${(x.clean / maxDay) * 100}%` }} />}
                    {x.flagged > 0 && <div className={`bg-red-400 ${x.clean === 0 ? "rounded-t-sm" : ""}`} style={{ height: `${(x.flagged / maxDay) * 100}%` }} />}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
