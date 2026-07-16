"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, auth } from "@/lib/api";
import type { Scan314aResult } from "@/types";

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
  const [scan, setScan] = useState<Scan314aResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const isAdmin = auth.user()?.role === "admin";

  const load = useCallback(() => {
    setLoading(true);
    const fetcher = tab === "sar" ? api.getSarReport() : api.getCtrReport();
    fetcher.then((r) => setRows(r.items)).catch(() => setRows([])).finally(() => setLoading(false));
  }, [tab]);
  useEffect(() => { load(); }, [load]);

  const downloadUrl = tab === "sar" ? api.sarReportUrl() : api.ctrReportUrl();
  const xmlUrl = tab === "sar" ? api.sarXmlDraftUrl() : api.ctrXmlDraftUrl();

  async function run314a(file: File) {
    setScanning(true);
    setScanError(null);
    setScan(null);
    try {
      const text = await file.text();
      setScan(await api.scan314a({ csv_text: text }));
    } catch (e) {
      setScanError(String(e));
    } finally {
      setScanning(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reports (SAR / STR)</h1>
          <p className="text-sm text-gray-500 mt-1">Filing worksheets for your compliance officer. Not filed automatically.</p>
        </div>
        <div className="flex gap-2">
          <a href={downloadUrl} className="text-sm font-medium px-3 py-1.5 rounded-lg border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100">
            Export {tab.toUpperCase()} (CSV)
          </a>
          <a href={xmlUrl} title="Batch XML structured after the FinCEN E-Filing format. DRAFT — complete the marked items and validate with FinCEN's batch validator before upload."
            className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 bg-white hover:bg-gray-50">
            Batch XML (draft)
          </a>
        </div>
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

      {/* FinCEN 314(a) scan (admin) */}
      {isAdmin && (
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">FinCEN 314(a) scan</h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Upload the 314(a) subject list (CSV) — FMS scans it against every account holder and counterparty it has seen. The file is scanned in memory and never stored.
              </p>
            </div>
            <label className={`text-sm font-medium px-3 py-1.5 rounded-lg border cursor-pointer ${scanning ? "opacity-50" : "border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100"}`}>
              {scanning ? "Scanning..." : "Upload subject list"}
              <input ref={fileRef} type="file" accept=".csv,.txt" className="hidden" disabled={scanning}
                onChange={(e) => e.target.files?.[0] && run314a(e.target.files[0])} />
            </label>
          </div>
          {scanError && <p className="text-sm text-red-600">{scanError}</p>}
          {scan && !scan.error && (
            <div className="mt-2">
              <p className="text-sm text-gray-700 mb-2">
                <span className="font-semibold">{scan.subjects_screened}</span> subject(s) screened against{" "}
                <span className="font-semibold">{scan.parties_checked}</span> known parties —{" "}
                <span className={`font-semibold ${scan.matches.length ? "text-red-700" : "text-green-700"}`}>
                  {scan.matches.length} match(es)
                </span>
              </p>
              {scan.matches.length > 0 && (
                <div className="overflow-x-auto border border-gray-100 rounded-lg">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
                        <th className="px-3 py-2 font-medium">Subject</th>
                        <th className="px-3 py-2 font-medium">Matched party</th>
                        <th className="px-3 py-2 font-medium">Score</th>
                        <th className="px-3 py-2 font-medium">Seen as</th>
                        <th className="px-3 py-2 font-medium">Accounts</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scan.matches.map((m, i) => (
                        <tr key={i} className="border-b border-gray-50">
                          <td className="px-3 py-2 font-medium text-gray-900">{m.subject}</td>
                          <td className="px-3 py-2 text-gray-700">{m.matched_party}</td>
                          <td className="px-3 py-2 text-gray-600">{Math.round(m.score * 100)}%</td>
                          <td className="px-3 py-2 text-gray-600">{m.seen_as.join(", ")}</td>
                          <td className="px-3 py-2 font-mono text-xs text-gray-600">{m.account_ids.join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="text-[11px] text-gray-400 mt-2">{scan.note}</p>
            </div>
          )}
          {scan?.error && <p className="text-sm text-amber-700">{scan.error}</p>}
        </section>
      )}

      <p className="text-xs text-gray-400">
        Add <code className="font-mono">?format=fincen</code> for Form 111/112 field worksheets, or <code className="font-mono">?format=xml</code> for a draft batch XML (complete and validate in FinCEN&apos;s E-Filing batch validator before upload). FMS prepares filings; it does not transmit them to FinCEN.
      </p>
    </div>
  );
}
