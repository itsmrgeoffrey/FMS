"""Download the live OFAC lists and write the screening data files.

Run periodically (OFAC updates the lists frequently — production programs
refresh at least daily):

    python scripts/update_ofac.py

Pulls the SDN list (sdn.csv + alt.csv aliases) into data/ofac_sdn.json and,
best-effort, the Consolidated non-SDN lists (cons_prim.csv + cons_alt.csv —
e.g. Sectoral Sanctions) into data/ofac_consolidated.json, normalized into the
JSON shape backend/services/sanctions.py expects. If the SDN download fails
(e.g. no network), it prints manual-download instructions and leaves existing
files untouched; a Consolidated failure is non-fatal.
"""
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OUT = DATA_DIR / "ofac_sdn.json"
OUT_CONS = DATA_DIR / "ofac_consolidated.json"

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
CONS_URL = "https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv"
CONS_ALT_URL = "https://www.treasury.gov/ofac/downloads/consolidated/cons_alt.csv"

# sdn.csv columns (no header): ent_num, name, sdn_type, program, title, ...
# alt.csv columns (no header): ent_num, alt_num, alt_type, alt_name, alt_remarks
_EMPTY = {"-0-", ""}


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "FMS-OFAC-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("latin-1")


def _parse_pair(prim_raw: str, alt_raw: str, source: str) -> list[dict]:
    """Parse an OFAC primary+alias CSV pair (SDN or Consolidated — same layout)."""
    entries: list[dict] = []

    # Primary names, plus a program lookup keyed by entity number for aliases.
    program_by_ent: dict[str, str] = {}
    for row in csv.reader(io.StringIO(prim_raw)):
        if len(row) < 4:
            continue
        ent_num, name, sdn_type, program = row[0], row[1].strip(), row[2].strip(), row[3].strip()
        if name in _EMPTY:
            continue
        program_by_ent[ent_num] = program
        entries.append({
            "name": name,
            "type": sdn_type if sdn_type not in _EMPTY else "",
            "program": program if program not in _EMPTY else "",
            "source": source,
        })

    # Alternate names / aliases.
    for row in csv.reader(io.StringIO(alt_raw)):
        if len(row) < 4:
            continue
        ent_num, alt_name = row[0], row[3].strip()
        if alt_name in _EMPTY:
            continue
        entries.append({
            "name": alt_name,
            "type": "",
            "program": program_by_ent.get(ent_num, ""),
            "source": f"{source} (alias)",
        })
    return entries


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    local_sdn = DATA_DIR / "sdn.csv"
    local_alt = DATA_DIR / "alt.csv"

    # Pre-downloaded files take precedence — supports environments where Python's
    # TLS is intercepted (corporate proxy/AV) but curl/browser downloads work.
    if local_sdn.exists() and local_alt.exists():
        print(f"Using pre-downloaded {local_sdn.name} and {local_alt.name} from {DATA_DIR}")
        sdn_raw = local_sdn.read_text(encoding="latin-1")
        alt_raw = local_alt.read_text(encoding="latin-1")
    else:
        try:
            sdn_raw = _fetch(SDN_URL)
            alt_raw = _fetch(ALT_URL)
        except Exception as e:
            print(f"[ERROR] Could not download the OFAC list: {e}")
            print("Manual option: download sdn.csv and alt.csv from")
            print(f"  {SDN_URL}\n  {ALT_URL}")
            print(f"and place them in {DATA_DIR}, then re-run.")
            return 1

    entries = _parse_pair(sdn_raw, alt_raw, "OFAC SDN")
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Wrote {len(entries)} SDN entries to {OUT}")

    # Consolidated non-SDN lists (e.g. Sectoral Sanctions) — best-effort: SDN
    # screening must never depend on this succeeding.
    local_cons = DATA_DIR / "cons_prim.csv"
    local_cons_alt = DATA_DIR / "cons_alt.csv"
    try:
        if local_cons.exists() and local_cons_alt.exists():
            print(f"Using pre-downloaded {local_cons.name} and {local_cons_alt.name} from {DATA_DIR}")
            cons_raw = local_cons.read_text(encoding="latin-1")
            cons_alt_raw = local_cons_alt.read_text(encoding="latin-1")
        else:
            cons_raw = _fetch(CONS_URL)
            cons_alt_raw = _fetch(CONS_ALT_URL)
        cons_entries = _parse_pair(cons_raw, cons_alt_raw, "OFAC Consolidated (non-SDN)")
        OUT_CONS.write_text(json.dumps(cons_entries, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"Wrote {len(cons_entries)} Consolidated (non-SDN) entries to {OUT_CONS}")
    except Exception as e:
        print(f"[WARN] Consolidated (non-SDN) list unavailable ({e}) — SDN screening unaffected.")

    print("Restart the backend (or call sanctions.reload()) to pick up the new lists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
