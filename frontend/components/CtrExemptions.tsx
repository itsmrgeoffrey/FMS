"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Ban, Plus, Send, X } from "lucide-react";
import { api, type CtrExemption, type CtrExemptionInput } from "@/lib/api";
import { LoadError, RefreshButton } from "@/components/ReviewUI";

const categories = ["BANK", "GOVERNMENT", "GOVERNMENT_AUTHORITY", "LISTED_ENTITY", "LISTED_SUBSIDIARY", "NONLISTED_BUSINESS", "PAYROLL_CUSTOMER"];
const label = (value: string) => value.toLowerCase().replaceAll("_", " ");
const inputClass = "w-full min-w-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500";
const empty: CtrExemptionInput = {
  subject_id: "", subject_name: "", exemption_type: "NONLISTED_BUSINESS", account_ids: [],
  effective_from: "", expires_on: "", reviewed_on: "", review_due: "", eligibility_basis: "",
  evidence_reference: "", designation_reference: "", eligibility_verified: false,
};

export default function CtrExemptions({ onSubmitted }: { onSubmitted: () => void }) {
  const [items, setItems] = useState<CtrExemption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(empty);
  const [accounts, setAccounts] = useState("");
  const [revoking, setRevoking] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try { setItems((await api.listCtrExemptions()).items); setError(null); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    api.listCtrExemptions().then(result => { if (active) setItems(result.items); })
      .catch(e => { if (active) setError(String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      const result = await api.proposeCtrExemption({ ...form,
        account_ids: accounts.split(/[\n,]/).map(value => value.trim()).filter(Boolean),
        designation_reference: form.designation_reference?.trim() || null });
      if (result.pending) setMessage(result.message);
      setEditing(false); setForm(empty); setAccounts(""); onSubmitted(); await load();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  async function revoke(event: React.FormEvent) {
    event.preventDefault(); if (!revoking) return;
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await api.revokeCtrExemption(revoking, reason.trim());
      if (result.pending) setMessage(result.message);
      setRevoking(null); setReason(""); onSubmitted(); await load();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  const field = (key: "subject_id" | "subject_name" | "effective_from" | "expires_on" | "reviewed_on" | "review_due" | "evidence_reference" | "designation_reference", title: string, type = "text", required = true) =>
    <label className="block min-w-0 text-xs font-medium text-gray-600">{title}
      <input className={`${inputClass} mt-1`} type={type} value={form[key] ?? ""} required={required}
        maxLength={key === "subject_id" ? 64 : key === "subject_name" ? 200 : 255}
        onChange={event => setForm(previous => ({ ...previous, [key]: event.target.value }))} />
    </label>;

  return <section className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 pb-4">
      <h2 className="text-lg font-semibold text-gray-800">CTR exemptions</h2>
      <div className="flex items-center gap-2"><RefreshButton loading={loading} onClick={load} />
        <button onClick={() => setEditing(!editing)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">
          {editing ? <X size={16} /> : <Plus size={16} />}{editing ? "Close" : "Propose exemption"}
        </button>
      </div>
    </div>
    {message && <p role="status" className="border-l-4 border-blue-500 bg-blue-50 p-3 text-sm text-blue-900">{message} <Link href="/settings?tab=approvals" className="underline">View approvals</Link></p>}
    {error && <LoadError message={error} retry={load} />}
    {editing && <form onSubmit={submit} className="space-y-4 border-b border-gray-200 pb-5">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {field("subject_id", "Account holder ID")}{field("subject_name", "Legal name")}
        <label className="text-xs font-medium text-gray-600">Exemption category
          <select className={`${inputClass} mt-1 capitalize`} value={form.exemption_type} onChange={e => setForm({ ...form, exemption_type: e.target.value })}>
            {categories.map(category => <option key={category} value={category}>{label(category)}</option>)}
          </select>
        </label>
        {field("evidence_reference", "Eligibility evidence reference")}
        {field("designation_reference", "FinCEN designation reference", "text", !categories.slice(0, 3).includes(form.exemption_type))}
        <label className="text-xs font-medium text-gray-600">Covered account IDs
          <textarea required className={`${inputClass} mt-1`} rows={2} value={accounts} onChange={e => setAccounts(e.target.value)} placeholder="One per line or comma-separated" />
        </label>
        {field("effective_from", "Effective from", "date")}{field("expires_on", "Expires on", "date")}
        {field("reviewed_on", "Eligibility reviewed on", "date")}{field("review_due", "Next review due", "date")}
      </div>
      <label className="block text-xs font-medium text-gray-600">Eligibility basis
        <textarea required minLength={10} maxLength={8000} rows={3} className={`${inputClass} mt-1`} value={form.eligibility_basis} onChange={e => setForm({ ...form, eligibility_basis: e.target.value })} />
      </label>
      <label className="flex items-start gap-2 text-sm text-gray-700"><input type="checkbox" required checked={form.eligibility_verified} onChange={e => setForm({ ...form, eligibility_verified: e.target.checked })} className="mt-1" />I verified the institution&apos;s eligibility evidence, category, account scope, and applicable designation requirements.</label>
      <button disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"><Send size={16} />Submit for approval</button>
    </form>}
    {loading && <p role="status" className="text-sm text-gray-500">Loading exemptions...</p>}
    {!loading && !error && items.length === 0 && <p className="text-sm text-gray-500">No approved exemption records.</p>}
    <ul className="divide-y divide-gray-200">{items.map(item => <li key={item.id} className="py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><h3 className="break-words text-sm font-semibold text-gray-800">{item.subject_name} <span className="font-normal text-gray-500">({item.subject_id})</span></h3>
          <p className="mt-1 text-xs capitalize text-gray-600">{label(item.exemption_type)} | {label(item.evaluation_status)}</p>
          <p className="mt-1 text-xs text-gray-500">{item.effective_from} to {item.expires_on} | Review due {item.review_due}</p>
        </div>
        {item.status === "ACTIVE" && <button disabled={busy} onClick={() => { setRevoking(item.id); setReason(""); }} className="inline-flex items-center gap-2 text-sm text-red-700"><Ban size={16} />Request revocation</button>}
      </div>
      <details className="mt-3 text-sm text-gray-600"><summary className="cursor-pointer">Scope and evidence</summary>
        <dl className="mt-2 space-y-2 break-words">
          {Object.entries({ "Accounts": item.account_ids.join(", "), "Eligibility basis": item.eligibility_basis, "Evidence": item.evidence_reference, "Designation": item.designation_reference || "Not required for recorded category", "Requested by": item.created_by, "Approved by": item.approved_by, "Revocation reason": item.revocation_reason || "None" }).map(([key, value]) => <div key={key}><dt className="font-medium">{key}</dt><dd>{value}</dd></div>)}
        </dl>
      </details>
      {revoking === item.id && <form onSubmit={revoke} className="mt-3 flex flex-wrap gap-2">
        <input aria-label="Revocation reason" required minLength={3} maxLength={2000} className={inputClass} value={reason} onChange={e => setReason(e.target.value)} placeholder="Revocation reason" />
        <button disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-sm text-white"><Send size={16} />Submit revocation</button>
        <button type="button" onClick={() => setRevoking(null)} className="px-3 py-2 text-sm text-gray-600">Cancel</button>
      </form>}
    </li>)}</ul>
  </section>;
}
