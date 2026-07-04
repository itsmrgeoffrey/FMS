"""OFAC sanctions screening.

Screens a transaction counterparty against the US Treasury OFAC Specially
Designated Nationals (SDN) list. A hit is the most serious signal FMS produces:
under OFAC regulations a US person generally must **block or reject** a
transaction involving a listed party and report it to OFAC — this is separate
from, and overrides, the fraud-risk score.

The list is loaded from `data/ofac_sdn.json` (produced by `scripts/update_ofac.py`
from the live OFAC download) if present, otherwise from the bundled
`data/ofac_sdn.sample.json` so the system works out of the box for testing.

Matching is intentionally transparent (normalized exact + token-overlap + string
similarity) so every hit is explainable. It is a screening aid, not a
determination — a human must adjudicate every alert.
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


@dataclass
class SanctionsMatch:
    query: str
    matched_name: str
    score: float          # 0.0–1.0
    program: str
    sdn_type: str
    source: str
    list_type: str = "SDN"   # "SDN" (block/reject) or "PEP" (enhanced due diligence)


def _normalize(name: str | None) -> str:
    n = (name or "").upper()
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    tokens = [t for t in n.split() if t and t not in _NOISE_TOKENS]
    return " ".join(tokens)


_entries: list[dict] | None = None


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
    if _PEP_LIST.exists():
        pep = read(_PEP_LIST, "PEP list", "PEP")
        _entries += pep
        log.info(f"Sanctions screening: loaded {len(pep)} PEP entries from {_PEP_LIST.name}")

    using = "full OFAC list" if path == _FULL_LIST else "bundled SAMPLE list (run scripts/update_ofac.py for the live list)"
    log.info(f"Sanctions screening: loaded {len(_entries)} entries — {using}")
    return _entries


def reload() -> int:
    """Force a reload of the list (e.g. after refreshing the data file). Returns entry count."""
    global _entries
    _entries = None
    return len(_load())


def _similarity(a: str, b: str) -> float:
    """Blend token-overlap (order-independent) with sequence similarity."""
    seq = SequenceMatcher(None, a, b).ratio()
    at, bt = set(a.split()), set(b.split())
    jac = len(at & bt) / len(at | bt) if (at and bt) else 0.0
    return max(seq, jac)


def screen(name: str | None, threshold: float = DEFAULT_THRESHOLD) -> SanctionsMatch | None:
    """Return the best sanctions match for `name` at/above `threshold`, else None."""
    q = _normalize(name)
    if not q:
        return None

    best: SanctionsMatch | None = None
    for e in _load():
        en = e["norm"]
        if not en:
            continue
        score = 1.0 if en == q else _similarity(q, en)
        if score >= threshold and (best is None or score > best.score):
            best = SanctionsMatch(
                query=name or "",
                matched_name=e["name"],
                score=round(score, 3),
                program=e["program"],
                sdn_type=e["type"],
                source=e["source"],
                list_type=e.get("list_type", "SDN"),
            )
    return best
