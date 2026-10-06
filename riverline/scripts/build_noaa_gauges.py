"""
Build noaa_gauges.json — maps USGS 8-digit site IDs to NOAA NWPS LIDs for Montana.

NOAA NWPS v1 API: each gauge response includes a `usgsId` field.
The list endpoint (?limit=N) has been unstable; this script uses a two-phase approach:
  Phase 1: Query individual NOAA gauges by known MT WFO station lists (AHPS RSS)
  Phase 2: Fall back to querying NOAA API list with small pages + retries

Usage:
  python riverline/scripts/build_noaa_gauges.py

Output:
  riverline/site/data/noaa_gauges.json
  Format: {"USGS_ID_8digit": "NOAA_LID", ...}
"""

import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "riverline" / "site" / "data"

NOAA_BASE = "https://api.water.noaa.gov/nwps/v1/gauges"
HEADERS = {"User-Agent": "RiverLine/1.0 (Ito Geospatial; itogeospatial@gmail.com)"}


def curl_json(url, timeout=20):
    """Fetch JSON via curl (more reliable than urllib for NOAA APIs)."""
    result = subprocess.run(
        ["curl", "-s", "--max-time", str(timeout), "-A", HEADERS["User-Agent"], url],
        capture_output=True, text=True
    )
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def fetch_noaa_gauge(lid):
    """Look up a single NOAA gauge by LID, return (usgsId, name) or None."""
    data = curl_json(f"{NOAA_BASE}/{lid}", timeout=10)
    if not data or "lid" not in data:
        return None
    return data.get("usgsId", "").strip(), data.get("name", "")


def fetch_noaa_page(offset=0, limit=50, retries=3):
    """Fetch one page of NOAA gauges. Returns list or None."""
    url = f"{NOAA_BASE}?limit={limit}&offset={offset}"
    for attempt in range(retries):
        data = curl_json(url, timeout=30)
        if data is not None:
            return data.get("gauges", [])
        print(f"  Attempt {attempt+1}/{retries} failed for offset={offset}")
        time.sleep(2 ** attempt)
    return None


def main():
    # Load our USGS gauge IDs to check for matches
    with open(DATA / "usgs_gauges.json") as f:
        usgs_fc = json.load(f)
    our_ids = {feat["properties"]["id"].zfill(8) for feat in usgs_fc["features"]}
    print(f"Loaded {len(our_ids)} USGS gauge IDs")

    # Start with confirmed mapping
    mapping = {"06043500": "GLGM8"}
    print(f"Starting with {len(mapping)} confirmed mappings")

    # Phase 1: Try paginating NOAA API with small pages
    print("\nPhase 1: Paginating NOAA API (limit=50, retrying on failure)...")
    offset = 0
    limit = 50
    max_offset = 5000
    empty_runs = 0

    while offset < max_offset:
        gauges = fetch_noaa_page(offset, limit)
        if gauges is None:
            print(f"  offset={offset}: failed after retries, stopping")
            break
        mt = [g for g in gauges if g.get("state", {}).get("abbreviation") == "MT"]
        added = 0
        for g in mt:
            usgs = g.get("usgsId", "").strip().zfill(8)
            lid = g.get("lid", "").strip()
            if usgs and lid and usgs in our_ids and usgs not in mapping:
                mapping[usgs] = lid
                added += 1
        if mt:
            print(f"  offset={offset}: {len(gauges)} gauges, {len(mt)} MT, +{added} new")
        if len(gauges) < limit:
            print(f"  Reached end at offset={offset}")
            break
        offset += limit
        if len(gauges) == 0:
            empty_runs += 1
            if empty_runs >= 3:
                break
        else:
            empty_runs = 0

    # Write output
    out = DATA / "noaa_gauges.json"
    with open(out, "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"\nWrote {len(mapping)} mappings → {out}")
    for usgs, lid in sorted(mapping.items()):
        print(f"  {usgs} → {lid}")


if __name__ == "__main__":
    main()
