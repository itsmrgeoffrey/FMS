"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type DateRange } from "@/lib/api";
import DateRangePicker from "@/components/DateRangePicker";
import Pagination from "@/components/Pagination";
import type { FraudCaseListItem } from "@/types";
import { DirectionBadge } from "@/components/ReviewUI";

function money(a: number, c: string) {
  const s = c === "USD" ? "$" : c === "NGN" ? "₦" : c + " ";
  return `${s}${a.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}
function fmtDate(ts: string) {
  return new Date(ts).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });
}

function needsReview(c: FraudCaseListItem) {
  return c.status !== "CLEAN" || c.ctr_required || c.sar_recommended || c.sanctions_hit;
}

function ResultBadge({ c }: { c: FraudCaseListItem }) {
  if (c.ctr_required && c.status === "CLEAN") {
    return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">CTR review</span>;
  }
  if (c.status === "CLEAN") {
    return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-green-50 text-green-700">clean</span>;
  }
  const flags = [
    c.ctr_required ? "CTR" : "",
    c.sar_recommended ? "SAR" : "",
    c.sanctions_hit ? "sanctions" : "",
  ].filter(Boolean);
  const suffix = flags.length ? ` · ${flags.join(" · ")}` : "";
  return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-50 text-red-700">flagged{suffix} · risk {c.risk_score}</span>;
}

export default function TransactionsPage() {
  const [items, setItems] = useState<FraudCaseListItem[]>([]);
  const [filter, setFilter] = useState<"all" | "flagged" | "clean">("all");
  const [direction, setDirection] = useState<"" | "INWARD" | "OUTWARD">("");
  const [range, setRange] = useState<DateRange>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [refresh, setRefresh] = useState(0);
  function startLoading() { setLoading(true); setError(""); }

  useEffect(() => {
    let cancelled = false;
    api.getCases({ limit: 25, page, ...(filter === "all" ? {} : { result: filter }), ...(direction ? { direction } : {}), ...range })
      .then((p) => {
        if (!cancelled) { setItems(p.items); setTotal(p.total); }
      })
      .catch(() => { if (!cancelled) { setItems([]); setError("Unable to load transactions."); } })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range, filter, direction, page, refresh]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-900">Transactions</h1>
          <p className="text-sm text-gray-500 mt-1">Every monitored transaction the engine has analyzed.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <DateRangePicker value={range} onChange={(value) => { startLoading(); setRange(value); setPage(1); }} />
          <label className="sr-only" htmlFor="transaction-direction">Direction</label>
          <select id="transaction-direction" value={direction} onChange={(e) => { startLoading(); setDirection(e.target.value as typeof direction); setPage(1); }} className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">Inward and outward</option><option value="INWARD">Inward</option><option value="OUTWARD">Outward</option>
          </select>
          <div className="flex rounded-lg bg-gray-100 p-1 text-sm font-medium">
            {(["all", "flagged", "clean"] as const).map((f) => (
              <button key={f} onClick={() => { if (f !== filter) { startLoading(); setFilter(f); setPage(1); } }}
                className={`px-3 py-1 rounded-md capitalize transition-colors ${filter === f ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <div role="alert" className="text-sm text-red-700">{error} <button className="underline" onClick={() => { startLoading(); setRefresh((r) => r + 1); }}>Retry</button></div>}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-sm overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-3 font-medium">Time</th>
              <th className="px-4 py-3 font-medium">Account</th>
              <th className="px-4 py-3 font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Dir</th>
              <th className="px-4 py-3 font-medium">Beneficiary / sender</th>
              <th className="px-4 py-3 font-medium">Result</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {!loading && !error && items.length === 0 && (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">
                {range.date_from || range.date_to ? "No transactions in this date range." : "No transactions."}
              </td></tr>
            )}
            {items.map((c) => (
              <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-500 whitespace-nowrap">{fmtDate(c.created_at)}</td>
                <td className="px-4 py-3 font-mono text-gray-800">{c.account_id}</td>
                <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">{money(c.amount, c.currency)}</td>
                <td className="px-4 py-3">
                  <DirectionBadge direction={c.direction} />
                </td>
                <td className="px-4 py-3 text-gray-600 max-w-[160px] truncate">{c.counterparty_name || "—"}</td>
                <td className="px-4 py-3">
                  <ResultBadge c={c} />
                </td>
                <td className="px-4 py-3 text-right">
                  {needsReview(c) && <Link href={`/cases/${c.id}`} className="text-blue-600 hover:text-blue-800 font-medium text-xs">View →</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={page} total={total} limit={25} loading={loading} onChange={(value) => { startLoading(); setPage(value); }} />
    </div>
  );
}
