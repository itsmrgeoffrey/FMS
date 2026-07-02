"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Stats } from "@/types";

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-5 py-4 flex flex-col gap-1">
      <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
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
          <div key={i} className="bg-white rounded-lg border border-gray-200 px-5 py-4 h-20 animate-pulse bg-gray-50" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard label="Flagged Today" value={stats.flagged_today} color="text-gray-900" />
      <StatCard label="High Confidence" value={stats.high_confidence} color="text-red-600" />
      <StatCard label="Pending Review" value={stats.pending_review} color="text-amber-600" />
      <StatCard label="Confirmed Fraud" value={stats.confirmed_fraud} color="text-red-700" />
    </div>
  );
}
