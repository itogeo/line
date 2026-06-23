"""
Fetch named rivers for Montana from OpenStreetMap via Overpass API.

Queries waterway=river with a name tag — this is already pre-classified as
major rivers only (Missouri, Yellowstone, Gallatin, etc.). Streams and
smaller waterways stay on the raster mt-streams tile layer.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/fetch_rivers.py

Output:
  riverline/site/data/mt_rivers.geojson   (~500 KB, ~1000-2000 features)
"""
import json
import time
from pathlib import Path

import requests

HEADERS = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
OVERPASS = "https://overpass-api.de/api/interpreter"
# south, west, north, east — Overpass bbox order
MT_BBOX = "44.0,-116.5,49.2,-103.5"
OUT = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "mt_rivers.geojson"
MAX_RETRIES = 3

QUERY = f"""
[out:json][timeout:180][bbox:{MT_BBOX}];
(
  way["waterway"="river"]["name"];
);
out geom;
"""


def fetch_with_retry() -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            print(f"  Querying Overpass (attempt {attempt + 1}) …", flush=True)
            r = requests.post(OVERPASS, data={"data": QUERY}, headers=HEADERS, timeout=200)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            wait = 15 * (2 ** attempt)
            print(f"  Timeout — waiting {wait}s before retry …")
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = 10 * (2 ** attempt)
            print(f"  Error: {e} — waiting {wait}s before retry …")
            time.sleep(wait)
    raise RuntimeError(f"Overpass query failed after {MAX_RETRIES} retries")


def main():
    print("Fetching MT rivers from OpenStreetMap (Overpass API) …")
    data = fetch_with_retry()

    elements = data.get("elements", [])
    print(f"  Received {len(elements)} way elements")

    features = []
    skipped = 0
    for el in elements:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry", [])
        if len(geom) < 2:
            skipped += 1
            continue
        coords = [[round(pt["lon"], 6), round(pt["lat"], 6)] for pt in geom]
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            skipped += 1
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "name": name,
                "waterway": tags.get("waterway", "river"),
            },
        })

    print(f"  {len(features)} named river segments ({skipped} skipped — no name or geometry)")

    geojson = {"type": "FeatureCollection", "features": features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {len(features)} features → {OUT}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
