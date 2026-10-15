#!/usr/bin/env python3
"""
Pre-compute SNOTEL 20-year median snow depth by day-of-year.
Outputs a small JSON file that the site loads for "% of normal" display.

Usage:
    python snowline/pipeline/build_snotel_normals.py

Output:
    site/data/snotel_normals.json (~50KB)
"""

if __name__ == "__main__":
    # --help before the heavy imports below (and before anything runs).
    import argparse
    # parse_known_args: --help exits here; options like --out-dir are read in main().
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_known_args()

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import requests
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))  # repo root, for `lib`
from lib.aoi import SNOWLINE, pad_bbox  # noqa: E402

SNOTEL_BBOX = pad_bbox(SNOWLINE.bbox, 0.15)   # AOI + 0.15 deg so edge stations count
YEARS = list(range(2005, 2026))  # 20 years
OUTPUT = Path(__file__).parent.parent / "site" / "data" / "snotel_normals.json"


def log(msg):
    print(f"[normals] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUTPUT, help="Output JSON (default site/data/snotel_normals.json)")
    out = ap.parse_args().out
    base = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"

    # Get SNOTEL stations in bbox
    log("Fetching station list...")
    resp = requests.get(f"{base}/stations", params={
        "networkCodes": "SNTL",
        "returnFields": "stationTriplet,name,elevation,latitude,longitude",
    }, timeout=30)
    all_stations = resp.json()

    local = [s for s in all_stations
             if s.get('latitude') and s.get('longitude')
             and SNOTEL_BBOX[0] <= s['longitude'] <= SNOTEL_BBOX[2]
             and SNOTEL_BBOX[1] <= s['latitude'] <= SNOTEL_BBOX[3]]

    # Filter to only SNTL network (not USGS, COOP, etc)
    sntl = [s for s in local if s['stationTriplet'].endswith(':SNTL')]
    log(f"{len(sntl)} SNTL stations in bbox")

    # For each station, fetch 20 years of Oct-Mar data and compute median by DOY
    results = {}
    batch_size = 10

    for i in range(0, len(sntl), batch_size):
        batch = sntl[i:i + batch_size]
        triplets = ','.join(s['stationTriplet'] for s in batch)
        log(f"Fetching batch {i // batch_size + 1} ({len(batch)} stations)...")

        # Fetch all years in one big call per batch
        for year in YEARS:
            begin = f"{year}-10-01"
            end = f"{year + 1}-05-31"

            try:
                resp = requests.get(f"{base}/data", params={
                    "stationTriplets": triplets,
                    "elements": "SNWD",
                    "duration": "DAILY",
                    "beginDate": begin,
                    "endDate": end,
                }, timeout=60)

                if resp.status_code != 200:
                    continue

                for rec in resp.json():
                    triplet = rec.get('stationTriplet', '')
                    if triplet not in results:
                        results[triplet] = defaultdict(list)

                    for elem in rec.get('data', []):
                        for v in elem.get('values', []):
                            if v.get('value') is not None:
                                # Convert date to month-day key
                                md = v['date'][5:]  # "MM-DD"
                                results[triplet][md].append(v['value'])

            except Exception as e:
                log(f"  Error year {year}: {e}")
                continue

    # Compute medians
    log("Computing medians...")
    normals = {}
    for triplet, by_day in results.items():
        station_normals = {}
        for md, values in sorted(by_day.items()):
            if len(values) >= 5:  # Need at least 5 years of data
                station_normals[md] = {
                    'median': round(float(np.median(values)), 1),
                    'p25': round(float(np.percentile(values, 25)), 1),
                    'p75': round(float(np.percentile(values, 75)), 1),
                    'n': len(values),
                }
        if station_normals:
            normals[triplet] = station_normals

    log(f"{len(normals)} stations with normals computed")

    # Build output
    # Include station metadata for the site to use
    station_meta = {}
    for s in sntl:
        t = s['stationTriplet']
        if t in normals:
            station_meta[t] = {
                'name': s['name'],
                'elevation_ft': s.get('elevation'),
                'lat': s['latitude'],
                'lon': s['longitude'],
            }

    output = {
        'years': [YEARS[0], YEARS[-1]],
        'stations': station_meta,
        'normals': normals,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        json.dump(output, f)

    size_kb = out.stat().st_size // 1024
    log(f"Done. {out} ({size_kb}KB)")


if __name__ == "__main__":
    main()
