#!/usr/bin/env python3
"""
Pre-compute SNOTEL current-season time series for every station in the AOI.

Replaces the old per-date SNOTEL embedding pattern. Instead of fetching
station readings for every satellite pass date and embedding them in each
snowline.json, we fetch the WHOLE current season (Oct 1 → today) once per
day and the frontend looks up the right reading for whichever timeline
date the user clicks.

Usage:
    python snowline/pipeline/build_snotel_season.py               # current season
    python snowline/pipeline/build_snotel_season.py --season 2025 # Oct 2025 - Jun 2026

Output:
    site/data/snotel_season_{YEAR}.json for the season that starts in Oct YEAR
    (the map loads the file for whichever season is on screen), and for the
    current season also site/data/snotel_season.json.
"""

if __name__ == "__main__":
    # --help before the heavy imports below (and before anything runs).
    import argparse
    _ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ap.add_argument("--season", type=int, help="season start year (default: the current season)")
    ARGS = _ap.parse_args()

import json
import time
from datetime import datetime
from pathlib import Path
import requests

SNOTEL_BBOX = [-112.5, 44.4, -108.5, 46.6]
DATA_DIR = Path(__file__).parent.parent / "site" / "data"
OUTPUT = DATA_DIR / "snotel_season.json"

BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"


def log(msg):
    print(f"[snotel-season] {msg}", flush=True)


def fetch_json(url, params, attempts=3):
    """Retry wrapper — NRCS API is flaky and returns 500s/empty bodies."""
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 200 and r.text.strip():
                return r.json()
            log(f"  attempt {i+1}: status={r.status_code} body_len={len(r.text)}")
        except Exception as e:
            log(f"  attempt {i+1}: {type(e).__name__}: {e}")
        if i < attempts - 1:
            time.sleep(2 ** i)
    return None


def main(season=None):
    # Snowline season runs Oct 1 → May 31; SNOTEL is kept to June 30 so the
    # melt-out is in the chart. In Oct-Dec we're in the new season; otherwise
    # it's the season that started last October.
    today = datetime.utcnow()
    current = today.year if today.month >= 10 else today.year - 1
    season = current if season is None else season
    if season > current:
        log(f"FATAL: season {season} hasn't started")
        return 1
    season_start = f"{season}-10-01"
    season_end = min(today.strftime("%Y-%m-%d"), f"{season + 1}-06-30")
    log(f"Season window: {season_start} → {season_end}")

    log("Fetching station list...")
    all_stations = fetch_json(f"{BASE}/stations", {
        "networkCodes": "SNTL",
        "returnFields": "stationTriplet,name,elevation,latitude,longitude,stateCode",
    })
    if all_stations is None:
        log("FATAL: station list fetch failed after retries.")
        return 1

    local = [s for s in all_stations
             if s.get("latitude") and s.get("longitude")
             and SNOTEL_BBOX[0] <= s["longitude"] <= SNOTEL_BBOX[2]
             and SNOTEL_BBOX[1] <= s["latitude"] <= SNOTEL_BBOX[3]]
    log(f"  {len(local)} SNOTEL stations in bbox")

    triplets = [s["stationTriplet"] for s in local]

    # Fetch the season's daily SWE + snow depth in batches.
    # Each batch returns one record per (station, element) with a `values`
    # array of {date, value}.
    history_by_station = {}  # triplet -> {date: {"swe": x, "depth": y}}

    for i in range(0, len(triplets), 50):
        batch = triplets[i:i+50]
        log(f"  batch {i//50 + 1}: {len(batch)} stations")
        batch_json = fetch_json(f"{BASE}/data", {
            "stationTriplets": ",".join(batch),
            "elements": "WTEQ,SNWD",
            "duration": "DAILY",
            "beginDate": season_start,
            "endDate": season_end,
        })
        if batch_json is None:
            log(f"  batch {i//50 + 1}: failed, continuing")
            continue
        for rec in batch_json:
            triplet = rec.get("stationTriplet", "")
            if triplet not in history_by_station:
                history_by_station[triplet] = {}
            for elem in rec.get("data", []):
                code = elem.get("stationElement", {}).get("elementCode", "")
                key = "swe_in" if code == "WTEQ" else ("depth_in" if code == "SNWD" else None)
                if key is None:
                    continue
                for v in elem.get("values", []):
                    date = v.get("date", "")[:10]
                    val = v.get("value")
                    if not date or val is None:
                        continue
                    if date not in history_by_station[triplet]:
                        history_by_station[triplet][date] = {}
                    history_by_station[triplet][date][key] = val

    # Build the output. Stations get metadata + a sorted history array.
    stations_out = []
    for s in local:
        triplet = s["stationTriplet"]
        history_dict = history_by_station.get(triplet, {})
        history = [
            {
                "date": date,
                "swe_in": readings.get("swe_in"),
                "depth_in": readings.get("depth_in"),
            }
            for date, readings in sorted(history_dict.items())
        ]
        stations_out.append({
            "id": triplet,
            "name": s["name"],
            "elevation_ft": s.get("elevation"),
            "lat": s["latitude"],
            "lon": s["longitude"],
            "history": history,
        })

    output = {
        "season": season,
        "season_start": season_start,
        "season_end": season_end,
        "generated_at": today.isoformat() + "Z",
        "stations": stations_out,
    }

    total_readings = sum(len(s["history"]) for s in stations_out)
    if total_readings == 0:
        log("FATAL: no readings came back; keeping the old files.")
        return 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [DATA_DIR / f"snotel_season_{season}.json"]
    if season == current:
        outputs.append(OUTPUT)
    for out in outputs:
        with open(out, "w") as f:
            json.dump(output, f)
        log(f"Wrote {out.name}")
    size_kb = outputs[0].stat().st_size // 1024
    log(f"Done. {len(stations_out)} stations, {total_readings} readings, {size_kb}KB")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(ARGS.season))
