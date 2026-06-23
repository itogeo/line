"""
Fetch all active DNRC StAGE hydrology stations from Layer 0 (locations_spatial).

Returns 316 active stations with LocationID, name, basin, county, coordinates.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/fetch_dnrc_stage_gages.py

Output:
  riverline/site/data/dnrc_gauges.json   (GeoJSON FeatureCollection, ~316 features)
"""
import json
import time
from pathlib import Path

import requests

HEADERS = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
BASE_URL = "https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WMB_StAGE/MapServer/0/query"
OUT = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "dnrc_gauges.json"
PAGE_SIZE = 500


def fetch_page(offset: int) -> list[dict]:
    params = {
        "where": "ActiveFlag=1",
        "outFields": "LocationID,LocationName,Latitude,Longitude,BasinName,CountyName",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("features", [])


def main():
    print("Fetching DNRC StAGE active locations …")
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

    print(f"\nTotal active locations: {len(all_features)}")

    # Normalize properties for map use
    clean_features = []
    for f in all_features:
        props = f.get("properties") or f.get("attributes") or {}
        lid = props.get("LocationID") or ""
        name = props.get("LocationName") or ""
        basin = props.get("BasinName") or ""
        county = props.get("CountyName") or ""
        geom = f.get("geometry")
        if not lid or not geom:
            continue
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        clean_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(coords[0], 5), round(coords[1], 5)]},
            "properties": {
                "id": lid,
                "name": name,
                "basin": basin,
                "county": county,
                "source": "dnrc",
            },
        })

    geojson = {"type": "FeatureCollection", "features": clean_features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {len(clean_features)} features → {OUT}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
