"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Stats } from "@/types";

function StatCard({ label, value, tone }: { label: string; value: number; tone?: "alert" | "warn" }) {
  return (
    <div className="relative bg-white rounded-xl border border-gray-200/80 p-4 shadow-sm hover:shadow-md transition-shadow duration-200 overflow-hidden">
      {tone === "alert" && <span className="absolute left-0 top-3 bottom-3 w-1 rounded-r-full bg-red-500" />}
      {tone === "warn" && <span className="absolute left-0 top-3 bottom-3 w-1 rounded-r-full bg-amber-400" />}
      <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">{label}</p>
      <p className={`mt-2 text-[28px] leading-none font-semibold tracking-tight tabular-nums ${tone === "alert" ? "text-red-600" : "text-gray-900"}`}>
        {value}
      </p>
    </div>
  );
}

export function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    api.getStats().then(setStats).catch(console.error);
    const id = setInterval(() => api.getStats().then(setStats).catch(console.error), 30000);
    return () => clearInterval(id);
  }, []);

  if (!stats) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200/80 h-[88px] animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard label="Flagged Today" value={stats.flagged_today} />
      <StatCard label="High Confidence" value={stats.high_confidence} tone="alert" />
      <StatCard label="Pending Review" value={stats.pending_review} tone="warn" />
      <StatCard label="Confirmed Fraud" value={stats.confirmed_fraud} tone="alert" />
    </div>
  );
}
