"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AuditEntry } from "@/types";

const ACTION_LABELS: Record<string, string> = {
  LOGIN: "signed in",
  SIGNUP: "created an account",
  SETTINGS_UPDATED: "updated settings",
  CASE_REVIEW: "marked a case under review",
  CASE_CONFIRMED: "confirmed fraud",
  CASE_DISMISSED: "dismissed a case",
  CASE_ESCALATED: "escalated a case",
  CASE_NOTE_ADDED: "added a note",
};

function label(a: AuditEntry): string {
  return ACTION_LABELS[a.action] ?? a.action.toLowerCase().replace(/_/g, " ");
}

function ago(ts: string): string {
  const s = Math.max(0, (Date.now() - new Date(ts + "Z").getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function AuditWidget() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<AuditEntry[]>([]);

  const load = useCallback(() => {
    api.getAudit(40).then(setEntries).catch(() => {});
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // Light background refresh so the badge reflects new activity while open.
  useEffect(() => {
    if (!open) return;
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [open, load]);

  return (
    <div className="fixed bottom-5 right-5 z-50">
      {open && (
        <div className="mb-3 w-80 max-h-96 overflow-auto rounded-xl border border-gray-200 bg-white shadow-xl">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white">
            <p className="text-sm font-semibold text-gray-700">Activity</p>
            <button onClick={load} className="text-xs text-blue-600 hover:text-blue-800">Refresh</button>
          </div>
          <ul className="divide-y divide-gray-50">
            {entries.length === 0 && (
              <li className="px-4 py-6 text-center text-xs text-gray-400">No activity yet</li>
            )}
            {entries.map((a) => (
              <li key={a.id} className="px-4 py-2.5 text-sm">
                <span className="font-medium text-gray-800">{a.username}</span>{" "}
                <span className="text-gray-500">{label(a)}</span>
                <div className="text-xs text-gray-400 mt-0.5">
                  {ago(a.created_at)}
                  {a.detail ? ` · ${a.detail}` : ""}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full bg-slate-900 text-white text-sm font-medium px-4 py-2.5 shadow-lg hover:bg-slate-800 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        Activity
      </button>
    </div>
  );
}
