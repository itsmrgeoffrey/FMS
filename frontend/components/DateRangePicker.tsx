"use client";
import { useCallback } from "react";
import type { DateRange } from "@/lib/api";

const PRESETS: { label: string; days: number | null }[] = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: null },
];

/** Local calendar date, not UTC. `toISOString()` would shift the day for anyone
 *  east or west of GMT and silently drop a day off the end of a range. */
function iso(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function rangeForDays(days: number): DateRange {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - (days - 1)); // inclusive of today
  return { date_from: iso(from), date_to: iso(to) };
}

function matchesPreset(v: DateRange, days: number | null): boolean {
  if (days === null) return !v.date_from && !v.date_to;
  const r = rangeForDays(days);
  return v.date_from === r.date_from && v.date_to === r.date_to;
}

const inputCls =
  "rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-gray-700 shadow-sm " +
  "focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100";

/**
 * Inclusive day-range filter used by the transactions, reports and audit views.
 * Either end may be left empty for an open-ended range.
 */
export default function DateRangePicker({
  value,
  onChange,
  className = "",
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
  className?: string;
}) {
  const applyPreset = useCallback(
    (days: number | null) => onChange(days === null ? {} : rangeForDays(days)),
    [onChange],
  );

  const isFiltered = Boolean(value.date_from || value.date_to);

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <div className="flex rounded-lg bg-gray-100 p-1 text-sm font-medium">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => applyPreset(p.days)}
            className={`px-2.5 py-1 rounded-md transition-colors ${
              matchesPreset(value, p.days)
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1.5 text-sm">
        <input
          type="date"
          aria-label="From date"
          value={value.date_from ?? ""}
          max={value.date_to || undefined}
          onChange={(e) => onChange({ ...value, date_from: e.target.value || undefined })}
          className={inputCls}
        />
        <span className="text-gray-400" aria-hidden>&rarr;</span>
        <input
          type="date"
          aria-label="To date"
          value={value.date_to ?? ""}
          min={value.date_from || undefined}
          onChange={(e) => onChange({ ...value, date_to: e.target.value || undefined })}
          className={inputCls}
        />
        {isFiltered && (
          <button
            type="button"
            onClick={() => onChange({})}
            className="ml-0.5 rounded-md px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
