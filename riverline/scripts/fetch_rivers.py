"""
Fetch named rivers for Montana from OpenStreetMap via Overpass API.
Adds a discharge-proxy `tier` (1–5) based on segment count per river name.

Tier thresholds (segment count = proxy for river size / drainage area):
  5 = 200+  (Missouri, Yellowstone — truly major)
  4 = 70–199  (Milk, Clark Fork, Flathead, Two Medicine, etc.)
  3 = 25–69  (Gallatin, Madison, Sun, Marias, etc.)
  2 = 8–24   (named mid-size rivers)
  1 = 1–7    (small named rivers)

Usage:
  python riverline/scripts/fetch_rivers.py

Output:
  riverline/site/data/mt_rivers.geojson
"""
import json
import time
from collections import Counter
from pathlib import Path

import requests

HEADERS  = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
OVERPASS = "https://overpass-api.de/api/interpreter"
MT_BBOX  = "44.0,-116.5,49.2,-103.5"
OUT      = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "mt_rivers.geojson"
MAX_RETRIES = 3

QUERY = f"""
[out:json][timeout:180][bbox:{MT_BBOX}];
(
  way["waterway"="river"]["name"];
);
out geom;
"""


def tier_from_count(count: int) -> int:
    if count >= 200: return 5
    if count >= 70:  return 4
    if count >= 25:  return 3
    if count >= 8:   return 2
    return 1


def fetch_with_retry() -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            print(f"  Querying Overpass (attempt {attempt + 1}) …", flush=True)
            r = requests.post(OVERPASS, data={"data": QUERY}, headers=HEADERS, timeout=200)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            wait = 15 * (2 ** attempt)
            print(f"  Timeout — waiting {wait}s …"); time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = 10 * (2 ** attempt)
            print(f"  Error: {e} — waiting {wait}s …"); time.sleep(wait)
    raise RuntimeError(f"Overpass failed after {MAX_RETRIES} retries")


def main():
    print("Fetching MT rivers from OpenStreetMap (Overpass API) …")
    data = fetch_with_retry()
    elements = data.get("elements", [])
    print(f"  Received {len(elements)} way elements")

    # First pass — collect all features and count segments per river name
    raw = []
    for el in elements:
        if el.get("type") != "way": continue
        geom = el.get("geometry", [])
        if len(geom) < 2: continue
        name = el.get("tags", {}).get("name", "").strip()
        if not name: continue
        coords = [[round(pt["lon"], 6), round(pt["lat"], 6)] for pt in geom]
        raw.append({"name": name, "coords": coords})

    segment_counts = Counter(r["name"] for r in raw)

    # Print top rivers for verification
    print("\nTop 10 rivers by segment count (discharge proxy):")
    for name, ct in segment_counts.most_common(10):
        print(f"  Tier {tier_from_count(ct)}  {ct:4d} segs  {name}")

    # Second pass — build GeoJSON with tier
    features = []
    for r in raw:
        ct   = segment_counts[r["name"]]
        tier = tier_from_count(ct)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": r["coords"]},
            "properties": {"name": r["name"], "waterway": "river", "tier": tier},
        })

    tier_dist = Counter(f["properties"]["tier"] for f in features)
    print("\nFeatures by tier:")
    for t in sorted(tier_dist, reverse=True):
        print(f"  Tier {t}: {tier_dist[t]} segments")
    print(f"  Total: {len(features)} segments")

    geojson = {"type": "FeatureCollection", "features": features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"\nWrote {len(features)} features → {OUT}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
