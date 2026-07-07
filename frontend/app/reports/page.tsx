"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Row = Record<string, unknown>;

function money(a: unknown, c: unknown) {
  const amt = Number(a) || 0;
  const cur = String(c || "USD");
  const s = cur === "USD" ? "$" : cur === "NGN" ? "₦" : cur + " ";
  return `${s}${amt.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

export default function ReportsPage() {
  const [tab, setTab] = useState<"sar" | "ctr">("sar");
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    const fetcher = tab === "sar" ? api.getSarReport() : api.getCtrReport();
    fetcher.then((r) => setRows(r.items)).catch(() => setRows([])).finally(() => setLoading(false));
  }, [tab]);
  useEffect(() => { load(); }, [load]);

  const downloadUrl = tab === "sar" ? api.sarReportUrl() : api.ctrReportUrl();

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reports (SAR / STR)</h1>
          <p className="text-sm text-gray-500 mt-1">Filing worksheets for your compliance officer. Not filed automatically.</p>
        </div>
        <a href={downloadUrl} className="text-sm font-medium px-3 py-1.5 rounded-lg border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100">
          Export {tab.toUpperCase()} (CSV)
        </a>
      </div>

      <div className="flex rounded-lg bg-gray-100 p-1 text-sm font-medium w-fit">
        {(["sar", "ctr"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md uppercase transition-colors ${tab === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}>
            {t === "sar" ? "SAR / STR" : "CTR"}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-2 border-b border-gray-100 text-xs text-gray-500">{rows.length} record(s)</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3 font-medium">Counterparty</th>
                {tab === "sar" ? (
                  <>
                    <th className="px-4 py-3 font-medium">Type</th>
                    <th className="px-4 py-3 font-medium">Filing deadline</th>
                    <th className="px-4 py-3 font-medium">Days left</th>
                  </>
                ) : (
                  <th className="px-4 py-3 font-medium">CTR trigger</th>
                )}
              </tr>
            </thead>
            <tbody className={loading ? "opacity-50" : ""}>
              {!loading && rows.length === 0 && (
                <tr><td colSpan={6} className="text-center py-12 text-gray-400">No {tab.toUpperCase()} records.</td></tr>
              )}
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-gray-800">{String(r.account_id ?? "")}</td>
                  <td className="px-4 py-3 font-semibold text-gray-900 whitespace-nowrap">{money(r.amount, r.currency)}</td>
                  <td className="px-4 py-3 text-gray-600 max-w-[180px] truncate">{String(r.counterparty_name ?? "—")}</td>
                  {tab === "sar" ? (
                    <>
                      <td className="px-4 py-3 text-gray-600">{String(r.fraud_type ?? "—")}</td>
                      <td className="px-4 py-3 text-gray-600">{String(r.filing_deadline ?? "—")}</td>
                      <td className="px-4 py-3">
                        {(() => {
                          const dl = Number(r.days_remaining);
                          const cls = dl <= 7 ? "bg-red-50 text-red-700" : dl <= 14 ? "bg-amber-50 text-amber-700" : "bg-gray-100 text-gray-600";
                          return <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${cls}`}>{isNaN(dl) ? "—" : `${dl}d`}</span>;
                        })()}
                      </td>
                    </>
                  ) : (
                    <td className="px-4 py-3 text-gray-500 text-xs max-w-[320px] truncate">{String(r.ctr_reason ?? "—")}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-gray-400">
        Add <code className="font-mono">?format=fincen</code> to the report endpoints for Form 111/112 field worksheets. FMS prepares filings; it does not transmit them to FinCEN.
      </p>
    </div>
  );
}
