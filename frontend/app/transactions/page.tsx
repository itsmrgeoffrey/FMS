"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FraudCaseListItem } from "@/types";

function money(a: number, c: string) {
  const s = c === "USD" ? "$" : c === "NGN" ? "₦" : c + " ";
  return `${s}${a.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}
function fmtDate(ts: string) {
  return new Date(ts).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });
}

export default function TransactionsPage() {
  const [items, setItems] = useState<FraudCaseListItem[]>([]);
  const [filter, setFilter] = useState<"all" | "flagged" | "clean">("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.getCases({ limit: 100 }).then((p) => setItems(p.items)).catch(() => {}).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const shown = items.filter((c) =>
    filter === "all" ? true : filter === "clean" ? c.status === "CLEAN" : c.status !== "CLEAN"
  );

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Transactions</h1>
          <p className="text-sm text-gray-500 mt-1">Every monitored transaction the engine has analyzed.</p>
        </div>
        <div className="flex rounded-lg bg-gray-100 p-1 text-sm font-medium">
          {(["all", "flagged", "clean"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-md capitalize transition-colors ${filter === f ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-3 font-medium">Time</th>
              <th className="px-4 py-3 font-medium">Account</th>
              <th className="px-4 py-3 font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Dir</th>
              <th className="px-4 py-3 font-medium">Counterparty</th>
              <th className="px-4 py-3 font-medium">Result</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {!loading && shown.length === 0 && (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">No transactions.</td></tr>
            )}
            {shown.map((c) => (
              <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-500 whitespace-nowrap">{fmtDate(c.created_at)}</td>
                <td className="px-4 py-3 font-mono text-gray-800">{c.account_id}</td>
                <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">{money(c.amount, c.currency)}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${c.direction === "INWARD" ? "bg-green-50 text-green-700" : "bg-orange-50 text-orange-700"}`}>{c.direction}</span>
                </td>
                <td className="px-4 py-3 text-gray-600 max-w-[160px] truncate">{c.counterparty_name || "—"}</td>
                <td className="px-4 py-3">
                  {c.status === "CLEAN" ? (
                    <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-green-50 text-green-700">clean</span>
                  ) : (
                    <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-50 text-red-700">flagged · risk {c.risk_score}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  {c.status !== "CLEAN" && <Link href={`/cases/${c.id}`} className="text-blue-600 hover:text-blue-800 font-medium text-xs">View →</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
