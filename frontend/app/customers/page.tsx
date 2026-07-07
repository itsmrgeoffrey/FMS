"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Customer } from "@/types";

function money(a: number, c: string | null) {
  const cur = c || "USD";
  const s = cur === "USD" ? "$" : cur === "NGN" ? "₦" : cur + " ";
  return `${s}${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}
function riskBadge(r: number | null) {
  const v = r ?? 0;
  const cls = v > 75 ? "bg-red-500" : v > 55 ? "bg-orange-500" : v > 30 ? "bg-amber-400" : "bg-green-400";
  return <span className={`text-xs font-bold px-1.5 py-0.5 rounded text-white ${cls}`}>{r ?? "—"}</span>;
}

export default function CustomersPage() {
  const [items, setItems] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getCustomers(200).then((r) => setItems(r.items)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Customers</h1>
        <p className="text-sm text-gray-500 mt-1">Accounts seen by the monitor, ranked by peak risk.</p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
              <th className="px-4 py-3 font-medium">Account</th>
              <th className="px-4 py-3 font-medium">Transactions</th>
              <th className="px-4 py-3 font-medium">Flagged</th>
              <th className="px-4 py-3 font-medium">Open</th>
              <th className="px-4 py-3 font-medium">Total volume</th>
              <th className="px-4 py-3 font-medium">Peak risk</th>
              <th className="px-4 py-3 font-medium">Flags</th>
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {!loading && items.length === 0 && (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">No accounts yet.</td></tr>
            )}
            {items.map((c) => (
              <tr key={c.account_id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-gray-800">{c.account_id}</td>
                <td className="px-4 py-3 text-gray-700">{c.transactions}</td>
                <td className="px-4 py-3 text-gray-700">{c.flagged}</td>
                <td className="px-4 py-3">
                  {c.open > 0 ? <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-amber-50 text-amber-700">{c.open} open</span> : <span className="text-gray-300">—</span>}
                </td>
                <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">{money(c.total_amount, c.currency)}</td>
                <td className="px-4 py-3">{riskBadge(c.max_risk)}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-1">
                    {c.sanctions_hits > 0 && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-red-50 text-red-700 border border-red-200">OFAC</span>}
                    {c.sar_count > 0 && <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-amber-50 text-amber-700 border border-amber-200">SAR</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
