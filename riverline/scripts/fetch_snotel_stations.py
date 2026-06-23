"""Fetch all active MT SNOTEL stations from AWDB REST API and write snotel_stations.json.

Run once to pre-bake the station list; re-run when new stations are added.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python riverline/scripts/fetch_snotel_stations.py
"""
import json
from pathlib import Path

import requests

AWDB_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
HEADERS = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
OUT = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "snotel_stations.json"


def main():
    print("Fetching all SNOTEL stations from AWDB...")
    r = requests.get(
        f"{AWDB_BASE}/stations",
        params={"stateCds": "MT", "networkCds": "SNTL", "activeOnly": "true"},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    all_stations = r.json()

    # The API doesn't filter well — filter client-side to MT SNTL only
    mt = [
        s for s in all_stations
        if ":MT:SNTL" in s.get("stationTriplet", "")
        and s.get("latitude") is not None
        and s.get("longitude") is not None
    ]
    print(f"  MT SNOTEL stations: {len(mt)}")

    features = []
    for s in mt:
        triplet = s["stationTriplet"]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(s["longitude"]), float(s["latitude"])],
            },
            "properties": {
                "triplet": triplet,
                "name": s.get("name", triplet),
                "elevation_ft": int(s["elevation"]) if s.get("elevation") else None,
                "county": s.get("countyName"),
                "huc": s.get("huc"),
                "source": "snotel",
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    print(f"  Wrote {len(features)} stations → {OUT}  ({OUT.stat().st_size:,} bytes)")

    for f in features[:5]:
        p = f["properties"]
        coords = f["geometry"]["coordinates"]
        print(f"  {p['name']:<25} ({p['triplet']})  {p['elevation_ft']}ft  [{coords[1]:.3f},{coords[0]:.3f}]")


if __name__ == "__main__":
    main()
