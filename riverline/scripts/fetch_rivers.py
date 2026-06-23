"""
Fetch NHD perennial stream lines for Montana from the USGS ArcGIS REST API.

Filters for fcode=46003 (Perennial StreamRiver) with a GNIS name.
Paginates automatically until all features are retrieved.

Usage:
  /Users/ianvandusen/anaconda3/envs/geodata/bin/python \
      /Users/ianvandusen/Desktop/Ito/itogeo/repos/line/riverline/scripts/fetch_rivers.py

Output:
  riverline/site/data/mt_rivers.geojson
"""
import json
import time
from pathlib import Path

import requests

HEADERS = {"User-Agent": "RiverLine/1.0 (Ito Geospatial)", "Accept": "application/json"}
BASE_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"
# Montana bounding box in WGS84
MT_BBOX = "-116.5,44.0,-103.5,49.2"
OUT = Path(__file__).resolve().parents[2] / "riverline" / "site" / "data" / "mt_rivers.geojson"
PAGE_SIZE = 2000


def fetch_page(offset: int) -> dict:
    params = {
        "where": "fcode=46003 AND gnis_name IS NOT NULL AND gnis_name <> ''",
        "geometry": MT_BBOX,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "gnis_name,fcode,reachcode,visibilityfilter",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    print("Fetching NHD perennial stream lines for MT …")
    all_features = []
    offset = 0

    while True:
        print(f"  Page at offset {offset} …", end=" ", flush=True)
        data = fetch_page(offset)
        features = data.get("features", [])
        print(f"{len(features)} features")
        if not features:
            break
        all_features.extend(features)
        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.5)

    print(f"\nTotal features: {len(all_features)}")

    geojson = {
        "type": "FeatureCollection",
        "features": all_features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(geojson, separators=(",", ":")))
    size_mb = OUT.stat().st_size / 1_048_576
    print(f"Wrote {len(all_features)} features → {OUT}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
