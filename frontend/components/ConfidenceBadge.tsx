const styles: Record<string, string> = {
  HIGH: "bg-red-50 text-red-700",
  MEDIUM: "bg-amber-50 text-amber-700",
  LOW: "bg-yellow-50 text-yellow-700",
};

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold tracking-wide ${styles[confidence] ?? "bg-gray-100 text-gray-600"}`}>
      {confidence}
    </span>
  );
}
