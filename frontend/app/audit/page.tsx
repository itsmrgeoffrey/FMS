"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AuditEntry } from "@/types";

const ACTION_LABELS: Record<string, string> = {
  LOGIN: "Signed in",
  SIGNUP: "Created account",
  SETTINGS_UPDATED: "Updated settings",
  CASE_REVIEW: "Marked case under review",
  CASE_CONFIRMED: "Confirmed fraud",
  CASE_DISMISSED: "Dismissed case",
  CASE_ESCALATED: "Escalated case",
  CASE_NOTE_ADDED: "Added note",
};

const ACTION_STYLES: Record<string, string> = {
  LOGIN: "bg-slate-100 text-slate-700",
  SIGNUP: "bg-blue-50 text-blue-700",
  SETTINGS_UPDATED: "bg-purple-50 text-purple-700",
  CASE_CONFIRMED: "bg-red-50 text-red-700",
  CASE_DISMISSED: "bg-gray-100 text-gray-600",
  CASE_ESCALATED: "bg-orange-50 text-orange-700",
  CASE_REVIEW: "bg-amber-50 text-amber-700",
  CASE_NOTE_ADDED: "bg-blue-50 text-blue-700",
};

function label(action: string): string {
  return ACTION_LABELS[action] ?? action.toLowerCase().replace(/_/g, " ");
}

function fmtDate(ts: string): string {
  return new Date(ts + "Z").toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "medium" });
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [limit, setLimit] = useState(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.getAudit(limit)
      .then(setEntries)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [limit]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit Trail</h1>
          <p className="text-sm text-gray-500 mt-1">Every user action, who performed it, and when.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {[50, 100, 200].map((n) => <option key={n} value={n}>Last {n}</option>)}
          </select>
          <button
            onClick={load}
            className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="text-sm px-4 py-3 rounded-lg bg-red-50 text-red-700 border border-red-200">{error}</div>}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
                <th className="px-4 py-3 font-medium">Time</th>
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Action</th>
                <th className="px-4 py-3 font-medium">Target</th>
                <th className="px-4 py-3 font-medium">Detail</th>
                <th className="px-4 py-3 font-medium">IP</th>
              </tr>
            </thead>
            <tbody className={loading ? "opacity-50" : ""}>
              {entries.length === 0 && (
                <tr><td colSpan={6} className="text-center py-12 text-gray-400">No activity recorded yet</td></tr>
              )}
              {entries.map((a) => (
                <tr key={a.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">{fmtDate(a.created_at)}</td>
                  <td className="px-4 py-3 font-medium text-gray-800">{a.username}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${ACTION_STYLES[a.action] ?? "bg-gray-100 text-gray-600"}`}>
                      {label(a.action)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">{a.target ? a.target.slice(0, 8) : "—"}</td>
                  <td className="px-4 py-3 text-gray-600 max-w-[240px] truncate">{a.detail || "—"}</td>
                  <td className="px-4 py-3 text-gray-400 font-mono text-xs">{a.ip || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
