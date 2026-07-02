"use client";
import { useState } from "react";
import Link from "next/link";
import { useWebSocket } from "@/lib/useWebSocket";
import type { WsNewCase } from "@/types";
import { ConfidenceBadge } from "./ConfidenceBadge";

interface Alert {
  id: string;
  account_id: string;
  amount: number;
  currency: string;
  direction: string;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  fraud_type: string | null;
  created_at: string;
}

export function LiveFeed({ onNewCase }: { onNewCase?: () => void }) {
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useWebSocket((data) => {
    const msg = data as WsNewCase;
    if (msg.event === "new_case") {
      setAlerts((prev) => [msg.case, ...prev].slice(0, 5));
      onNewCase?.();
    }
  });

  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-2 px-4 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-500">
        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse inline-block" />
        Monitoring live — no new alerts
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {alerts.map((a) => (
        <Link
          key={a.id}
          href={`/cases/${a.id}`}
          className="flex items-center gap-3 px-4 py-2.5 bg-red-50 border border-red-200 rounded-lg text-sm hover:bg-red-100 transition-colors"
        >
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse shrink-0" />
          <span className="font-semibold text-red-800">
            {a.currency} {a.amount.toLocaleString()} {a.direction}
          </span>
          <span className="text-red-700">· Account {a.account_id}</span>
          {a.fraud_type && <span className="text-red-600">· {a.fraud_type}</span>}
          <span className="ml-auto"><ConfidenceBadge confidence={a.confidence} /></span>
        </Link>
      ))}
    </div>
  );
}
