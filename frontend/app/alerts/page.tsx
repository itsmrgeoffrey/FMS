"use client";
import { useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { api, auth } from "@/lib/api";
import { useWebSocket } from "@/lib/useWebSocket";
import type { CaseBatch, FraudCaseListItem } from "@/types";
import Pagination from "@/components/Pagination";
import { LoadError, RefreshButton, ReviewTable } from "@/components/ReviewUI";

const defaults = { search: "", status: "", direction: "", flag: "", min_risk: "", sort: "recent" };
type Queue = "review" | "approvals" | "escalations" | "all";

export default function AlertsPage() {
  const role = auth.user()?.role;
  const canApprove = role === "approver" || role === "admin";
  const canInput = role === "analyst";
  const [queue, setQueue] = useState<Queue>(canApprove ? "approvals" : "review");
  const [filters, setFilters] = useState(defaults);
  const [draft, setDraft] = useState("");
  const [items, setItems] = useState<FraudCaseListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const [bulkAction, setBulkAction] = useState("");
  const [bulkReason, setBulkReason] = useState("");
  const [batch, setBatch] = useState<CaseBatch | null>(null);

  useWebSocket((data) => {
    const event = (data as { event?: string }).event;
    if (!event || !["new_case", "case_updated", "case_batch_completed"].includes(event)) return;
    setLoading(true); setRefresh(current => current + 1);
  });

  useEffect(() => {
    let active = true;
    const params: Record<string, string | number> = { queue, limit: 25, page };
    for (const [key, value] of Object.entries(filters)) if (value) params[key] = value;
    api.getCases(params).then(data => {
      if (!active) return;
      setError(""); setItems(data.items); setTotal(data.total);
    }).catch(e => {
      if (active) { setError(String(e)); setItems([]); setTotal(0); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filters, page, queue, refresh]);

  useEffect(() => {
    if (!batch || ["COMPLETED", "FAILED"].includes(batch.status)) return;
    const timer = window.setInterval(() => api.getCaseBatch(batch.id).then(next => {
      setBatch(next);
      if (["COMPLETED", "FAILED"].includes(next.status)) {
        setRefresh(value => value + 1); setSelected(new Set()); setAllMatching(false);
      }
    }).catch(() => undefined), 1200);
    return () => window.clearInterval(timer);
  }, [batch]);

  const actions = useMemo(() => {
    if (queue === "approvals" && canApprove) return [["APPROVE", "Approve decisions"], ["REJECT", "Reject and return"]];
    if (queue === "escalations" && canApprove) return [["REVIEW", "Claim senior review"]];
    if ((queue === "review" || queue === "all") && canInput) return [
      ["REVIEW", "Start review"], ["ESCALATED", "Escalate"],
      ["CONFIRMED", "Submit fraud"], ["DISMISSED", "Submit dismissal"],
    ];
    return [];
  }, [queue, canApprove, canInput]);

  function start() { setLoading(true); setError(""); }
  function clearSelection() { setSelected(new Set()); setAllMatching(false); setBulkAction(""); setBulkReason(""); }
  function change(key: keyof typeof defaults, value: string) {
    start(); clearSelection(); setPage(1); setFilters(current => ({ ...current, [key]: value }));
  }
  function changeQueue(value: Queue) { start(); clearSelection(); setQueue(value); setPage(1); }
  function reset() { start(); clearSelection(); setDraft(""); setFilters({ ...defaults }); setPage(1); }
  function toggle(id: string) {
    setAllMatching(false);
    setSelected(current => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  function togglePage() {
    setAllMatching(false);
    setSelected(current => {
      const next = new Set(current); const every = items.length > 0 && items.every(item => next.has(item.id));
      for (const item of items) {
        if (every) next.delete(item.id);
        else next.add(item.id);
      }
      return next;
    });
  }

  async function submitBulk() {
    const count = allMatching ? total : selected.size;
    if (!bulkAction || !bulkReason.trim() || !count) return;
    if (!window.confirm(`${actions.find(([key]) => key === bulkAction)?.[1] || bulkAction} for ${count.toLocaleString()} case(s)?`)) return;
    try {
      setError("");
      const activeFilters: Record<string, string | number> = { queue };
      for (const [key, value] of Object.entries(filters)) if (value && key !== "sort") activeFilters[key] = value;
      setBatch(await api.createCaseBatch({ action: bulkAction, rationale: bulkReason.trim(),
        case_ids: [...selected], all_matching: allMatching, filters: activeFilters }));
    } catch (e) { setError(String(e)); }
  }

  const filtered = Object.entries(filters).some(([key, value]) => value !== defaults[key as keyof typeof defaults]);
  const selectionCount = allMatching ? total : selected.size;
  const visibleSelection = allMatching ? new Set([...selected, ...items.map(item => item.id)]) : selected;

  return <div className="review-page space-y-6">
    <header className="flex items-start justify-between gap-4">
      <div><p className="mb-1 text-xs font-medium text-gray-500">Operations</p><h1>Alerts</h1>
        <p role="status" className="mt-2 text-sm text-gray-500">{loading ? "Updating queue..." : error ? "Queue unavailable" : `${total.toLocaleString()} ${queue === "approvals" ? "pending decisions" : queue === "escalations" ? "senior reviews" : "open cases"}`}</p></div>
      <RefreshButton loading={loading} onClick={() => { start(); setRefresh(v => v + 1); }} />
    </header>

    <nav className="flex flex-wrap gap-1 border-b border-gray-200" aria-label="Case queues">
      {(["review", "approvals", "escalations", "all"] as Queue[]).map(value => <button key={value} onClick={() => changeQueue(value)}
        className={`border-b-2 px-3 py-2 text-sm font-medium capitalize ${queue === value ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500"}`}>
        {value === "review" ? "Review queue" : value === "approvals" ? "Decision approvals" : value === "escalations" ? "Escalations" : "All open"}
      </button>)}
    </nav>

    <div className="grid grid-cols-2 items-end gap-3 xl:grid-cols-[minmax(220px,2fr)_1fr_1fr_1fr_1fr_1fr_auto]">
      <form className="col-span-2 xl:col-span-1" onSubmit={e => { e.preventDefault(); change("search", draft.trim()); }}>
        <label htmlFor="queue-search" className="mb-1.5 block text-xs font-medium text-gray-600">Search cases</label>
        <div className="relative"><input id="queue-search" className="review-input pr-10" type="search" maxLength={200} value={draft} onChange={e => setDraft(e.target.value)} placeholder="Account, source, reference..." />
          <button type="submit" className="absolute right-0 top-0 flex h-[38px] w-10 items-center justify-center text-gray-500" title="Search" aria-label="Search"><Search size={17} /></button></div>
      </form>
      <label className="text-xs font-medium text-gray-600">Status<select className="review-input mt-1.5" value={filters.status} onChange={e => change("status", e.target.value)}>
        <option value="">All statuses</option><option value="OPEN">Open</option><option value="UNDER_REVIEW">Under review</option><option value="PENDING_APPROVAL">Pending approval</option><option value="ESCALATED">Escalated</option><option value="CLEAN">Legacy obligation</option>
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
        <option value="recent">Newest first</option><option value="risk">Highest risk</option>
      </select></label>
      <button className="review-icon" disabled={!filtered && !draft} onClick={reset} title="Reset filters" aria-label="Reset filters"><X size={16} /></button>
    </div>

    {actions.length > 0 && selectionCount > 0 && <section className="border-y border-blue-200 bg-blue-50 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[150px]"><p className="text-sm font-semibold text-blue-950">{selectionCount.toLocaleString()} selected</p>
          {!allMatching && selected.size > 0 && total > selected.size && <button className="mt-1 text-xs font-medium text-blue-700 underline" onClick={() => setAllMatching(true)}>Select all {total.toLocaleString()} matching cases</button>}
          {allMatching && <button className="mt-1 text-xs font-medium text-blue-700 underline" onClick={clearSelection}>Clear selection</button>}
        </div>
        <label className="text-xs font-medium text-blue-950">Bulk action<select value={bulkAction} onChange={e => setBulkAction(e.target.value)} className="review-input mt-1.5 min-w-[190px]">
          <option value="">Choose action</option>{actions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <label className="min-w-[240px] flex-1 text-xs font-medium text-blue-950">Required rationale<input value={bulkReason} onChange={e => setBulkReason(e.target.value)} maxLength={2000} className="review-input mt-1.5" placeholder="Evidence and reason for this batch" /></label>
        <button disabled={!bulkAction || !bulkReason.trim() || !!batch && !["COMPLETED", "FAILED"].includes(batch.status)} onClick={submitBulk}
          className="rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">Submit batch</button>
      </div>
    </section>}

    {batch && <div role="status" className={`border-l-4 p-3 text-sm ${batch.status === "FAILED" || batch.failed ? "border-amber-500 bg-amber-50 text-amber-900" : "border-blue-500 bg-blue-50 text-blue-900"}`}>
      Batch {batch.status.toLowerCase()}: {batch.processed.toLocaleString()} / {batch.total.toLocaleString()} processed, {batch.succeeded.toLocaleString()} succeeded, {batch.failed.toLocaleString()} failed.
      {batch.errors.length > 0 && <ul className="mt-2 space-y-1">{batch.errors.slice(0, 5).map((entry, index) => <li key={index}>
        {entry.case_id ? `${entry.case_id.slice(0, 8)}: ` : ""}{entry.error}
      </li>)}</ul>}
    </div>}
    {error ? <LoadError message={error} retry={() => { start(); setRefresh(v => v + 1); }} /> : <>
      <ReviewTable items={items} loading={loading} selected={actions.length ? visibleSelection : undefined} onToggle={actions.length ? toggle : undefined} onTogglePage={actions.length ? togglePage : undefined}
        empty={filtered ? "No cases match these filters." : queue === "approvals" ? "No decisions awaiting approval." : queue === "escalations" ? "No escalated cases." : "No cases awaiting review."} />
      <Pagination page={page} total={total} limit={25} loading={loading} onChange={next => { start(); setPage(next); }} />
    </>}
  </div>;
}
