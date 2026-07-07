"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FraudCaseListItem } from "@/types";

function money(a: number, c: string) {
  const s = c === "USD" ? "$" : c === "NGN" ? "₦" : c + " ";
  return `${s}${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}
function riskColor(r: number | null) {
  const v = r ?? 0;
  return v > 75 ? "bg-red-500" : v > 55 ? "bg-orange-500" : "bg-amber-400";
}

export default function AlertsPage() {
  const [items, setItems] = useState<FraudCaseListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getCases({ limit: 100 })
      .then((p) => setItems(p.items.filter((c) => ["OPEN", "UNDER_REVIEW"].includes(c.status))
        .sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0))))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Alerts</h1>
        <p className="text-sm text-gray-500 mt-1">Open cases requiring review — highest risk first.</p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-3 font-medium">Account</th>
              <th className="px-4 py-3 font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium">Flags</th>
              <th className="px-4 py-3 font-medium">Risk</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium" />
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">No open alerts — all clear.</td></tr>
            )}
            {items.map((c) => (
              <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-gray-800">{c.account_id}</td>
                <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">{money(c.amount, c.currency)}</td>
                <td className="px-4 py-3 text-gray-600">{c.fraud_type ?? "—"}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-1">
                    {c.sanctions_hit && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-red-50 text-red-700 border border-red-200">OFAC</span>}
                    {c.sar_recommended && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">SAR</span>}
                    {c.ctr_required && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-blue-50 text-blue-700 border border-blue-200">CTR</span>}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-bold px-1.5 py-0.5 rounded text-white ${riskColor(c.risk_score)}`}>{c.risk_score}</span>
                </td>
                <td className="px-4 py-3 text-gray-600">{c.status.replace("_", " ")}</td>
                <td className="px-4 py-3 text-right">
                  <Link href={`/cases/${c.id}`} className="text-blue-600 hover:text-blue-800 font-medium text-xs">Review →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
