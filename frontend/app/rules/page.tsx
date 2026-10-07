"use client";
import { useEffect, useState } from "react";
import { Plus, Play, Save } from "lucide-react";
import { api, auth } from "@/lib/api";
import { LoadError, RefreshButton } from "@/components/ReviewUI";
import type { BacktestResult, RuleChangeEntry, RulesConfig } from "@/types";

const COVERAGE_STYLE: Record<string, string> = {
  direct: "bg-green-50 text-green-700",
  partial: "bg-amber-50 text-amber-700",
  screening: "bg-blue-50 text-blue-700",
};

export default function RulesPage() {
  const [cfg, setCfg] = useState<RulesConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [benchmarks, setBenchmarks] = useState<Record<string, string>>({});
  const [currency, setCurrency] = useState("");
  const [amount, setAmount] = useState("");
  const [allowEmpty, setAllowEmpty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [logError, setLogError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [rationale, setRationale] = useState("");
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [changes, setChanges] = useState<RuleChangeEntry[]>([]);
  const isAdmin = auth.user()?.role === "admin";
  const busy = loading || saving || testing;

  useEffect(() => {
    let active = true;
    async function load() {
    try {
      const c = await api.getRules();
      if (!active) return;
      setError(null);
      setLogError(null);
      setCfg(c);
      setEdit({
        structuring_band_ratio: String(c.detection_parameters.structuring_band_ratio),
        rolling_window_days: String(c.detection_parameters.rolling_window_days),
        smurfing_window_hours: String(c.detection_parameters.smurfing_window_hours),
      });
      setBenchmarks(Object.fromEntries(Object.entries(c.regulatory_thresholds.ctr_by_currency).map(([key, value]) => [key, String(value)])));
      setBacktest(null);
      setAllowEmpty(false);
      const history = await api.getRuleChanges().catch(e => { if (active) setLogError(String(e)); return { items: [] }; });
      if (active) setChanges(history.items);
    } catch (e) { if (active) setError(String(e)); }
    finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, [refresh]);
  function reload() { setLoading(true); setRefresh(value => value + 1); }

  function invalidate() { setBacktest(null); setAllowEmpty(false); setNotice(null); }
  function addCurrency() {
    const code = currency.trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(code) || code in benchmarks || !Number.isFinite(Number(amount)) || Number(amount) <= 0) return;
    setBenchmarks(p => ({ ...p, [code]: amount })); setCurrency(""); setAmount(""); invalidate();
  }
  const valid = Object.values(benchmarks).every(v => v.trim() && Number.isFinite(Number(v)) && Number(v) > 0) &&
    Number(edit.structuring_band_ratio) > 0 && Number(edit.structuring_band_ratio) < 1 &&
    Number.isInteger(Number(edit.rolling_window_days)) && Number(edit.rolling_window_days) >= 1 && Number(edit.rolling_window_days) <= 365 &&
    Number.isInteger(Number(edit.smurfing_window_hours)) && Number(edit.smurfing_window_hours) >= 1 && Number(edit.smurfing_window_hours) <= 8760;

  function proposedRules() {
    return {
      structuring_band_ratio: Number(edit.structuring_band_ratio),
      rolling_window_days: Number(edit.rolling_window_days),
      smurfing_window_hours: Number(edit.smurfing_window_hours),
      ctr_thresholds: Object.fromEntries(Object.entries(benchmarks).map(([key, value]) => [key, Number(value)])),
    };
  }

  async function runBacktest() {
    setTesting(true);
    invalidate();
    setError(null);
    try {
      setBacktest(await api.backtestRules(proposedRules()));
    } catch (e) {
      setError(String(e));
    } finally {
      setTesting(false);
    }
  }

  async function saveRules() {
    if (!cfg || !backtest || !valid || !rationale.trim()) return;
    setSaving(true);
    setNotice(null);
    setError(null);
    try {
      const result = await api.updateSettings({
        rules: proposedRules(),
        rules_rationale: rationale.trim(),
        rules_base_version: cfg.revision,
        rules_allow_empty_history: allowEmpty,
      });
      setNotice(result.pending ? "Submitted for second-person approval. Live rules are unchanged." : result.saved ? "Rules applied. Change reason and server replay recorded." : "No effective rule change.");
      setRationale("");
      setBacktest(null);
      reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (!cfg) return <div className="p-6">{error ? <LoadError message={error} retry={reload} /> : <p role="status" className="py-12 text-center text-sm text-gray-500">Loading rules...</p>}</div>;

  return (
    <div className="p-4 sm:p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-gray-900">Rule Engine</h1>
        <RefreshButton loading={busy} onClick={() => { if (window.confirm("Reload rules and discard unsaved edits?")) reload(); }} />
      </div>
      {error && <LoadError message={error} retry={reload} />}
      {notice && <p role="status" className="border-l-4 border-blue-500 bg-blue-50 p-3 text-sm text-blue-800">{notice}</p>}

      {/* Regulatory thresholds */}
      <section className="border-t border-gray-200 pt-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Behavioral benchmarks</h2>
        <p className="text-xs text-gray-400 mb-4">{cfg.regulatory_thresholds.note}</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(benchmarks).sort(([a], [b]) => a.localeCompare(b)).map(([cur, val]) => (
            <div key={cur}>
              <label htmlFor={`benchmark-${cur}`} className="mb-1 block text-xs font-medium text-gray-600">{cur} high value</label>
              <input id={`benchmark-${cur}`} type="number" min="0.000001" step="any" disabled={!isAdmin || busy} value={val}
                onChange={e => { setBenchmarks(p => ({ ...p, [cur]: e.target.value })); invalidate(); }}
                className="w-full min-w-0 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50" />
            </div>
          ))}
        </div>
        {isAdmin && <fieldset disabled={busy} className="mt-4 flex min-w-0 flex-wrap items-end gap-3">
          <div className="w-28"><label htmlFor="new-currency" className="mb-1 block text-xs font-medium text-gray-600">New currency</label><input id="new-currency" maxLength={3} value={currency} onChange={e => setCurrency(e.target.value.toUpperCase())} placeholder="KES" className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" /></div>
          <div className="w-40"><label htmlFor="new-benchmark" className="mb-1 block text-xs font-medium text-gray-600">Benchmark</label><input id="new-benchmark" type="number" min="0.000001" step="any" value={amount} onChange={e => setAmount(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" /></div>
          <button type="button" onClick={addCurrency} title="Add currency benchmark" aria-label="Add currency benchmark" disabled={!/^[A-Z]{3}$/.test(currency) || currency in benchmarks || !Number.isFinite(Number(amount)) || Number(amount) <= 0} className="review-icon"><Plus size={18} /></button>
        </fieldset>}
      </section>

      {/* Detection parameters */}
      <section className="border-t border-gray-200 pt-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Detection windows</h2>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-semibold text-gray-900">{Math.round(cfg.detection_parameters.structuring_band_ratio * 100)}%</p>
            <p className="text-xs text-gray-400 mt-1">structuring band (of threshold)</p>
          </div>
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-semibold text-gray-900">{cfg.detection_parameters.rolling_window_days}d</p>
            <p className="text-xs text-gray-400 mt-1">velocity window</p>
          </div>
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-semibold text-gray-900">{cfg.detection_parameters.smurfing_window_hours}h</p>
            <p className="text-xs text-gray-400 mt-1">smurfing window</p>
          </div>
        </div>
      </section>

      {/* Admin tuning */}
      {isAdmin && (
        <section className="border-t border-gray-200 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Change review</h2>
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={runBacktest} disabled={busy || !valid}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100 disabled:opacity-50"><Play size={16} />
                {testing ? "Replaying..." : "Backtest proposed"}
              </button>
              <button onClick={saveRules} disabled={busy || !valid || !rationale.trim() || !backtest || (!backtest.replayed && !allowEmpty)}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"><Save size={16} />
                {saving ? "Submitting..." : "Submit change"}
              </button>
            </div>
          </div>
          <fieldset disabled={busy} className="grid min-w-0 gap-4 sm:grid-cols-3">
            {([
              ["structuring_band_ratio", "Structuring band ratio"],
              ["rolling_window_days", "Velocity window (days)"],
              ["smurfing_window_hours", "Smurfing window (hours)"],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label htmlFor={key} className="block text-xs text-gray-500 font-medium mb-1">{label}</label>
                <input id={key} type="number" step={key === "structuring_band_ratio" ? "0.01" : "1"} value={edit[key] ?? ""}
                  onChange={(e) => { setEdit((p) => ({ ...p, [key]: e.target.value })); invalidate(); }}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            ))}
          </fieldset>

          {backtest && backtest.replayed > 0 && (
            <div className="mt-4 border border-blue-100 bg-blue-50/50 rounded-lg p-4">
              <p className="text-xs font-semibold text-gray-700 mb-2">
                Backtest — {backtest.replayed.toLocaleString()} transactions replayed ({backtest.window_days}d window), {backtest.changed_count} verdict(s) would change
              </p>
              <div className="grid gap-3 sm:grid-cols-3 mb-2">
                {([["Flagged", "flagged"], ["SAR recommended", "sar_recommended"], ["CTR required", "ctr_required"]] as const).map(([label, key]) => (
                  <div key={key} className="p-2">
                    <p className="text-xs text-gray-400">{label}</p>
                    <p className="text-sm font-semibold text-gray-900">
                      {backtest.current[key]} → <span className={backtest.proposed[key] === backtest.current[key] ? "" : "text-blue-700"}>{backtest.proposed[key]}</span>
                    </p>
                  </div>
                ))}
              </div>
              {backtest.changed_examples.length > 0 && (
                <div className="max-h-40 overflow-y-auto text-xs text-gray-600 space-y-1">
                  {backtest.changed_examples.map((c) => (
                    <p key={`${c.external_id}-${c.account_id}-${c.timestamp}`} className="break-words">
                      {c.account_id} · {c.currency} {c.amount.toLocaleString()} — {c.current.level}{c.current.flagged ? " (flagged)" : ""} → {c.proposed.level}{c.proposed.flagged ? " (flagged)" : ""}
                    </p>
                  ))}
                </div>
              )}
              <p className="text-[11px] text-gray-400 mt-2">{backtest.note}</p>
            </div>
          )}
          {backtest?.error && <p className="text-sm mt-3 text-amber-700">{backtest.error}</p>}
          {backtest && !backtest.replayed && <label className="mt-3 flex items-start gap-2 text-sm text-amber-900"><input type="checkbox" checked={allowEmpty} disabled={busy} onChange={e => setAllowEmpty(e.target.checked)} className="mt-1 shrink-0" />I acknowledge initial configuration without historical validation.</label>}

          <div className="mt-4">
            <label htmlFor="rationale" className="block text-xs text-gray-500 font-medium mb-1">Reason for change (required)</label>
            <textarea id="rationale" required disabled={busy} value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2}
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </section>
      )}

      <details className="border-t border-gray-200 pt-5">
        <summary className="cursor-pointer text-sm font-semibold text-gray-800">Scoring and coverage</summary>
        <div className="mt-4 space-y-5">
      {/* Scoring components */}
      <section className="border-t border-gray-200 pt-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Scoring components</h2>
        <div className="space-y-2">
          {cfg.scoring_components.map((c) => (
            <div key={c.name} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
              <span className={`text-xs font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${c.points.startsWith("-") ? "bg-green-50 text-green-700" : "bg-blue-50 text-blue-700"}`}>
                {c.points}
              </span>
              <div>
                <p className="text-sm font-medium text-gray-800">{c.name}</p>
                <p className="text-xs text-gray-500">{c.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Risk levels + sanctions */}
      <div className="grid md:grid-cols-2 gap-6">
        <section className="border-t border-gray-200 pt-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Risk levels</h2>
          {cfg.risk_levels.map((r) => (
            <div key={r.level} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0">
              <span className="text-gray-700">{r.level}</span>
              <span className="text-gray-400">{r.range}</span>
            </div>
          ))}
        </section>
        <section className="border-t border-gray-200 pt-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Sanctions screening</h2>
          <p className="text-sm text-gray-700">{cfg.sanctions.list}</p>
          <p className="text-xs text-gray-500 mt-1">Match threshold: {cfg.sanctions.match_threshold}</p>
          <p className="text-xs text-gray-400 mt-2">{cfg.sanctions.note}</p>
        </section>
      </div>

      {/* National AML/CFT Priorities coverage */}
      {cfg.national_priorities && (
        <section className="border-t border-gray-200 pt-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">FinCEN National AML/CFT Priorities</h2>
          <p className="text-xs text-gray-400 mb-4">{cfg.national_priorities.note}</p>
          <div className="space-y-2">
            {cfg.national_priorities.items.map((p) => (
              <div key={p.priority} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5 uppercase ${COVERAGE_STYLE[p.coverage] ?? "bg-gray-100 text-gray-600"}`}>
                  {p.coverage}
                </span>
                <div>
                  <p className="text-sm font-medium text-gray-800">{p.priority}</p>
                  <p className="text-xs text-gray-500">{p.how}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

        </div>
      </details>

      {/* Tuning log */}
      <section className="border-t border-gray-200 pt-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Tuning log</h2>
        {logError && <LoadError message={logError} retry={reload} />}
        {!logError && changes.length === 0 && <p className="text-sm text-gray-400">No parameter changes recorded yet.</p>}
        <div className="space-y-3">
          {changes.map((ch) => {
            const diffs = Object.keys({ ...ch.old_values, ...ch.new_values })
              .filter((k) => k !== "ctr_thresholds" && JSON.stringify(ch.old_values[k]) !== JSON.stringify(ch.new_values[k]))
              .map((k) => `${k}: ${JSON.stringify(ch.old_values[k])} → ${JSON.stringify(ch.new_values[k])}`);
            const oldCtr = (ch.old_values.ctr_thresholds ?? {}) as Record<string, number>;
            const newCtr = (ch.new_values.ctr_thresholds ?? {}) as Record<string, number>;
            for (const cur of new Set([...Object.keys(oldCtr), ...Object.keys(newCtr)])) {
              if (oldCtr[cur] !== newCtr[cur]) diffs.push(`${cur} benchmark: ${oldCtr[cur] ?? "unset"} to ${newCtr[cur] ?? "unset"}`);
            }
            const bt = ch.backtest as { replayed?: number; changed_count?: number; storage_version?: number } | null;
            return (
              <div key={ch.id} className="border border-gray-100 rounded-lg p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-gray-500">
                    <span className="font-medium text-gray-800">{ch.changed_by}</span> · {new Date(/(?:Z|[+-]\d\d:\d\d)$/.test(ch.changed_at) ? ch.changed_at : `${ch.changed_at}Z`).toLocaleString()}
                  </p>
                  {bt?.replayed != null && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-medium">
                      {bt.storage_version === 1 ? bt.replayed ? `Server replay: ${bt.replayed} transactions, ${bt.changed_count} changed` : "Initial configuration / no replay history" : "Legacy evidence"}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-800 break-words mt-1">{diffs.join(" · ") || "(no effective change)"}</p>
                {ch.rationale && <p className="text-xs text-gray-600 mt-1 italic">“{ch.rationale}”</p>}
              </div>
            );
          })}
        </div>
      </section>

    </div>
  );
}
