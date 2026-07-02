"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { FraudCase } from "@/types";

const ACTOR_KEY = "fms.actor";

const ACTIONS = [
  { key: "REVIEW", label: "Mark Under Review", style: "bg-purple-600 hover:bg-purple-700 text-white" },
  { key: "CONFIRMED", label: "Confirm Fraud", style: "bg-red-600 hover:bg-red-700 text-white" },
  { key: "ESCALATED", label: "Escalate", style: "bg-orange-500 hover:bg-orange-600 text-white" },
  { key: "DISMISSED", label: "Dismiss", style: "bg-gray-200 hover:bg-gray-300 text-gray-800" },
];

const FINAL_STATUSES = new Set(["CONFIRMED_FRAUD", "DISMISSED", "CLEAN"]);

export function ActionPanel({
  caseData,
  onUpdate,
}: {
  caseData: FraudCase;
  onUpdate: (updated: FraudCase) => void;
}) {
  const [note, setNote] = useState("");
  const [actor, setActor] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Remember the officer's name across cases so the audit trail is attributed.
  useEffect(() => {
    setActor(localStorage.getItem(ACTOR_KEY) || "");
  }, []);

  const isFinal = FINAL_STATUSES.has(caseData.status);

  async function handleAction(action: string) {
    setLoading(action);
    setError(null);
    try {
      const trimmed = actor.trim();
      if (trimmed) localStorage.setItem(ACTOR_KEY, trimmed);
      const updated = await api.addAction(caseData.id, action, note || undefined, trimmed || undefined);
      onUpdate(updated);
      setNote("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(null);
    }
  }

  if (caseData.status === "CLEAN") {
    return (
      <p className="text-sm text-green-600 font-medium">
        Transaction passed AI review — no action required.
      </p>
    );
  }

  if (isFinal) {
    return (
      <p className="text-sm text-gray-500 italic">
        This case is closed ({caseData.status.replace("_", " ")}).
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <input
        value={actor}
        onChange={(e) => setActor(e.target.value)}
        placeholder="Your name (recorded in the audit trail)"
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Optional note for this action..."
        rows={2}
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
      />
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map((a) => (
          <button
            key={a.key}
            onClick={() => handleAction(a.key)}
            disabled={loading !== null}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${a.style}`}
          >
            {loading === a.key ? "Saving..." : a.label}
          </button>
        ))}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
