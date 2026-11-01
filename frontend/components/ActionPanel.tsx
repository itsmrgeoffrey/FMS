"use client";
import { useState } from "react";
import { api, auth } from "@/lib/api";
import type { FraudCase } from "@/types";

const FINAL_STATUSES = new Set(["CONFIRMED_FRAUD", "DISMISSED"]);

export function ActionPanel({ caseData, onUpdate }: {
  caseData: FraudCase;
  onUpdate: (updated: FraudCase) => void;
}) {
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const user = auth.user();
  const canInput = user?.role === "analyst";
  const canApprove = user?.role === "approver" || user?.role === "admin";
  const mine = caseData.assigned_to === user?.username;

  async function run(label: string, operation: () => Promise<FraudCase>) {
    setLoading(label); setError(null);
    try { onUpdate(await operation()); setNote(""); }
    catch (e) { setError(String(e)); }
    finally { setLoading(null); }
  }

  const textarea = (
    <label className="block text-xs font-medium text-gray-600">Decision note
      <textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Record the evidence and reason" rows={4}
        className="mt-1.5 w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
    </label>
  );

  if (caseData.status === "CLEAN" && !caseData.ctr_required && !caseData.sar_recommended && !caseData.sanctions_hit) {
    return <p className="text-sm font-medium text-green-700">No review is currently open for this transaction.</p>;
  }
  if (FINAL_STATUSES.has(caseData.status)) {
    return <p className="text-sm italic text-gray-500">This case is closed ({caseData.status.replaceAll("_", " ").toLowerCase()}). Reporting obligations remain separate.</p>;
  }

  if (caseData.status === "PENDING_APPROVAL") {
    const proposal = caseData.pending_decision;
    if (!proposal) return <p className="text-sm text-amber-800">The disposition is pending, but its approval record is unavailable.</p>;
    const ownProposal = proposal.requested_by === user?.username;
    return <div className="space-y-4">
      <div className="border-l-4 border-amber-500 bg-amber-50 p-3 text-sm text-amber-950">
        <p className="font-semibold">{proposal.proposed_action === "CONFIRMED" ? "Fraud confirmation" : "Dismissal"} awaiting approval</p>
        <p className="mt-1 text-xs">Submitted by {proposal.requested_by}</p>
        <p className="mt-2 whitespace-pre-wrap">{proposal.rationale}</p>
      </div>
      {ownProposal ? <>
        <p className="text-xs text-gray-500">You submitted this disposition. A different Approver or Admin must decide it.</p>
        <button disabled={!!loading} onClick={() => run("cancel", () => api.cancelCaseDecision(caseData.id))}
          className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 disabled:opacity-50">Withdraw proposal</button>
      </> : canApprove ? <>
        {textarea}
        <div className="grid grid-cols-2 gap-2">
          <button disabled={!!loading} onClick={() => run("approve", () => api.approveCaseDecision(caseData.id, note.trim() || undefined))}
            className="rounded-lg bg-green-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Approve</button>
          <button disabled={!!loading || !note.trim()} onClick={() => run("reject", () => api.rejectCaseDecision(caseData.id, note.trim()))}
            className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Reject &amp; return</button>
        </div>
      </> : <p className="text-sm text-gray-500">Awaiting an independent Approver or Admin.</p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>;
  }

  if (caseData.status === "ESCALATED") {
    return canApprove ? <div className="space-y-3">
      <p className="text-sm text-gray-600">This case was escalated for senior review. Claim it before recording a disposition.</p>
      <button disabled={!!loading} onClick={() => run("review", () => api.addAction(caseData.id, "REVIEW", note.trim() || undefined))}
        className="w-full rounded-lg bg-purple-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Start senior review</button>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div> : <p className="text-sm text-gray-500">Escalated to the senior-review queue. An Approver or Admin must claim it.</p>;
  }

  const senior = caseData.review_level === "SENIOR";
  const authorizedReviewer = senior ? canApprove : canInput;
  if (!authorizedReviewer) {
    return <p className="text-sm text-gray-600">{senior
      ? "This case is escalated. An Approver or Admin must claim the senior review."
      : "An Analyst/Inputter must claim and investigate this standard case. They can escalate it or submit a fraud or dismissal proposal for your review."}</p>;
  }
  if (caseData.status !== "UNDER_REVIEW" || !caseData.assigned_to) {
    return <div className="space-y-3">
      <button disabled={!!loading} onClick={() => run("review", () => api.addAction(caseData.id, "REVIEW"))}
        className="w-full rounded-lg bg-purple-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Start review</button>
      {!senior && <>{textarea}<button disabled={!!loading || !note.trim()} onClick={() => run("escalate", () => api.addAction(caseData.id, "ESCALATED", note.trim()))}
        className="w-full rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Escalate to senior review</button></>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>;
  }
  if (!mine) {
    return <p className="text-sm text-gray-500">Assigned to <span className="font-medium text-gray-700">{caseData.assigned_to || "another reviewer"}</span>.</p>;
  }

  return <div className="space-y-4">
    <p className="text-xs text-gray-500">Assigned to you · {senior ? "Senior review" : "Analyst review"}</p>
    {textarea}
    <button disabled={!!loading || !note.trim()} onClick={() => run("confirm", () => api.addAction(caseData.id, "CONFIRMED", note.trim()))}
      className="w-full rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Submit fraud confirmation</button>
    {!senior && <button disabled={!!loading || !note.trim()} onClick={() => run("escalate", () => api.addAction(caseData.id, "ESCALATED", note.trim()))}
      className="w-full rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Escalate to senior review</button>}
    <button disabled={!!loading || !note.trim()} onClick={() => run("dismiss", () => api.addAction(caseData.id, "DISMISSED", note.trim()))}
      className="w-full rounded-lg bg-gray-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Submit dismissal</button>
    <button disabled={!!loading} onClick={() => run("release", () => api.addAction(caseData.id, "RELEASED", note.trim() || undefined))}
      className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 disabled:opacity-50">Release to queue</button>
    <button disabled={!!loading || !note.trim()} onClick={() => run("note", () => api.addAction(caseData.id, "NOTE_ADDED", note.trim()))}
      className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 disabled:opacity-50">Add review note</button>
    <p className="text-xs text-gray-500">Final dispositions require approval by a different Approver or Admin.</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
  </div>;
}
