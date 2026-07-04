"""Download the live OFAC SDN list and write data/ofac_sdn.json for screening.

Run periodically (OFAC updates the list frequently — production programs refresh
at least daily):

    python scripts/update_ofac.py

Pulls the primary SDN names (sdn.csv) and alternate names / aliases (alt.csv)
from the US Treasury OFAC download endpoint and normalizes them into the JSON
shape backend/services/sanctions.py expects. If the download fails (e.g. no
network), it prints manual-download instructions and leaves any existing
data/ofac_sdn.json untouched.
"""
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OUT = DATA_DIR / "ofac_sdn.json"

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"

# sdn.csv columns (no header): ent_num, name, sdn_type, program, title, ...
# alt.csv columns (no header): ent_num, alt_num, alt_type, alt_name, alt_remarks
_EMPTY = {"-0-", ""}


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "FMS-OFAC-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("latin-1")


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        sdn_raw = _fetch(SDN_URL)
        alt_raw = _fetch(ALT_URL)
    except Exception as e:
        print(f"[ERROR] Could not download the OFAC list: {e}")
        print("Manual option: download sdn.csv and alt.csv from")
        print(f"  {SDN_URL}\n  {ALT_URL}")
        print(f"then re-run, or hand-build {OUT} as a JSON list of "
              '{"name","type","program","source"} objects.')
        return 1

    entries: list[dict] = []

    # Primary names, plus a program lookup keyed by entity number for aliases.
    program_by_ent: dict[str, str] = {}
    for row in csv.reader(io.StringIO(sdn_raw)):
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
            "source": "OFAC SDN",
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
            "source": "OFAC SDN (alias)",
        })

    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Wrote {len(entries)} sanctions entries to {OUT}")
    print("Restart the backend (or call sanctions.reload()) to pick up the new list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
