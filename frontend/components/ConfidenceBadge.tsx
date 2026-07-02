const styles: Record<string, string> = {
  HIGH: "bg-red-100 text-red-700 border border-red-300",
  MEDIUM: "bg-amber-100 text-amber-700 border border-amber-300",
  LOW: "bg-yellow-100 text-yellow-700 border border-yellow-200",
};

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${styles[confidence] ?? "bg-gray-100 text-gray-600"}`}>
      {confidence}
    </span>
  );
}
