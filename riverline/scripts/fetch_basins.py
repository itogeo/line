"""
Fetch HUC8 watershed boundaries for Montana from USGS WBD MapServer.

No large downloads — queries the USGS REST API directly and paginates.
Returns ~60 HUC8 polygons covering Montana and its immediate neighbors.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/fetch_basins.py

Output:
  riverline/site/data/mt_basins.geojson
"""
import json
import time
from pathlib import Path

import requests

HEADERS   = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
# USGS WBD MapServer — layer 4 = HUC8
BASE_URL  = "https://hydrowfs.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4/query"
OUT       = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "mt_basins.geojson"
PAGE_SIZE = 100
MT_BBOX   = "-116.5,44.0,-103.5,49.2"   # xmin,ymin,xmax,ymax


def fetch_page(offset: int) -> list:
    params = {
        "where": "states LIKE '%MT%'",
        "geometry": MT_BBOX,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "huc8,name,states,areasqkm",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("features", [])


def simplify_coords(ring: list, precision: int = 4) -> list:
    return [[round(pt[0], precision), round(pt[1], precision)] for pt in ring]


def main():
    print("Fetching HUC8 basins from USGS WBD …")
    all_features = []
    offset = 0

    while True:
        print(f"  Page at offset {offset} …", end=" ", flush=True)
        features = fetch_page(offset)
        print(f"{len(features)} features")
        if not features:
            break
        all_features.extend(features)
        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.3)

    print(f"\nTotal HUC8 basins: {len(all_features)}")

    # Normalize and round coordinates to reduce file size
    clean = []
    for f in all_features:
        props = f.get("properties") or {}
        geom  = f.get("geometry") or {}
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if not coords:
            continue

        if gtype == "Polygon":
            new_coords = [simplify_coords(ring) for ring in coords]
        elif gtype == "MultiPolygon":
            new_coords = [[simplify_coords(ring) for ring in poly] for poly in coords]
        else:
            continue

        clean.append({
            "type": "Feature",
            "geometry": {"type": gtype, "coordinates": new_coords},
            "properties": {
                "huc8":     props.get("huc8", ""),
                "name":     props.get("name", ""),
                "areasqkm": props.get("areasqkm", 0),
            },
        })

    print("\nSample basins:")
    for f in clean[:8]:
        p = f["properties"]
        print(f"  {p['huc8']}  {p['name']}  ({p['areasqkm']:.0f} km²)")

    geojson = {"type": "FeatureCollection", "features": clean}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"\nWrote {len(clean)} features → {OUT}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
