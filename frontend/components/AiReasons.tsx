export function AiReasons({ reasons, summary }: { reasons: string[]; summary: string | null }) {
  return (
    <div className="space-y-4">
      {reasons.length > 0 && (
        <ul className="space-y-2">
          {reasons.map((r, i) => (
            <li key={i} className="flex gap-2 text-sm text-gray-700">
              <span className="text-red-500 mt-0.5 shrink-0">•</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      )}
      {summary && (
        <p className="text-sm text-gray-600 leading-relaxed border-t border-gray-100 pt-3">
          {summary}
        </p>
      )}
    </div>
  );
}
