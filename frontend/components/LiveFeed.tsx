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
      <div className="flex items-center gap-2.5 px-4 py-2.5 bg-gray-50/60 border border-gray-200/80 rounded-xl text-sm text-gray-500">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
        </span>
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
          className="flex items-center gap-3 px-4 py-2.5 bg-red-50 border border-red-200/80 rounded-xl text-sm shadow-sm hover:bg-red-100 transition-colors"
        >
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse shrink-0" />
          <span className="font-semibold text-red-800 tabular-nums">
            {a.currency} {a.amount.toLocaleString()} {a.direction}
          </span>
          <span className="text-red-700 font-mono text-xs">· {a.account_id}</span>
          {a.fraud_type && <span className="text-red-600 capitalize">· {a.fraud_type}</span>}
          <span className="ml-auto"><ConfidenceBadge confidence={a.confidence} /></span>
        </Link>
      ))}
    </div>
  );
}
