"""
Build nrcs_forecast_points.json — NRCS seasonal runoff forecast stations in Montana.

NRCS publishes monthly Water Supply Forecasts (April–July runoff volume, element SRVO)
for specific basin outlet points.  This script fetches the station list, then maps each
forecast point to the nearest USGS gauge in usgs_gauges.json so the frontend can link
SRVO forecasts to gauges the user clicks on.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/build_nrcs_forecast_points.py

Output:
  riverline/site/data/nrcs_forecast_points.json
  Format: list of {triplet, name, lat, lon, usgs_id, usgs_name, dist_km}
  usgs_id is null if no USGS gauge within MAX_DIST_KM
"""

import json
import math
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "riverline" / "site" / "data"

AWDB_STATIONS = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations"
MAX_DIST_KM = 30.0


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    # AWDB allows filtering by element — try direct filter first
    params = urllib.parse.urlencode({
        "stateCode": "MT",
        "elements": "SRVO",
        "activeOnly": "false",
    })
    url = f"{AWDB_STATIONS}?{params}"
    print(f"Fetching NRCS SRVO stations in Montana …\n  GET {url}")
    stations = fetch_json(url)
    print(f"  Got {len(stations)} stations with SRVO element")

    if not stations:
        print("\nNo stations returned — AWDB may not support element filter on this endpoint.")
        print("Try: curl '" + url + "' | python3 -m json.tool | head -40")
        return

    # Load USGS gauges for proximity matching
    with open(DATA / "usgs_gauges.json") as f:
        usgs_fc = json.load(f)
    usgs_gauges = [
        {
            "id": feat["properties"]["id"],
            "name": feat["properties"]["name"],
            "lat": feat["geometry"]["coordinates"][1],
            "lon": feat["geometry"]["coordinates"][0],
        }
        for feat in usgs_fc["features"]
    ]
    print(f"Loaded {len(usgs_gauges)} USGS gauges for proximity matching")

    results = []
    for s in stations:
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is None or lon is None:
            continue
        nearest_id, nearest_name, nearest_dist = None, None, float("inf")
        for g in usgs_gauges:
            d = haversine_km(lon, lat, g["lon"], g["lat"])
            if d < nearest_dist:
                nearest_dist = d
                nearest_id = g["id"]
                nearest_name = g["name"]
        if nearest_dist > MAX_DIST_KM:
            nearest_id = None
            nearest_name = None
            nearest_dist = None
        results.append({
            "triplet":   s.get("stationTriplet", ""),
            "name":      s.get("name", ""),
            "lat":       lat,
            "lon":       lon,
            "usgs_id":   nearest_id,
            "usgs_name": nearest_name,
            "dist_km":   round(nearest_dist, 1) if nearest_dist is not None else None,
        })

    out = DATA / "nrcs_forecast_points.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {len(results)} forecast points → {out}")

    linked = sum(1 for r in results if r["usgs_id"])
    print(f"  {linked}/{len(results)} matched to USGS gauge within {MAX_DIST_KM} km")
    for r in results:
        status = f"→ {r['usgs_id']} ({r['dist_km']} km)" if r["usgs_id"] else "→ no nearby USGS"
        print(f"  {r['triplet']}: {r['name']} {status}")


if __name__ == "__main__":
    main()
