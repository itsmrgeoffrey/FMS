"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Copy, Check, ShieldAlert, FileCheck2, Activity } from "lucide-react";
import { api } from "@/lib/api";
import type { FraudCase } from "@/types";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { AiReasons } from "@/components/AiReasons";
import { ActionPanel } from "@/components/ActionPanel";
import { AuditTrail } from "@/components/AuditTrail";
import { RiskScoreGauge } from "@/components/RiskScoreBadge";
import { LoadError, money, words, ReviewFlags } from "@/components/ReviewUI";

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  return <div className="min-w-0"><dt className="text-xs text-gray-500">{label}</dt><dd className="mt-1 break-words text-sm font-medium text-gray-800 [overflow-wrap:anywhere]">{value ?? "Not provided"}</dd></div>;
}
function date(value: string) {
  return new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <CaseDetail key={id} id={id} />;
}

function CaseDetail({ id }: { id: string }) {
  const [caseData, setCaseData] = useState<FraudCase | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  useEffect(() => {
    let active = true;
    api.getCase(id).then(data => { if (active) setCaseData(data); })
      .catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [id, retry]);
  async function copyId() {
    try { await navigator.clipboard.writeText(id); setCopied(true); setCopyError(""); }
    catch { setCopyError("Could not copy the case ID."); }
  }
  const legacy = !caseData?.assessment || caseData.assessment.version === "legacy";
  const assessment = caseData?.assessment;
  const context = assessment?.transaction_context;

  return <div className="review-page">
    <Link href="/alerts" className="mb-6 inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:underline"><ArrowLeft size={16} />Alerts</Link>
    {error ? <LoadError message={error} retry={() => { setError(""); setRetry(v => v + 1); }} /> : !caseData ? <p role="status" className="py-16 text-center text-sm text-gray-500">Loading transaction...</p> : <>
      <header className="flex flex-wrap items-start justify-between gap-5">
        <div className="min-w-0 flex-1"><p className="mb-1 text-xs font-medium text-gray-500">Transaction review</p>
          <h1 className="break-words [overflow-wrap:anywhere]">{caseData.account_id}</h1>
          <div className="mt-2 flex items-center gap-2"><span className="min-w-0 break-all font-mono text-xs text-gray-500">{caseData.id}</span>
            <button onClick={copyId} className="review-icon" title={copied ? "Case ID copied" : "Copy case ID"} aria-label={copied ? "Case ID copied" : "Copy case ID"}>{copied ? <Check size={15} /> : <Copy size={15} />}</button></div>
          {copyError && <p role="alert" className="mt-1 text-xs text-red-700">{copyError}</p>}
        </div>
        <div className="min-w-0"><p className="break-words text-xl font-semibold tabular-nums [overflow-wrap:anywhere]">{money(caseData.amount, caseData.currency)}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2"><span className="text-xs text-gray-500">{words(caseData.direction)}</span><StatusBadge status={caseData.status} /></div></div>
      </header>
      <div className="mt-5"><ReviewFlags item={caseData} /></div>
      <a href="#review-decision" className="mt-4 inline-block text-sm font-medium text-blue-700 underline underline-offset-4 xl:hidden">Review decision</a>
      <dl className="mt-6 grid border-y border-gray-200 bg-white md:grid-cols-3">
        <div className="min-w-0 border-b border-gray-100 p-4 md:border-b-0 md:border-r"><dt className="mb-2 flex items-center gap-2 text-xs text-gray-500"><Activity size={15} />Detection</dt><dd className="text-sm font-semibold text-gray-800">{legacy ? "Reassessment required" : words(assessment?.detection_status)}</dd></div>
        <div className="min-w-0 border-b border-gray-100 p-4 md:border-b-0 md:border-r"><dt className="mb-2 flex items-center gap-2 text-xs text-gray-500"><ShieldAlert size={15} />Sanctions screening</dt><dd className={`text-sm font-semibold ${assessment?.screening_status === "NO_MATCH" ? "text-gray-800" : "text-amber-800"}`}>{legacy ? "Legacy / unverified" : words(assessment?.screening_status)}</dd></div>
        <div className="min-w-0 p-4"><dt className="mb-2 flex items-center gap-2 text-xs text-gray-500"><FileCheck2 size={15} />Reporting assessment</dt><dd className="text-sm font-semibold text-blue-800">{words(assessment?.regulatory_status)}</dd><dd className="mt-1 text-xs text-gray-500">Filing: {words(assessment?.reporting_status)}</dd></div>
      </dl>
      <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <section className="review-section"><h2 className="mb-5">Transaction details</h2>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Account" value={caseData.account_id} /><Field label={caseData.direction === "OUTWARD" ? "Beneficiary account" : "Sender account"} value={caseData.counterparty_account} /><Field label={caseData.direction === "OUTWARD" ? "Beneficiary name" : "Sender name"} value={caseData.counterparty_name} />
              <Field label="Source" value={caseData.source_table} /><Field label="Source transaction ID" value={caseData.source_txn_id} /><Field label="Channel" value={caseData.channel} />
              <Field label="Transaction time (local)" value={date(caseData.timestamp)} /><Field label="Created (local)" value={date(caseData.created_at)} /><Field label="Reference" value={caseData.reference} />
              <Field label="Instrument" value={context?.transaction_instrument ? words(context.transaction_instrument) : null} /><Field label="Business date" value={assessment?.business_date} /><Field label="Cash classification" value={assessment?.cash_classification == null ? null : assessment.cash_classification ? "Cash" : "Non-cash"} />
              <Field label="Branch" value={context?.branch_id} /><Field label="Location" value={context?.location_id} /><Field label="Account holder ID" value={context?.account_holder_id} />
              <Field label="Account holder" value={context?.account_holder_name} /><Field label="Conductor ID" value={context?.conductor_id} /><Field label="Conductor" value={context?.conductor_name} />
            </dl>
          </section>
          <section className="review-section"><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><h2>Detection evidence</h2><ConfidenceBadge confidence={caseData.confidence} /></div>
            {assessment?.structuring_alert && <div className="mb-5 border-l-4 border-red-500 bg-red-50 p-4"><h3 className="font-semibold text-red-900">Cross-branch structuring alert</h3><p className="mt-1 text-sm text-red-800">Multiple individually sub-threshold cash transactions were identified across distinct branches or locations on the same business day.</p></div>}
            <div className="mb-5"><RiskScoreGauge score={caseData.risk_score} /></div>
            {caseData.fraud_type && <p className="mb-4 text-sm font-medium text-gray-700">{words(caseData.fraud_type)}</p>}
            {caseData.reasons.length || caseData.ai_summary ? <AiReasons reasons={caseData.reasons} summary={caseData.ai_summary} /> : <p className="text-sm text-gray-500">No detection evidence recorded.</p>}
          </section>
          <section className="review-section"><h2 className="mb-4">Screening &amp; reporting</h2>
            <div className="space-y-4 text-sm">
              {legacy && <p className="border-l-4 border-amber-400 bg-amber-50 p-4 text-amber-900">Legacy assessment. Screening and reporting requirements need reassessment.</p>}
              {caseData.sanctions_hit && <div className="border-l-4 border-red-400 bg-red-50 p-4"><h3 className="font-semibold text-red-900">Possible sanctions match</h3><p className="mt-2 break-words text-red-800">{caseData.sanctions_detail}</p><p className="mt-2 text-xs text-red-700">Identity and program verification outstanding. A name match is not a confirmed identity.</p></div>}
              {!legacy && !caseData.sanctions_hit && assessment?.screening_status !== "NO_MATCH" && <p className="border-l-4 border-amber-400 bg-amber-50 p-4 text-amber-900">Screening is {words(assessment?.screening_status).toLowerCase()}. No clearance has been established.</p>}
              {!legacy && assessment?.screening_status === "NO_MATCH" && <p className="text-gray-600">No screening candidate was recorded at assessment time.</p>}
              {caseData.ctr_required && <div className="border-l-4 border-blue-400 bg-blue-50 p-4"><h3 className="font-semibold text-blue-900">CTR review</h3><p className="mt-2 break-words text-blue-800">{caseData.ctr_reason}</p><p className="mt-2 text-xs text-blue-700">Cash classification, business-day totals and exemptions require verification. This flag is separate from fraud suspicion.</p></div>}
              {caseData.sar_recommended && <div className="border-l-4 border-amber-400 bg-amber-50 p-4"><h3 className="font-semibold text-amber-900">SAR recommendation</h3><p className="mt-2 break-words text-amber-800">{caseData.sar_reason}</p><p className="mt-2 text-xs text-amber-800">Officer assessment is outstanding. This recommendation is not a filed report.</p></div>}
              {!caseData.ctr_required && !caseData.sar_recommended && <p className="text-gray-600">No CTR or SAR flag recorded.</p>}
            </div>
          </section>
          <section className="review-section pb-6"><div className="mb-5 flex items-center gap-2"><h2>Audit trail</h2><span className="text-xs text-gray-500">{caseData.actions.length} entries</span></div><AuditTrail actions={caseData.actions} /></section>
        </div>
        <aside id="review-decision" className="mt-6 min-w-0 scroll-mt-6 rounded-lg border border-gray-200 bg-white p-5 xl:sticky xl:top-6">
          <h2 className="mb-2">Review decision</h2><p className="mb-5 text-xs text-gray-500">Updated {date(caseData.updated_at)}</p>
          <ActionPanel caseData={caseData} onUpdate={setCaseData} />
        </aside>
      </div>
    </>}
  </div>;
}
