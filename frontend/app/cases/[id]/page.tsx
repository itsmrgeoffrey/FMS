"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import type { FraudCase } from "@/types";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { AiReasons } from "@/components/AiReasons";
import { ActionPanel } from "@/components/ActionPanel";
import { AuditTrail } from "@/components/AuditTrail";
import { RiskScoreGauge } from "@/components/RiskScoreBadge";

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">{label}</p>
      <p className="text-sm text-gray-800 font-medium mt-0.5">{value ?? "—"}</p>
    </div>
  );
}

function fmtDate(ts: string) {
  return new Date(ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "medium" });
}

function fmt(amount: number, currency: string) {
  return `${currency} ${amount.toLocaleString("en-NG", { minimumFractionDigits: 2 })}`;
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [caseData, setCaseData] = useState<FraudCase | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getCase(id)
      .then(setCaseData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">
        Loading case...
      </div>
    );
  }

  if (error || !caseData) {
    return (
      <div className="p-6">
        <p className="text-red-600 text-sm">{error ?? "Case not found."}</p>
        <Link href="/cases" className="text-blue-600 text-sm mt-2 inline-block">← Back to cases</Link>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Back */}
      <Link href="/cases" className="text-sm text-blue-600 hover:text-blue-800 inline-flex items-center gap-1">
        ← All cases
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start gap-4 justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">
            {fmt(caseData.amount, caseData.currency)} {caseData.direction}
          </h1>
          <p className="text-sm text-gray-500 mt-1">Case ID: {caseData.id}</p>
        </div>
        <div className="flex items-center gap-2">
          <ConfidenceBadge confidence={caseData.confidence} />
          <StatusBadge status={caseData.status} />
        </div>
      </div>

      {/* Transaction details */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Transaction Details</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-5">
          <Field label="Account" value={caseData.account_id} />
          <Field label="Amount" value={fmt(caseData.amount, caseData.currency)} />
          <Field label="Direction" value={caseData.direction} />
          <Field label="Timestamp" value={fmtDate(caseData.timestamp)} />
          <Field label="Channel" value={caseData.channel} />
          <Field label="Counterparty Account" value={caseData.counterparty_account} />
          <Field label="Counterparty Name" value={caseData.counterparty_name} />
          <Field label="Reference" value={caseData.reference} />
        </div>
      </section>

      {/* CTR Filing Panel — regulatory track, separate from fraud */}
      {caseData.ctr_required && (
        <section className="bg-blue-50 rounded-lg border border-blue-200 p-5">
          <div className="flex items-start gap-3">
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-blue-100 text-blue-800 border border-blue-300 shrink-0 mt-0.5">
              CTR REQUIRED
            </span>
            <div>
              <p className="text-sm font-semibold text-blue-900 mb-1">Currency Transaction Report filing obligation</p>
              <p className="text-xs text-blue-700 leading-relaxed">{caseData.ctr_reason}</p>
              <p className="text-xs text-blue-500 mt-2">
                This is a regulatory filing requirement under the Bank Secrecy Act — it does not indicate fraud on its own.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* SAR Recommendation — suspicious activity reporting track */}
      {caseData.sar_recommended && (
        <section className="bg-amber-50 rounded-lg border border-amber-200 p-5">
          <div className="flex items-start gap-3">
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300 shrink-0 mt-0.5">
              SAR RECOMMENDED
            </span>
            <div>
              <p className="text-sm font-semibold text-amber-900 mb-1">Suspicious Activity Report recommended</p>
              <p className="text-xs text-amber-700 leading-relaxed">{caseData.sar_reason}</p>
              <p className="text-xs text-amber-600 mt-2">
                Under the Bank Secrecy Act, suspicious activity is reportable to FinCEN — structuring/smurfing regardless of amount, otherwise at or above the SAR threshold.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* AI Analysis — fraud risk track */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center gap-3 mb-4">
          <h2 className="text-sm font-semibold text-gray-700">Fraud Risk Analysis</h2>
          {caseData.fraud_type && (
            <span className="text-xs bg-red-50 text-red-700 border border-red-200 px-2 py-0.5 rounded font-medium">
              {caseData.fraud_type}
            </span>
          )}
        </div>
        {caseData.risk_score !== null && caseData.risk_score !== undefined && (
          <div className="mb-4 pb-4 border-b border-gray-100">
            <RiskScoreGauge score={caseData.risk_score} />
          </div>
        )}
        <AiReasons reasons={caseData.reasons} summary={caseData.ai_summary} />
      </section>

      {/* Actions */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Take Action</h2>
        <ActionPanel caseData={caseData} onUpdate={setCaseData} />
      </section>

      {/* Audit trail */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Audit Trail</h2>
        <AuditTrail actions={caseData.actions} />
      </section>
    </div>
  );
}
