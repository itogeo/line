"""
Fetch NOAA NWPS gauge list for MT and build USGS-ID → NOAA LID mapping.

Strategy:
  1. Fetch list endpoint (slow but works at 90s timeout) to get all 277 MT LIDs
  2. Concurrently fetch each individual gauge to get usgsId (fast per call, ~30s total)
  3. Write USGS-ID → LID mapping

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/fetch_noaa_gauges.py

Output:
  riverline/site/data/noaa_gauges.json
  Keys: USGS site ID (zero-padded to 8 digits) → NOAA LID (uppercase)
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HEADERS = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
BASE = "https://api.water.noaa.gov/nwps/v1/gauges"
OUT = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "noaa_gauges.json"

WORKERS = 20


def fetch_mt_lids() -> list[str]:
    """Fetch list endpoint — returns 12k gauges total, filter to MT."""
    print("Fetching NOAA gauge list (MT) — this takes ~60-90 seconds …")
    r = requests.get(BASE, params={"stateCd": "MT"}, headers=HEADERS, timeout=120)
    r.raise_for_status()
    gauges = r.json().get("gauges", [])
    mt = [g["lid"] for g in gauges if g.get("state", {}).get("abbreviation") == "MT" and g.get("lid")]
    print(f"  {len(mt)} MT LIDs found")
    return mt


def fetch_usgs_id(lid: str) -> tuple[str, str] | None:
    """Return (usgsId, lid) or None if no usgsId."""
    try:
        r = requests.get(f"{BASE}/{lid}", headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        usgs_id = r.json().get("usgsId", "").strip()
        if usgs_id:
            return (usgs_id, lid)
    except Exception:
        pass
    return None


def main():
    lids = fetch_mt_lids()

    print(f"Fetching individual gauge details ({len(lids)} LIDs, {WORKERS} workers) …")
    mapping: dict[str, str] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_usgs_id, lid): lid for lid in lids}
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if result:
                usgs_id, lid = result
                key = usgs_id.zfill(8)
                mapping[key] = lid
            if done % 50 == 0 or done == len(lids):
                print(f"  {done}/{len(lids)}  ({len(mapping)} with USGS IDs so far)")

    print(f"\nFinal: {len(mapping)} USGS→NOAA pairs")
    for k, v in sorted(mapping.items())[:10]:
        print(f"  {k} → {v}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(mapping, sort_keys=True, indent=2))
    print(f"\nWrote → {OUT}")


if __name__ == "__main__":
    main()
