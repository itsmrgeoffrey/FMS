"use client";
import { useEffect, useState } from "react";
import { api, auth } from "@/lib/api";
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
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [rationale, setRationale] = useState("");
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [changes, setChanges] = useState<RuleChangeEntry[]>([]);
  const isAdmin = auth.user()?.role === "admin";

  function load() {
    api.getRules().then((c) => {
      setCfg(c);
      setEdit({
        structuring_band_ratio: String(c.detection_parameters.structuring_band_ratio),
        rolling_window_days: String(c.detection_parameters.rolling_window_days),
        smurfing_window_hours: String(c.detection_parameters.smurfing_window_hours),
        sar_ratio: String(c.regulatory_thresholds.sar_ratio_of_ctr),
        usd_ctr: String(c.regulatory_thresholds.ctr_by_currency["USD"] ?? 10000),
      });
    }).catch((e) => setError(String(e)));
    api.getRuleChanges().then((r) => setChanges(r.items)).catch(() => setChanges([]));
  }
  useEffect(load, []);

  function proposedRules() {
    return {
      structuring_band_ratio: Number(edit.structuring_band_ratio),
      rolling_window_days: Number(edit.rolling_window_days),
      smurfing_window_hours: Number(edit.smurfing_window_hours),
      sar_ratio: Number(edit.sar_ratio),
      ctr_thresholds: { USD: Number(edit.usd_ctr) },
    };
  }

  async function runBacktest() {
    setTesting(true);
    setBacktest(null);
    try {
      setBacktest(await api.backtestRules(proposedRules()));
    } catch (e) {
      setNotice(String(e));
    } finally {
      setTesting(false);
    }
  }

  async function saveRules() {
    setSaving(true);
    setNotice(null);
    try {
      await api.updateSettings({
        rules: proposedRules(),
        rules_rationale: rationale.trim() || undefined,
        rules_backtest: backtest
          ? { replayed: backtest.replayed, current: backtest.current, proposed: backtest.proposed, changed_count: backtest.changed_count }
          : undefined,
      });
      setNotice("Saved — applied live to the engine and recorded in the tuning log and Audit Trail.");
      setRationale("");
      setBacktest(null);
      load();
    } catch (e) {
      setNotice(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>;
  if (!cfg) return <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">Loading…</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Rule Engine</h1>
        <p className="text-sm text-gray-500 mt-1">
          The detection engine is fully deterministic and explainable — every flag traces to these rules. No black box.
        </p>
      </div>

      {/* Regulatory thresholds */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Regulatory thresholds</h2>
        <p className="text-xs text-gray-400 mb-4">{cfg.regulatory_thresholds.note}</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(cfg.regulatory_thresholds.ctr_by_currency).map(([cur, val]) => (
            <div key={cur} className="border border-gray-100 rounded-lg p-3">
              <p className="text-xs text-gray-400">{cur} CTR</p>
              <p className="text-sm font-semibold text-gray-900">{val.toLocaleString()}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-500 mt-3">
          SAR threshold = CTR × <span className="font-semibold">{cfg.regulatory_thresholds.sar_ratio_of_ctr}</span>
        </p>
      </section>

      {/* Detection parameters */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Detection windows</h2>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-bold text-gray-900">{Math.round(cfg.detection_parameters.structuring_band_ratio * 100)}%</p>
            <p className="text-xs text-gray-400 mt-1">structuring band (of threshold)</p>
          </div>
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-bold text-gray-900">{cfg.detection_parameters.rolling_window_days}d</p>
            <p className="text-xs text-gray-400 mt-1">velocity window</p>
          </div>
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-bold text-gray-900">{cfg.detection_parameters.smurfing_window_hours}h</p>
            <p className="text-xs text-gray-400 mt-1">smurfing window</p>
          </div>
        </div>
      </section>

      {/* Scoring components */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
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
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Risk levels</h2>
          {cfg.risk_levels.map((r) => (
            <div key={r.level} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0">
              <span className="text-gray-700">{r.level}</span>
              <span className="text-gray-400">{r.range}</span>
            </div>
          ))}
        </section>
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Sanctions screening</h2>
          <p className="text-sm text-gray-700">{cfg.sanctions.list}</p>
          <p className="text-xs text-gray-500 mt-1">Match threshold: {cfg.sanctions.match_threshold}</p>
          <p className="text-xs text-gray-400 mt-2">{cfg.sanctions.note}</p>
        </section>
      </div>

      {/* National AML/CFT Priorities coverage */}
      {cfg.national_priorities && (
        <section className="bg-white rounded-lg border border-gray-200 p-5">
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

      {/* Admin tuning */}
      {isAdmin && (
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Tune rules</h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Backtest first, document why, then save — the FFIEC expects threshold changes to be assessed and documented.
              </p>
            </div>
            <div className="flex gap-2">
              <button onClick={runBacktest} disabled={testing}
                className="px-4 py-1.5 rounded-lg text-sm font-medium border border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100 disabled:opacity-50">
                {testing ? "Replaying..." : "Backtest proposed"}
              </button>
              <button onClick={saveRules} disabled={saving}
                className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50">
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {([
              ["usd_ctr", "USD CTR threshold"],
              ["sar_ratio", "SAR ratio (× CTR)"],
              ["structuring_band_ratio", "Structuring band ratio"],
              ["rolling_window_days", "Velocity window (days)"],
              ["smurfing_window_hours", "Smurfing window (hours)"],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label className="block text-xs text-gray-500 font-medium mb-1">{label}</label>
                <input type="number" step="any" value={edit[key] ?? ""}
                  onChange={(e) => setEdit((p) => ({ ...p, [key]: e.target.value }))}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            ))}
          </div>

          {backtest && !backtest.error && (
            <div className="mt-4 border border-blue-100 bg-blue-50/50 rounded-lg p-4">
              <p className="text-xs font-semibold text-gray-700 mb-2">
                Backtest — {backtest.replayed.toLocaleString()} transactions replayed ({backtest.window_days}d window), {backtest.changed_count} verdict(s) would change
              </p>
              <div className="grid grid-cols-3 gap-3 text-center mb-2">
                {([["Flagged", "flagged"], ["SAR recommended", "sar_recommended"], ["CTR required", "ctr_required"]] as const).map(([label, key]) => (
                  <div key={key} className="bg-white border border-gray-100 rounded-lg p-2">
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
                    <p key={c.external_id} className="font-mono">
                      {c.account_id} · {c.currency} {c.amount.toLocaleString()} — {c.current.level}{c.current.flagged ? " (flagged)" : ""} → {c.proposed.level}{c.proposed.flagged ? " (flagged)" : ""}
                    </p>
                  ))}
                </div>
              )}
              <p className="text-[11px] text-gray-400 mt-2">{backtest.note}</p>
            </div>
          )}
          {backtest?.error && <p className="text-sm mt-3 text-amber-700">{backtest.error}</p>}

          <div className="mt-4">
            <label className="block text-xs text-gray-500 font-medium mb-1">Rationale (recorded in the tuning log)</label>
            <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2}
              placeholder="Why this change? e.g. quarterly tuning review — velocity window widened after backtest showed missed clustering."
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          {notice && <p className="text-sm mt-3 text-green-700">{notice}</p>}
        </section>
      )}

      {/* Tuning log */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Tuning log</h2>
        <p className="text-xs text-gray-400 mb-3">Every parameter change with before/after values, actor, rationale, and backtest evidence.</p>
        {changes.length === 0 && <p className="text-sm text-gray-400">No parameter changes recorded yet.</p>}
        <div className="space-y-3">
          {changes.map((ch) => {
            const diffs = Object.keys({ ...ch.old_values, ...ch.new_values })
              .filter((k) => k !== "ctr_thresholds" && JSON.stringify(ch.old_values[k]) !== JSON.stringify(ch.new_values[k]))
              .map((k) => `${k}: ${JSON.stringify(ch.old_values[k])} → ${JSON.stringify(ch.new_values[k])}`);
            const oldCtr = (ch.old_values.ctr_thresholds ?? {}) as Record<string, number>;
            const newCtr = (ch.new_values.ctr_thresholds ?? {}) as Record<string, number>;
            for (const cur of new Set([...Object.keys(oldCtr), ...Object.keys(newCtr)])) {
              if (oldCtr[cur] !== newCtr[cur]) diffs.push(`CTR ${cur}: ${oldCtr[cur] ?? "—"} → ${newCtr[cur] ?? "—"}`);
            }
            const bt = ch.backtest as { replayed?: number; changed_count?: number } | null;
            return (
              <div key={ch.id} className="border border-gray-100 rounded-lg p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-gray-500">
                    <span className="font-medium text-gray-800">{ch.changed_by}</span> · {new Date(ch.changed_at + "Z").toLocaleString()}
                  </p>
                  {bt?.replayed != null && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-medium">
                      backtested: {bt.replayed} txns, {bt.changed_count} changed
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-800 font-mono mt-1">{diffs.join(" · ") || "(no effective change)"}</p>
                {ch.rationale && <p className="text-xs text-gray-600 mt-1 italic">“{ch.rationale}”</p>}
              </div>
            );
          })}
        </div>
      </section>

      <p className="text-xs text-gray-400">
        Parameters are documented with their rationale in MODEL.md. {isAdmin ? "Changes above apply immediately and are recorded in the tuning log and Audit Trail." : "Ask an administrator to tune thresholds."}
      </p>
    </div>
  );
}
