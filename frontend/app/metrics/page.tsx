"use client";
import { useEffect, useState } from "react";

interface Metrics {
  status: string;
  uptime_seconds: number;
  serving_since: string;
  requests_total: number;
  transactions_total: number;
  transactions_24h: number;
  alerts_total: number;
  alerts_24h: number;
  sessions_total: number;
  latency_avg_ms: number;
  latency_p95_ms: number;
  trend: { day: string; requests: number; transactions: number }[];
}

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
const n = (x: number) => x.toLocaleString("en-US");
function fmtDate(iso: string): string {
  try { return new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200/80 p-5 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums text-gray-900">{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-400 tabular-nums">{sub}</p>}
    </div>
  );
}

export default function MetricsPage() {
  const [m, setM] = useState<Metrics | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    const load = () =>
      fetch("/api/metrics/usage")
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d) => { setM(d); setErr(false); })
        .catch(() => setErr(true));
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  const maxTrend = m ? Math.max(1, ...m.trend.map((t) => Math.max(t.requests, t.transactions))) : 1;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-slate-900 text-white">
        <div className="max-w-5xl mx-auto px-6 py-6 flex items-center justify-between flex-wrap gap-4">
          <div>
            <p className="font-bold text-xl tracking-tight">FMS — Live Metrics</p>
            <p className="text-slate-400 text-sm mt-0.5">Real-time operational metrics of the deployed system</p>
          </div>
          <span className="inline-flex items-center gap-2 text-sm font-medium text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-full pl-2.5 pr-3.5 py-1.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
            </span>
            {m?.status === "operational" ? "Operational" : err ? "Unavailable" : "Checking…"}
          </span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {err && !m ? (
          <div className="text-sm text-red-600">Couldn&apos;t load metrics right now.</div>
        ) : !m ? (
          <div className="text-sm text-gray-400">Loading metrics…</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat label="Uptime" value={fmtUptime(m.uptime_seconds)} sub="this deployment" />
              <Stat label="API requests" value={n(m.requests_total)} sub="total served" />
              <Stat label="Transactions processed" value={n(m.transactions_total)} sub={`${n(m.transactions_24h)} in 24h`} />
              <Stat label="Alerts generated" value={n(m.alerts_total)} sub={`${n(m.alerts_24h)} in 24h`} />
              <Stat label="Sessions" value={n(m.sessions_total)} sub="genuine logins" />
              <Stat label="Response time" value={`${m.latency_avg_ms} ms`} sub={`p95 ${m.latency_p95_ms} ms`} />
              <Stat label="System status" value={<span className="text-emerald-600">🟢 Operational</span>} />
              <Stat label="Last deployment" value={<span className="text-base">{fmtDate(m.serving_since)}</span>} />
            </div>

            <section className="bg-white rounded-xl border border-gray-200/80 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-sm font-semibold text-gray-800">Usage — last 7 days</h2>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-blue-500 inline-block" /> requests</span>
                  <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500 inline-block" /> transactions</span>
                </div>
              </div>
              <div className="flex items-end gap-2 h-40">
                {m.trend.map((t) => (
                  <div key={t.day} className="flex-1 flex flex-col items-center gap-1.5">
                    <div className="w-full flex items-end justify-center gap-1 h-full">
                      <div className="w-1/2 bg-blue-500 rounded-t-sm transition-all duration-500" style={{ height: `${Math.max(2, (t.requests / maxTrend) * 100)}%` }} title={`${t.requests} requests`} />
                      <div className="w-1/2 bg-emerald-500 rounded-t-sm transition-all duration-500" style={{ height: `${Math.max(2, (t.transactions / maxTrend) * 100)}%` }} title={`${t.transactions} transactions`} />
                    </div>
                    <span className="text-[10px] text-gray-400 tabular-nums">{t.day}</span>
                  </div>
                ))}
              </div>
            </section>

            <p className="text-center text-xs text-gray-400">
              Live operational metrics of the deployed FMS system · transaction &amp; alert figures are seeded demo data · refreshes every 30 seconds
            </p>
          </>
        )}
      </main>
    </div>
  );
}
