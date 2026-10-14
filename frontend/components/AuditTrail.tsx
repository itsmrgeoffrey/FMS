import type { CaseAction } from "@/types";

const actionLabels: Record<string, string> = {
  OPENED: "Opened case",
  REVIEW: "Marked Under Review",
  RELEASED: "Released back to the queue",
  FRAUD_PROPOSED: "Submitted fraud confirmation",
  DISMISSAL_PROPOSED: "Submitted dismissal",
  DECISION_APPROVED: "Approved disposition",
  DECISION_REJECTED: "Rejected disposition",
  DECISION_CANCELLED: "Withdrew disposition",
  ESCALATED: "Escalated to senior review",
  NOTE_ADDED: "Note added",
};

const actionColors: Record<string, string> = {
  FRAUD_PROPOSED: "bg-red-400",
  DISMISSAL_PROPOSED: "bg-gray-400",
  DECISION_APPROVED: "bg-green-600",
  DECISION_REJECTED: "bg-amber-500",
  DECISION_CANCELLED: "bg-gray-400",
  RELEASED: "bg-gray-400",
  ESCALATED: "bg-orange-500",
  REVIEW: "bg-purple-500",
  NOTE_ADDED: "bg-blue-400",
  OPENED: "bg-blue-500",
};

function fmtDate(ts: string) {
  return new Date(ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function AuditTrail({ actions }: { actions: CaseAction[] }) {
  if (actions.length === 0) {
    return <p className="text-sm text-gray-400">No actions taken yet.</p>;
  }

  return (
    <ol className="relative border-l border-gray-200 space-y-5 ml-2">
      {actions.map((a) => (
        <li key={a.id} className="ml-5">
          <span className={`absolute -left-2 flex items-center justify-center w-4 h-4 rounded-full ${actionColors[a.action] ?? "bg-gray-400"}`} />
          <div className="flex flex-col gap-0.5">
            <p className="text-sm font-medium text-gray-800">
              {actionLabels[a.action] ?? a.action}
            </p>
            <p className="break-words text-xs text-gray-500">{a.actor} · {fmtDate(a.created_at)}</p>
            {a.note && (
              <p className="break-words whitespace-pre-wrap text-sm text-gray-600 mt-1 [overflow-wrap:anywhere]">
                {a.note}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
