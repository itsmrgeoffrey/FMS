function riskLevel(score: number): { label: string; bar: string; text: string } {
  if (score <= 30) return { label: "LOW", bar: "bg-emerald-500", text: "text-emerald-700" };
  if (score <= 55) return { label: "MEDIUM", bar: "bg-amber-400", text: "text-amber-700" };
  if (score <= 75) return { label: "HIGH", bar: "bg-orange-500", text: "text-orange-700" };
  return { label: "CRITICAL", bar: "bg-red-600", text: "text-red-700" };
}

export function RiskScoreBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined) return <span className="text-gray-300 text-xs">—</span>;
  const { bar, text } = riskLevel(score);
  return (
    <div className="flex items-center gap-2 min-w-[72px]">
      <div className="w-14 h-1.5 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`text-xs font-semibold tabular-nums ${text}`}>{score}</span>
    </div>
  );
}

export function RiskScoreGauge({ score }: { score: number | null }) {
  if (score === null || score === undefined) return null;
  const { label, bar, text } = riskLevel(score);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500 font-medium">Risk Score</span>
        <span className={`font-bold ${text}`}>{score}/100 — {label}</span>
      </div>
      <div className="w-full h-2 rounded-full bg-gray-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${bar}`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}
