"use client";
import { useState } from "react";
import { api, auth } from "@/lib/api";
import type { FraudCase } from "@/types";


const ACTIONS = [
  { key: "REVIEW", label: "Mark Under Review", style: "bg-purple-600 hover:bg-purple-700 text-white" },
  { key: "CONFIRMED", label: "Confirm Fraud", style: "bg-red-600 hover:bg-red-700 text-white" },
  { key: "ESCALATED", label: "Escalate", style: "bg-orange-500 hover:bg-orange-600 text-white" },
  { key: "DISMISSED", label: "Dismiss", style: "bg-gray-200 hover:bg-gray-300 text-gray-800" },
];

const FINAL_STATUSES = new Set(["CONFIRMED_FRAUD", "DISMISSED"]);

export function ActionPanel({
  caseData,
  onUpdate,
}: {
  caseData: FraudCase;
  onUpdate: (updated: FraudCase) => void;
}) {
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const isFinal = FINAL_STATUSES.has(caseData.status);

  async function handleAction(action: string) {
    setLoading(action);
    setError(null);
    try {
      const updated = await api.addAction(caseData.id, action, note.trim() || undefined);
      onUpdate(updated);
      setNote("");
      setPending(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }

  if (caseData.status === "CLEAN" && !caseData.ctr_required && !caseData.sar_recommended && !caseData.sanctions_hit) {
    return (
      <p className="text-sm text-green-600 font-medium">
        No review is currently open for this transaction.
      </p>
    );
  }

  if (isFinal) {
    return (
      <p className="text-sm text-gray-500 italic">
        This case is closed ({caseData.status.replace("_", " ")}). Reporting flags remain separate; closure does not record a filing.
      </p>
    );
  }

  if (auth.user()?.role === "viewer") {
    return (
      <p className="text-sm text-gray-500 italic">
        You have read-only (viewer) access — case actions are disabled for your role.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <label htmlFor="disposition-note" className="block text-xs font-medium text-gray-600">Disposition reason</label>
      <textarea
        id="disposition-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Reason for disposition"
        rows={4}
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
      />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-1">
        {ACTIONS.map((a) => (
          <button
            key={a.key}
            onClick={() => a.key === "CONFIRMED" || a.key === "DISMISSED" ? setPending(a.key) : handleAction(a.key)}
            disabled={loading !== null || pending !== null || (a.key !== "REVIEW" && !note.trim()) || (a.key === "REVIEW" && caseData.status === "UNDER_REVIEW")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${a.style}`}
          >
            {loading === a.key ? "Saving..." : a.label}
          </button>
        ))}
      </div>
      {pending && <div className="border-t border-gray-200 pt-4" role="group" aria-label="Confirm disposition">
        <p className="text-sm font-medium text-gray-800">{pending === "CONFIRMED" ? "Confirm fraud" : "Dismiss"} for {caseData.account_id}?</p>
        <p className="mt-2 text-xs text-gray-500">This closes the case. Reporting flags remain unchanged.</p>
        <div className="mt-3 flex flex-wrap gap-3">
          <button disabled={loading !== null || !note.trim()} onClick={() => handleAction(pending)} className="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">{loading ? "Saving..." : "Confirm decision"}</button>
          <button disabled={loading !== null} onClick={() => setPending(null)} className="px-2 py-2 text-sm text-gray-600">Cancel</button>
        </div>
      </div>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
