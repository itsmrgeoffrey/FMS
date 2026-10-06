export default function Pagination({ page, total, limit, loading, onChange }: {
  page: number; total: number; limit: number; loading: boolean; onChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / limit));
  return <nav aria-label="Pagination" className="flex items-center justify-end gap-3 text-sm text-gray-600">
    <span>{total} records · Page {page} of {pages}</span>
    <button title="Previous page" aria-label="Previous page" disabled={loading || page <= 1}
      onClick={() => onChange(page - 1)} className="w-9 h-9 border rounded disabled:opacity-30">←</button>
    <button title="Next page" aria-label="Next page" disabled={loading || page >= pages}
      onClick={() => onChange(page + 1)} className="w-9 h-9 border rounded disabled:opacity-30">→</button>
  </nav>;
}
