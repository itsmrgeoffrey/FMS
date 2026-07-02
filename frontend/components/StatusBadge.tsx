const styles: Record<string, string> = {
  CLEAN: "bg-green-50 text-green-700",
  OPEN: "bg-blue-100 text-blue-700",
  UNDER_REVIEW: "bg-purple-100 text-purple-700",
  CONFIRMED_FRAUD: "bg-red-100 text-red-700",
  DISMISSED: "bg-gray-100 text-gray-600",
  ESCALATED: "bg-orange-100 text-orange-700",
};

const labels: Record<string, string> = {
  CLEAN: "Clean",
  OPEN: "Open",
  UNDER_REVIEW: "Under Review",
  CONFIRMED_FRAUD: "Confirmed Fraud",
  DISMISSED: "Dismissed",
  ESCALATED: "Escalated",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status] ?? "bg-gray-100 text-gray-600"}`}>
      {labels[status] ?? status}
    </span>
  );
}
