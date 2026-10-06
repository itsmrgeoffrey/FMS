import Link from "next/link";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import type { Assessment } from "@/types";
import { RiskScoreBadge } from "@/components/RiskScoreBadge";
import { StatusBadge } from "@/components/StatusBadge";

export function money(amount: number, currency: string) {
  return `${currency} ${amount.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
}

export function words(value?: string | null) {
  return value ? value.replaceAll("_", " ").toLowerCase().replace(/^./, c => c.toUpperCase()) : "Not assessed";
}

export function RefreshButton({ loading, onClick }: { loading: boolean; onClick: () => void }) {
  return <button type="button" title="Refresh" aria-label="Refresh" disabled={loading} onClick={onClick} className="review-icon">
    <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
  </button>;
}

export function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return <div role="alert" className="flex flex-wrap items-center justify-between gap-3 border-l-4 border-red-500 bg-red-50 p-4 text-sm text-red-800">
    <span className="min-w-0 break-words">{message}</span>
    <button onClick={retry} className="font-semibold underline underline-offset-4">Retry</button>
  </div>;
}

type ReviewItem = {
  id: string; account_id: string; amount: number; currency: string;
  risk_score: number | null; status: string; ctr_required: boolean;
  sar_recommended: boolean; sanctions_hit: boolean; assessment?: Assessment;
  fraud_type: string | null; channel?: string | null; source_table?: string;
};

export function ReviewFlags({ item }: { item: Pick<ReviewItem, "ctr_required" | "sar_recommended" | "sanctions_hit" | "assessment"> }) {
  const screening = item.assessment?.screening_status;
  const legacy = !item.assessment || item.assessment.version === "legacy";
  return <div className="flex flex-wrap gap-1.5">
    {item.ctr_required && <span className="review-tag bg-blue-50 text-blue-800">CTR review</span>}
    {item.sar_recommended && <span className="review-tag bg-amber-50 text-amber-800">SAR review</span>}
    {item.sanctions_hit && <span className="review-tag bg-red-50 text-red-700">Possible match</span>}
    {legacy ? <span className="review-tag bg-gray-100 text-gray-600">Legacy assessment</span> :
      screening !== "NO_MATCH" && screening !== "POSSIBLE_MATCH" && <span className="review-tag bg-amber-50 text-amber-800">Screening: {words(screening)}</span>}
    {!item.ctr_required && !item.sar_recommended && !item.sanctions_hit && !legacy && screening === "NO_MATCH" && <span className="text-xs text-gray-500">No reporting flag</span>}
  </div>;
}

export function ReviewTable({ items, loading, empty }: { items: ReviewItem[]; loading: boolean; empty: string }) {
  return <div aria-busy={loading}>
    <ul aria-label="Transactions requiring review" className={`divide-y divide-gray-200 border-y border-gray-200 bg-white md:hidden ${loading ? "opacity-50" : ""}`}>
      {items.map(item => <li key={item.id} className="space-y-3 px-3 py-4">
        <div className="flex items-start justify-between gap-3"><div className="min-w-0"><Link href={`/cases/${item.id}`} className="break-words text-sm font-semibold text-blue-700 [overflow-wrap:anywhere]">{item.account_id}</Link><p className="mt-1 break-words text-xs text-gray-500">{item.channel || item.source_table || "Transaction"}</p></div><StatusBadge status={item.status} /></div>
        <p className="break-words text-sm font-semibold tabular-nums [overflow-wrap:anywhere]">{money(item.amount, item.currency)}</p>
        <ReviewFlags item={item} />
        <div className="flex items-center justify-between gap-3"><p className="min-w-0 break-words text-xs text-gray-500">{words(item.fraud_type || item.assessment?.detection_status)}</p><div className="flex shrink-0 items-center gap-2"><span className="text-xs text-gray-500">Risk</span><RiskScoreBadge score={item.risk_score} /></div></div>
      </li>)}
      {!items.length && <li role="status" className="px-4 py-12 text-center text-sm text-gray-500">{loading ? "Loading transactions..." : empty}</li>}
    </ul>
    <div className="hidden overflow-x-auto border-y border-gray-200 bg-white md:block">
    <table className="w-full min-w-[850px] text-left text-sm">
      <caption className="sr-only">Transactions requiring review</caption>
      <thead className="border-b border-gray-200 bg-gray-50 text-xs text-gray-500"><tr>
        {["Account / source", "Amount", "Detection", "Review flags", "Risk", "Status", ""].map((label, i) => <th key={i} scope="col" className="px-4 py-3 font-medium">{label || <span className="sr-only">Open transaction</span>}</th>)}
      </tr></thead>
      <tbody className={`divide-y divide-gray-100 ${loading ? "opacity-50" : ""}`}>
        {items.map(item => <tr key={item.id} className="hover:bg-blue-50/40">
          <td className="max-w-52 px-4 py-4"><Link href={`/cases/${item.id}`} className="break-words font-semibold text-blue-700 hover:underline">{item.account_id}</Link>
            <p className="mt-1 break-words text-xs text-gray-500">{item.channel || item.source_table || "Transaction"}</p></td>
          <td className="whitespace-nowrap px-4 py-4 font-medium tabular-nums">{money(item.amount, item.currency)}</td>
          <td className="max-w-44 break-words px-4 py-4 text-xs text-gray-600">{words(item.fraud_type || item.assessment?.detection_status)}</td>
          <td className="max-w-60 px-4 py-4"><ReviewFlags item={item} /></td>
          <td className="px-4 py-4"><RiskScoreBadge score={item.risk_score} /></td>
          <td className="px-4 py-4"><StatusBadge status={item.status} /></td>
          <td className="px-3 py-4"><Link href={`/cases/${item.id}`} className="review-icon" title={`Review ${item.account_id}`} aria-label={`Review ${item.account_id}`}><ArrowUpRight size={16} /></Link></td>
        </tr>)}
        {!items.length && <tr><td colSpan={7} className="h-40 px-4 text-center text-gray-500" role="status">{loading ? "Loading transactions..." : empty}</td></tr>}
      </tbody>
    </table>
    </div>
  </div>;
}
