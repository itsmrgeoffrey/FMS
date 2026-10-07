"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, CheckCircle2, CircleHelp, Save, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { LoadError, RefreshButton } from "@/components/ReviewUI";
import type { InstallationInfo, OperatingProfile } from "@/types";

const inputStyle = "w-full min-w-0 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";
export default function InstallationSettings({ onSubmitted }: { onSubmitted: () => void }) {
  const [data, setData] = useState<InstallationInfo | null>(null);
  const [profile, setProfile] = useState<OperatingProfile | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    async function load() {
      try { const result = await api.getInstallation(); if (active) { setError(null); setData(result); setProfile(result.profile); } }
      catch (e) { if (active) setError(String(e)); }
      finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, [refresh]);
  function reload() { setLoading(true); setRefresh(value => value + 1); }
  async function save() {
    if (!data || !profile || !reason.trim()) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      const result = await api.updateSettings({ operating_profile: profile, configuration_revision: data.revision, profile_rationale: reason.trim() });
      setNotice(result.pending ? "Profile submitted for second-person approval. The active profile is unchanged." : "Operating profile saved. Future assessments will use this scope.");
      setReason(""); onSubmitted(); reload();
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  }
  return <div className="space-y-7">
    <header className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold text-gray-900">Installation</h2>
      <RefreshButton loading={loading || saving} onClick={() => { if (window.confirm("Reload the profile and discard unsaved edits?")) reload(); }} /></header>
    {error && <LoadError message={error} retry={reload} />}
    {notice && <p role="status" className="border-l-4 border-blue-500 bg-blue-50 p-3 text-sm text-blue-800">{notice} <Link href="/settings?tab=approvals" className="font-medium underline">View approvals</Link></p>}
    {!data || !profile ? <p role="status" className="py-12 text-center text-sm text-gray-500">{loading ? "Loading installation..." : "Installation unavailable."}</p> : <>
      <form onSubmit={e => { e.preventDefault(); void save(); }} className="space-y-4 border-t border-gray-200 pt-5">
        <h2 className="text-base font-semibold text-gray-900">Operating profile</h2>
        <fieldset disabled={loading || saving} className="grid min-w-0 gap-4 sm:grid-cols-3">
          <div><label htmlFor="jurisdiction" className="mb-1 block text-xs font-medium text-gray-600">Jurisdiction (country code)</label><input id="jurisdiction" required pattern="[A-Z]{2}" maxLength={2} value={profile.regulatory_jurisdiction} onChange={e => setProfile({ ...profile, regulatory_jurisdiction: e.target.value.toUpperCase() })} className={inputStyle} /></div>
          <div><label htmlFor="institution-type" className="mb-1 block text-xs font-medium text-gray-600">Institution type</label><select id="institution-type" value={profile.institution_type} onChange={e => setProfile({ ...profile, institution_type: e.target.value as OperatingProfile["institution_type"] })} className={inputStyle}>
            <option value="bank">Bank</option><option value="credit_union">Credit union</option><option value="msb">Money services business</option><option value="fintech">Fintech</option><option value="other">Other</option>
          </select></div>
          <div><label htmlFor="timezone" className="mb-1 block text-xs font-medium text-gray-600">Business timezone</label><input id="timezone" required maxLength={100} value={profile.business_timezone} onChange={e => setProfile({ ...profile, business_timezone: e.target.value })} className={inputStyle} /></div>
          <div className="sm:col-span-3"><label htmlFor="profile-reason" className="mb-1 block text-xs font-medium text-gray-600">Reason for confirming or changing profile (required)</label><textarea id="profile-reason" required rows={2} value={reason} onChange={e => setReason(e.target.value)} className={inputStyle} /></div>
        </fieldset>
        <p className="text-sm text-gray-600"><span className="font-medium">Active reporting scope:</span> {data.reporting_scope}</p>
        <p className="text-xs text-gray-500">Profile changes affect future assessments only. Existing assessments retain their original scope.</p>
        <button type="submit" disabled={loading || saving || !reason.trim()} className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"><Save size={16} />{saving ? "Submitting..." : "Submit profile"}</button>
      </form>
      <section className="space-y-4 border-t border-gray-200 pt-5" aria-labelledby="onboarding-heading">
        <h2 id="onboarding-heading" className="text-base font-semibold text-gray-900">Transaction onboarding and history</h2>
        {data.onboarding ? <>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-gray-500">Input mode</dt><dd className="font-medium text-gray-900">{data.onboarding.mode === "api" ? "API push" : "Database polling"}</dd></div>
            <div><dt className="text-gray-500">History window</dt><dd className="font-medium text-gray-900">{data.onboarding.history_days} days / {data.onboarding.required_history_days} required by detection windows</dd></div>
          </dl>
          {data.onboarding.mode === "poll" && <div className="space-y-3">
            <p className="border-l-4 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">{data.onboarding.polling_start}</p>
            <p className="text-sm text-gray-600">{data.onboarding.cursor_requirement}</p>
            <h3 className="text-sm font-semibold text-gray-800">Saved polling cursors</h3>
            {data.onboarding.checkpoints.length === 0 ? <p className="text-sm text-amber-800">No source tables are mapped. Database polling cannot receive transactions.</p> :
              <ul className="divide-y divide-gray-200">{data.onboarding.checkpoints.map(checkpoint => <li key={checkpoint.table_key} className="space-y-1 py-3 text-sm">
                <p className="break-all font-medium text-gray-900">{checkpoint.table_key}</p>
                <p className="break-all text-gray-600">{!checkpoint.initialized ? "Not initialized: first connection will establish the baseline." : checkpoint.cursor === null || checkpoint.cursor === "" ? "Initialized with no rows; awaiting first transactions." : `Monitoring IDs after ${checkpoint.cursor}`}</p>
                {checkpoint.updated_at && <p className="text-xs text-gray-500">Cursor recorded: {new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(checkpoint.updated_at) ? checkpoint.updated_at : `${checkpoint.updated_at}Z`).toLocaleString()}</p>}
              </li>)}</ul>}
          </div>}
          <h3 className="text-sm font-semibold text-gray-800">Historical data</h3>
          <p className="text-sm text-gray-600">{data.onboarding.history_supply}</p>
          {data.onboarding.mode === "api" && <p className="text-sm text-gray-700">Stored API transactions: <span className="font-medium tabular-nums">{data.onboarding.api_history.count.toLocaleString()}</span>{data.onboarding.api_history.earliest && data.onboarding.api_history.latest ? ` (transaction dates ${data.onboarding.api_history.earliest.slice(0, 10)} to ${data.onboarding.api_history.latest.slice(0, 10)})` : ". No stored API history."}</p>}
          <p className="border-l-4 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">{data.onboarding.history_verification}</p>
          <h3 className="text-sm font-semibold text-gray-800">API transaction IDs</h3>
          <p className="break-words text-sm text-gray-600">{data.onboarding.api_id_convention}</p>
        </> : <p role="alert" className="text-sm text-amber-800">Onboarding status is unavailable. Verify that the backend is updated.</p>}
      </section>
      <section className="border-t border-gray-200 pt-5"><h2 className="mb-3 text-base font-semibold text-gray-900">Installation checks</h2>
        <p className="mb-4 text-sm text-gray-500">Configuration checks, not a compliance certification or production approval.</p>
        <ul className="divide-y divide-gray-200">{data.checks.map(check => {
          const Icon = check.state === "configured" ? CheckCircle2 : check.state === "attention" ? TriangleAlert : CircleHelp;
          const color = check.state === "configured" ? "text-green-700" : check.state === "attention" ? "text-amber-700" : "text-gray-500";
          return <li key={check.key} className="flex items-start gap-3 py-4"><Icon size={18} className={`mt-0.5 shrink-0 ${color}`} /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><h3 className="text-sm font-medium text-gray-900">{check.label}</h3><span className={`text-xs ${color}`}>{check.state === "attention" ? "Needs attention" : check.state === "configured" ? "Configured" : "Not verified"}</span></div><p className="mt-1 break-words text-sm text-gray-500">{check.detail}</p></div>
            {check.href !== "/settings?tab=installation" && <Link href={check.href} className="review-icon shrink-0" title={`Review ${check.label.toLowerCase()}`} aria-label={`Review ${check.label.toLowerCase()}`}><ArrowUpRight size={16} /></Link>}</li>;
        })}</ul>
      </section>
      <div className="grid gap-7 border-t border-gray-200 pt-5 md:grid-cols-2"><section><h2 className="mb-3 text-base font-semibold text-gray-900">Available capabilities</h2><ul className="space-y-2 text-sm text-gray-600">{data.capabilities.map(item => <li key={item}>{item}</li>)}</ul><Link href="/settings?tab=rules" className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-blue-700">Rule Engine <ArrowUpRight size={16} /></Link></section>
        <section><h2 className="mb-3 text-base font-semibold text-gray-900">Operating limits</h2><ul className="space-y-2 text-sm text-gray-600">{data.boundaries.map(item => <li key={item}>{item}</li>)}</ul></section></div>
    </>}
  </div>;
}
