"""
Fetch named lakes and reservoirs in Montana from OpenStreetMap via Overpass API.

Filters to named water bodies that are large enough to be visible at state level.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/fetch_lakes.py

Output:
  riverline/site/data/mt_lakes.geojson
"""
import json
import time
from pathlib import Path

import requests

HEADERS  = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
OVERPASS = "https://overpass-api.de/api/interpreter"
MT_BBOX  = "44.0,-116.5,49.2,-103.5"
OUT      = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "mt_lakes.geojson"
MAX_RETRIES = 3

# Get named water bodies (lakes, reservoirs, ponds) as closed ways and relations.
# The `out geom;` on relations expands member geometry inline.
QUERY = f"""
[out:json][timeout:120][bbox:{MT_BBOX}];
(
  way["natural"="water"]["name"];
  way["water"~"lake|reservoir"]["name"];
  relation["natural"="water"]["name"]["type"="multipolygon"];
  relation["water"~"lake|reservoir"]["name"]["type"="multipolygon"];
);
out body geom;
"""


def fetch_with_retry() -> dict:
    for attempt in range(MAX_RETRIES):
        try:
            print(f"  Querying Overpass (attempt {attempt + 1}) …", flush=True)
            r = requests.post(OVERPASS, data={"data": QUERY}, headers=HEADERS, timeout=150)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            wait = 15 * (2 ** attempt)
            print(f"  Timeout — waiting {wait}s …"); time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = 10 * (2 ** attempt)
            print(f"  Error: {e} — waiting {wait}s …"); time.sleep(wait)
    raise RuntimeError(f"Overpass failed after {MAX_RETRIES} retries")


def way_to_polygon(geom_nodes: list) -> list | None:
    """Convert Overpass way geometry nodes to a coordinate ring."""
    if len(geom_nodes) < 4:
        return None
    coords = [[round(pt["lon"], 6), round(pt["lat"], 6)] for pt in geom_nodes]
    # Ensure ring is closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def main():
    print("Fetching MT lakes from OpenStreetMap (Overpass API) …")
    data = fetch_with_retry()
    elements = data.get("elements", [])
    print(f"  Received {len(elements)} elements")

    features = []
    skipped = 0

    for el in elements:
        el_type = el.get("type")
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            continue
        water_type = tags.get("water", tags.get("natural", "water"))

        if el_type == "way":
            geom = el.get("geometry", [])
            ring = way_to_polygon(geom)
            if not ring:
                skipped += 1
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {"name": name, "water": water_type},
            })

        elif el_type == "relation":
            # Build outer ring from members with role="outer"
            members = el.get("members", [])
            outer_rings = []
            for member in members:
                if member.get("role") != "outer":
                    continue
                geom = member.get("geometry", [])
                ring = way_to_polygon(geom)
                if ring:
                    outer_rings.append(ring)
            if not outer_rings:
                skipped += 1
                continue
            # Use largest outer ring as the main polygon shell
            largest = max(outer_rings, key=len)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [largest]},
                "properties": {"name": name, "water": water_type},
            })

    print(f"  Built {len(features)} lake features ({skipped} skipped — too small or no geometry)")

    # Print top lakes by name for a sanity check
    print("\nSample lake names:")
    for f in features[:15]:
        print(f"  {f['properties']['name']}")

    geojson = {"type": "FeatureCollection", "features": features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"\nWrote {len(features)} features → {OUT}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
