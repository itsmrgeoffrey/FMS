"use client";
import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "@/lib/api";
import type { FraudCaseListItem } from "@/types";
import Pagination from "@/components/Pagination";
import { LoadError, RefreshButton, ReviewTable } from "@/components/ReviewUI";

const defaults = { search: "", status: "", direction: "", flag: "", min_risk: "", sort: "risk" };

export default function AlertsPage() {
  const [filters, setFilters] = useState(defaults);
  const [draft, setDraft] = useState("");
  const [items, setItems] = useState<FraudCaseListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    const params: Record<string, string | number> = { review_required: "true", limit: 25, page };
    for (const [key, value] of Object.entries(filters)) if (value) params[key] = value;
    api.getCases(params).then(data => {
      if (!active) return;
      setItems(data.items); setTotal(data.total);
    }).catch(e => {
      if (active) { setError(String(e)); setItems([]); setTotal(0); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, page, refresh]);

  function start() { setLoading(true); setError(""); }
  function change(key: keyof typeof defaults, value: string) {
    start(); setPage(1); setFilters(current => ({ ...current, [key]: value }));
  }
  function reset() { start(); setDraft(""); setFilters({ ...defaults }); setPage(1); }
  const filtered = Object.entries(filters).some(([key, value]) => value !== defaults[key as keyof typeof defaults]);

  return <div className="review-page space-y-6">
    <header className="flex items-start justify-between gap-4">
      <div><p className="mb-1 text-xs font-medium text-gray-500">Operations</p><h1>Alerts</h1>
        <p role="status" className="mt-2 text-sm text-gray-500">{loading ? "Updating queue..." : error ? "Queue unavailable" : `${total.toLocaleString()} ${filtered ? "matching" : "open"} ${total === 1 ? "transaction" : "transactions"}`}</p></div>
      <RefreshButton loading={loading} onClick={() => { start(); setRefresh(v => v + 1); }} />
    </header>
    <div className="grid grid-cols-2 items-end gap-3 xl:grid-cols-[minmax(220px,2fr)_1fr_1fr_1fr_1fr_1fr_auto]">
      <form className="col-span-2 xl:col-span-1" onSubmit={e => { e.preventDefault(); change("search", draft.trim()); }}>
        <label htmlFor="queue-search" className="mb-1.5 block text-xs font-medium text-gray-600">Search transactions</label>
        <div className="relative"><input id="queue-search" className="review-input pr-10" type="search" maxLength={200} value={draft} onChange={e => setDraft(e.target.value)} placeholder="Account, source, reference..." />
          <button type="submit" className="absolute right-0 top-0 flex h-[38px] w-10 items-center justify-center text-gray-500" title="Search" aria-label="Search"><Search size={17} /></button></div>
      </form>
      <label className="text-xs font-medium text-gray-600">Status<select className="review-input mt-1.5" value={filters.status} onChange={e => change("status", e.target.value)}>
        <option value="">All open reviews</option><option value="OPEN">Open</option><option value="UNDER_REVIEW">Under review</option><option value="ESCALATED">Escalated</option><option value="CLEAN">Legacy clean / flagged</option>
      </select></label>
      <label className="text-xs font-medium text-gray-600">Direction<select className="review-input mt-1.5" value={filters.direction} onChange={e => change("direction", e.target.value)}>
        <option value="">Inward and outward</option><option value="INWARD">Inward</option><option value="OUTWARD">Outward</option>
      </select></label>
      <label className="text-xs font-medium text-gray-600">Review flag<select className="review-input mt-1.5" value={filters.flag} onChange={e => change("flag", e.target.value)}>
        <option value="">All flags</option><option value="structuring">Structuring alert</option><option value="ctr">CTR review</option><option value="sar">SAR review</option><option value="sanctions">Possible sanctions match</option>
      </select></label>
      <label className="text-xs font-medium text-gray-600">Risk score<select className="review-input mt-1.5" value={filters.min_risk} onChange={e => change("min_risk", e.target.value)}>
        <option value="">All scores</option><option value="31">Medium and above</option><option value="56">High and above</option><option value="76">Critical</option>
      </select></label>
      <label className="text-xs font-medium text-gray-600">Sort by<select className="review-input mt-1.5" value={filters.sort} onChange={e => change("sort", e.target.value)}>
        <option value="risk">Highest risk</option><option value="recent">Newest first</option>
      </select></label>
      <button className="review-icon" disabled={!filtered && !draft} onClick={reset} title="Reset filters" aria-label="Reset filters"><X size={16} /></button>
    </div>
    {error ? <LoadError message={error} retry={() => { start(); setRefresh(v => v + 1); }} /> : <>
      <ReviewTable items={items} loading={loading} empty={filtered ? "No transactions match these filters." : "No transactions awaiting review."} />
      {!loading && !items.length && filtered && <button onClick={reset} className="text-sm font-medium text-blue-700 hover:underline">Clear filters</button>}
      <Pagination page={page} total={total} limit={25} loading={loading} onChange={next => { start(); setPage(next); }} />
    </>}
  </div>;
}
