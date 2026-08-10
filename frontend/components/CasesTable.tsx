"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FraudCaseListItem, CasesPage } from "@/types";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { StatusBadge } from "./StatusBadge";
import { RiskScoreBadge } from "./RiskScoreBadge";

const STATUSES = ["", "CLEAN", "OPEN", "UNDER_REVIEW", "CONFIRMED_FRAUD", "DISMISSED", "ESCALATED"];
const CONFIDENCES = ["", "HIGH", "MEDIUM", "LOW"];

function fmt(amount: number, currency: string) {
  const symbol = currency === "USD" ? "$" : currency === "NGN" ? "₦" : currency + " ";
  return `${symbol}${amount.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

function fmtDate(ts: string) {
  return new Date(ts).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });
}

export function CasesTable({ refresh }: { refresh?: number }) {
  const [data, setData] = useState<CasesPage | null>(null);
  const [status, setStatus] = useState("");
  const [confidence, setConfidence] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.getCases({ status: status || undefined, confidence: confidence || undefined, page, limit: 20 })
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [status, confidence, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (refresh) load(); }, [refresh, load]);

  const selectCls = "text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500";

  return (
    <div className="bg-white rounded-xl border border-gray-200/80 shadow-sm overflow-hidden">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 px-4 py-3 border-b border-gray-100 bg-gray-50/60">
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className={selectCls}>
          {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </select>
        <select value={confidence} onChange={(e) => { setConfidence(e.target.value); setPage(1); }} className={selectCls}>
          {CONFIDENCES.map((c) => <option key={c} value={c}>{c || "All confidence"}</option>)}
        </select>
        <span className="ml-auto text-xs text-gray-400 self-center tabular-nums">
          {data ? `${data.total} cases` : ""}
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-gray-400 uppercase tracking-wider border-b border-gray-100 bg-gray-50/40">
              <th className="px-4 py-2.5 font-semibold">Time</th>
              <th className="px-4 py-2.5 font-semibold">Account</th>
              <th className="px-4 py-2.5 font-semibold">Narration</th>
              <th className="px-4 py-2.5 font-semibold text-right">Amount</th>
              <th className="px-4 py-2.5 font-semibold">Dir</th>
              <th className="px-4 py-2.5 font-semibold">Counterparty</th>
              <th className="px-4 py-2.5 font-semibold">Fraud Type</th>
              <th className="px-4 py-2.5 font-semibold">Filings</th>
              <th className="px-4 py-2.5 font-semibold">Risk</th>
              <th className="px-4 py-2.5 font-semibold">Confidence</th>
              <th className="px-4 py-2.5 font-semibold">Status</th>
              <th className="px-4 py-2.5 font-semibold" />
            </tr>
          </thead>
          <tbody className={`divide-y divide-gray-50 ${loading ? "opacity-50" : ""}`}>
            {data?.items.length === 0 && (
              <tr>
                <td colSpan={12} className="text-center py-12 text-gray-400">No transactions yet</td>
              </tr>
            )}
            {data?.items.map((c: FraudCaseListItem) => (
              <tr key={c.id} className="hover:bg-gray-50/70 transition-colors">
                <td className="px-4 py-3 text-gray-500 whitespace-nowrap tabular-nums">{fmtDate(c.created_at)}</td>
                <td className="px-4 py-3 font-mono text-[13px] text-gray-800">{c.account_id}</td>
                <td className="px-4 py-3 text-gray-500 text-xs max-w-[160px] truncate">{c.reference || "—"}</td>
                <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap text-right tabular-nums">{fmt(c.amount, c.currency)}</td>
                <td className="px-4 py-3">
                  <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${c.direction === "INWARD" ? "bg-emerald-50 text-emerald-700" : "bg-orange-50 text-orange-700"}`}>
                    {c.direction}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600 max-w-[160px] truncate">{c.counterparty_name || "—"}</td>
                <td className="px-4 py-3 text-gray-600 capitalize">{c.fraud_type || "—"}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {c.sanctions_hit && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide text-white bg-red-500">OFAC</span>}
                    {c.ctr_required && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide bg-blue-50 text-blue-700 border border-blue-200">CTR</span>}
                    {c.sar_recommended && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide bg-orange-50 text-orange-700 border border-orange-200">SAR</span>}
                  </div>
                </td>
                <td className="px-4 py-3"><RiskScoreBadge score={c.risk_score} /></td>
                <td className="px-4 py-3"><ConfidenceBadge confidence={c.confidence} /></td>
                <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                <td className="px-4 py-3">
                  <Link href={`/cases/${c.id}`} className="text-blue-600 hover:text-blue-800 font-medium text-xs whitespace-nowrap">
                    View →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
