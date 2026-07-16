"""Sanctions and watch-list screening.

Screens transaction parties against, in order of severity:

  * **OFAC SDN** (`data/ofac_sdn.json`, or the bundled sample) — a hit is the
    most serious signal FMS produces: under OFAC regulations a US person
    generally must **block or reject** the transaction and report it to OFAC.
  * **OFAC Consolidated non-SDN lists** (`data/ofac_consolidated.json`) — e.g.
    Sectoral Sanctions (SSI). A match carries *program-specific* restrictions,
    not a blanket block obligation: FMS raises a review-required case.
  * **Institution-supplied lists** (`data/extra_lists/*.json`) — bring-your-own
    UN / EU / UK or internal watch lists. Same JSON shape as the OFAC files:
    `[{"name": ..., "program": ..., "type": ..., "source": ..., "list_type": ...}]`
    with `list_type` one of `"SDN"`-like blocking (`"SDN"`), review (`"OTHER"`,
    the default) or `"PEP"`.
  * **PEP list** (`data/pep.json`) — enhanced-due-diligence signal only.

Both OFAC files are produced by `scripts/update_ofac.py` (or the in-app
refresh). Matching is intentionally transparent (normalized exact +
token-overlap + string similarity) so every hit is explainable. It is a
screening aid, not a determination — a human must adjudicate every alert.

Deliberately out of scope (documented, not silently missing): the OFAC 50%
ownership rule requires beneficial-ownership data FMS does not hold; screening
here is name-based only.
"""
import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_FULL_LIST = _DATA_DIR / "ofac_sdn.json"
_SAMPLE_LIST = _DATA_DIR / "ofac_sdn.sample.json"
# OFAC Consolidated (non-SDN) lists — e.g. Sectoral Sanctions. Program-specific
# restrictions, not a blanket block: matches are review-required, not block/reject.
_CONSOLIDATED_LIST = _DATA_DIR / "ofac_consolidated.json"
# Institution-supplied lists (UN/EU/UK or internal watch lists), one JSON file
# per list. Entries may carry their own list_type; default "OTHER" (review).
_EXTRA_LISTS_DIR = _DATA_DIR / "extra_lists"
# Optional politically-exposed-persons list (same JSON shape). PEP matches are
# an enhanced-due-diligence signal, NOT a block/reject obligation like SDN hits —
# callers distinguish them via SanctionsMatch.list_type.
_PEP_LIST = _DATA_DIR / "pep.json"

# Corporate suffixes carry no identifying value and cause false matches ("CO",
# "LTD" appear in thousands of names) — strip them before comparing.
_NOISE_TOKENS = {
    "LTD", "LLC", "INC", "CORP", "CO", "LLP", "PLC", "GMBH", "SA", "AG", "LP",
    "LIMITED", "COMPANY", "CORPORATION", "INCORPORATED", "THE", "AND",
}

DEFAULT_THRESHOLD = 0.90

# When the same name appears on multiple lists, the more severe listing must
# win (an SDN block obligation never loses to a PEP/watch-list annotation).
_SEVERITY = {"SDN": 3, "NON_SDN": 2, "OTHER": 2, "PEP": 1}


@dataclass
class SanctionsMatch:
    query: str
    matched_name: str
    score: float          # 0.0–1.0
    program: str
    sdn_type: str
    source: str
    # "SDN" (block/reject) · "NON_SDN" (OFAC Consolidated — program-specific,
    # review required) · "OTHER" (institution-supplied list — review required)
    # · "PEP" (enhanced due diligence only)
    list_type: str = "SDN"


def _normalize(name: str | None) -> str:
    n = (name or "").upper()
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    tokens = [t for t in n.split() if t and t not in _NOISE_TOKENS]
    return " ".join(tokens)


_entries: list[dict] | None = None
# Performance indexes over _entries, built at load time. With the full OFAC list
# (~40k names) a linear fuzzy scan costs seconds per screen; the trigram index
# narrows each query to a small candidate set before any similarity scoring,
# and the exact-name map answers clean hits in O(1).
_exact: dict[str, int] = {}
_trigram_index: dict[str, list[int]] = {}
_trigrams_per_entry: list[int] = []
_screen_cache: dict[tuple[str, float], "SanctionsMatch | None"] = {}


def _trigrams(norm: str) -> set[str]:
    """Padded per-token trigrams — token order doesn't change the set."""
    grams: set[str] = set()
    for token in norm.split():
        padded = f"  {token} "
        grams.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return grams


def _build_indexes() -> None:
    global _exact, _trigram_index, _trigrams_per_entry
    _exact = {}
    _trigram_index = {}
    _trigrams_per_entry = []
    _screen_cache.clear()
    for i, e in enumerate(_entries or []):
        norm = e["norm"]
        if norm:
            prev = _exact.get(norm)
            if prev is None or (
                _SEVERITY.get(e.get("list_type", "SDN"), 0)
                > _SEVERITY.get((_entries or [])[prev].get("list_type", "SDN"), 0)
            ):
                _exact[norm] = i
        grams = _trigrams(norm)
        _trigrams_per_entry.append(len(grams))
        for g in grams:
            _trigram_index.setdefault(g, []).append(i)


def _load() -> list[dict]:
    """Load and cache the sanctions list. Prefers the full list, falls back to sample."""
    global _entries
    if _entries is not None:
        return _entries

    path = _FULL_LIST if _FULL_LIST.exists() else _SAMPLE_LIST

    def read(p: Path, default_source: str, list_type: str) -> list[dict]:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Could not load screening list from {p}: {e}")
            return []
        return [
            {
                "name": r.get("name", ""),
                "norm": _normalize(r.get("name", "")),
                "program": r.get("program", ""),
                "type": r.get("type", ""),
                "source": r.get("source", default_source),
                "list_type": list_type,
            }
            for r in raw
            if r.get("name")
        ]

    _entries = read(path, "OFAC SDN", "SDN")
    if _CONSOLIDATED_LIST.exists():
        cons = read(_CONSOLIDATED_LIST, "OFAC Consolidated (non-SDN)", "NON_SDN")
        _entries += cons
        log.info(f"Sanctions screening: loaded {len(cons)} OFAC Consolidated (non-SDN) entries")
    if _EXTRA_LISTS_DIR.is_dir():
        for extra in sorted(_EXTRA_LISTS_DIR.glob("*.json")):
            rows = read(extra, extra.stem, "OTHER")
            # An entry may declare its own list_type (e.g. a UN list an operator
            # treats as blocking); read() applied the default, so re-honor it.
            try:
                declared = {r.get("name"): r.get("list_type") for r in json.loads(extra.read_text(encoding="utf-8"))}
                for r in rows:
                    lt = (declared.get(r["name"]) or "").upper()
                    if lt in ("SDN", "NON_SDN", "OTHER", "PEP"):
                        r["list_type"] = lt
            except Exception:
                pass
            _entries += rows
            log.info(f"Sanctions screening: loaded {len(rows)} entries from extra list {extra.name}")
    if _PEP_LIST.exists():
        pep = read(_PEP_LIST, "PEP list", "PEP")
        _entries += pep
        log.info(f"Sanctions screening: loaded {len(pep)} PEP entries from {_PEP_LIST.name}")

    using = "full OFAC list" if path == _FULL_LIST else "bundled SAMPLE list (run scripts/update_ofac.py for the live list)"
    _build_indexes()
    log.info(f"Sanctions screening: loaded {len(_entries)} entries — {using}")
    return _entries


def reload() -> int:
    """Force a reload of the list (e.g. after refreshing the data file). Returns entry count."""
    global _entries
    _entries = None
    return len(_load())


def _parse_ofac_csv(prim_raw: str, alt_raw: str, source: str) -> list[dict]:
    """Parse an OFAC primary+alias CSV pair (sdn.csv/alt.csv or the Consolidated
    cons_prim.csv/cons_alt.csv — same column layout) into screening entries."""
    import csv as _csv
    import io

    entries: list[dict] = []
    program_by_ent: dict[str, str] = {}
    _EMPTY = {"-0-", ""}
    for row in _csv.reader(io.StringIO(prim_raw)):
        if len(row) < 4 or row[1].strip() in _EMPTY:
            continue
        program_by_ent[row[0]] = row[3].strip()
        entries.append({"name": row[1].strip(),
                        "type": row[2].strip() if row[2].strip() not in _EMPTY else "",
                        "program": row[3].strip() if row[3].strip() not in _EMPTY else "",
                        "source": source})
    for row in _csv.reader(io.StringIO(alt_raw)):
        if len(row) < 4 or row[3].strip() in _EMPTY:
            continue
        entries.append({"name": row[3].strip(), "type": "",
                        "program": program_by_ent.get(row[0], ""), "source": f"{source} (alias)"})
    return entries


def refresh_from_treasury() -> int:
    """Download the live OFAC SDN + alias lists (and, best-effort, the
    Consolidated non-SDN lists), rewrite the data files, and reload. Blocking
    (run in an executor). Returns the new entry count; raises on SDN download
    failure (caller logs and keeps the current list). A Consolidated-list
    failure is non-fatal — SDN screening must never be blocked by it."""
    import json as _json
    import httpx

    with httpx.Client(follow_redirects=True, timeout=120) as client:
        sdn_raw = client.get("https://www.treasury.gov/ofac/downloads/sdn.csv").raise_for_status().content.decode("latin-1")
        alt_raw = client.get("https://www.treasury.gov/ofac/downloads/alt.csv").raise_for_status().content.decode("latin-1")
        _FULL_LIST.parent.mkdir(exist_ok=True)
        _FULL_LIST.write_text(
            _json.dumps(_parse_ofac_csv(sdn_raw, alt_raw, "OFAC SDN"), ensure_ascii=False),
            encoding="utf-8",
        )

        try:
            cons_raw = client.get("https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv").raise_for_status().content.decode("latin-1")
            cons_alt_raw = client.get("https://www.treasury.gov/ofac/downloads/consolidated/cons_alt.csv").raise_for_status().content.decode("latin-1")
            _CONSOLIDATED_LIST.write_text(
                _json.dumps(_parse_ofac_csv(cons_raw, cons_alt_raw, "OFAC Consolidated (non-SDN)"), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning(f"OFAC Consolidated (non-SDN) refresh failed (keeping current file): {e}")

    return reload()


def _similarity(a: str, b: str) -> float:
    """Blend token-overlap (order-independent) with sequence similarity."""
    seq = SequenceMatcher(None, a, b).ratio()
    at, bt = set(a.split()), set(b.split())
    jac = len(at & bt) / len(at | bt) if (at and bt) else 0.0
    return max(seq, jac)


def _make_match(name: str | None, e: dict, score: float) -> SanctionsMatch:
    return SanctionsMatch(
        query=name or "",
        matched_name=e["name"],
        score=round(score, 3),
        program=e["program"],
        sdn_type=e["type"],
        source=e["source"],
        list_type=e.get("list_type", "SDN"),
    )


def screen(name: str | None, threshold: float = DEFAULT_THRESHOLD) -> SanctionsMatch | None:
    """Return the best sanctions match for `name` at/above `threshold`, else None."""
    q = _normalize(name)
    if not q:
        return None

    entries = _load()
    cache_key = (q, threshold)
    if cache_key in _screen_cache:
        return _screen_cache[cache_key]

    # Fast path: exact normalized match.
    idx = _exact.get(q)
    if idx is not None:
        result = _make_match(name, entries[idx], 1.0)
        _screen_cache[cache_key] = result
        return result

    # Candidate generation: entries sharing enough trigrams with the query.
    # A 0.90 similarity requires substantial character overlap, so requiring
    # ~half the query's trigrams keeps recall while cutting 40k entries to tens.
    q_grams = _trigrams(q)
    counts: dict[int, int] = {}
    for g in q_grams:
        for i in _trigram_index.get(g, ()):
            counts[i] = counts.get(i, 0) + 1

    min_shared = max(2, len(q_grams) // 2)
    candidates = [i for i, c in counts.items() if c >= min_shared]
    # Guard the pathological case (very short/common names): score only the
    # strongest-overlapping candidates.
    if len(candidates) > 500:
        candidates = sorted(candidates, key=lambda i: -counts[i])[:500]

    best: SanctionsMatch | None = None
    for i in candidates:
        e = entries[i]
        if not e["norm"]:
            continue
        score = _similarity(q, e["norm"])
        if score < threshold:
            continue
        if (
            best is None
            or score > best.score
            or (score == best.score
                and _SEVERITY.get(e.get("list_type", "SDN"), 0) > _SEVERITY.get(best.list_type, 0))
        ):
            best = _make_match(name, e, score)

    _screen_cache[cache_key] = best
    if len(_screen_cache) > 10_000:  # bound memory across long uptimes
        _screen_cache.clear()
    return best
