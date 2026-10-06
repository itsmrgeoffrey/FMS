"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type DateRange } from "@/lib/api";
import DateRangePicker from "@/components/DateRangePicker";
import type { FraudCaseListItem } from "@/types";

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
    return <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">CTR required</span>;
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
  const [range, setRange] = useState<DateRange>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.getCases({ limit: 100, ...range })
      .then((p) => {
        if (!cancelled) setItems(p.items);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range]);

  const shown = items.filter((c) =>
    filter === "all" ? true : filter === "clean" ? !needsReview(c) : needsReview(c)
  );

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-900">Transactions</h1>
          <p className="text-sm text-gray-500 mt-1">Every monitored transaction the engine has analyzed.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <DateRangePicker value={range} onChange={setRange} />
          <div className="flex rounded-lg bg-gray-100 p-1 text-sm font-medium">
            {(["all", "flagged", "clean"] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-md capitalize transition-colors ${filter === f ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200/80 shadow-sm overflow-hidden">
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
              <tr><td colSpan={7} className="text-center py-12 text-gray-400">
                {range.date_from || range.date_to ? "No transactions in this date range." : "No transactions."}
              </td></tr>
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
    </div>
  );
}
