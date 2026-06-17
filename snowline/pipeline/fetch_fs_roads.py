#!/usr/bin/env python3
"""
One-shot fetch of US Forest Service roads inside the snowline AOI,
combining geometry + maintenance level + seasonal use restrictions.

Pulls from TWO USDA Forest Service Enterprise Data Warehouse endpoints
and merges them by road ID:

  1. EDW_RoadBasic_01/MapServer/0 — road geometry + OPER_MAINT_LEVEL
     (the maintenance grade: 1=closed → 5=high standard paved)
  2. EDW_MVUM_01/MapServer/1 — Motor Vehicle Use Map. Has detailed
     PASSENGERVEHICLE_DATESOPEN / HIGHCLEARANCEVEHICLE_DATESOPEN fields
     showing real season-of-use restrictions like 05/15-09/30
     (mid-May to end of September) for high-elevation campground roads.

Why merge: the MVUM layer's geometry is sometimes coarser, but the
seasonal fields are the only place this data lives. The basic Roads
layer has cleaner geometry and the maintenance level. Merging gives
us the best of both.

Saves to site/data/fs_roads.geojson as a static asset the frontend
loads as a Mapbox layer. Run this once (or once a year — these change
slowly). No automation needed.

Usage:
    python pipeline/fetch_fs_roads.py
"""

import json
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).parent.parent
OUTPUT = REPO_ROOT / "site" / "data" / "fs_roads.geojson"
BBOX = [-112.2, 44.9, -109.0, 46.5]

ROADS_ENDPOINT = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RoadBasic_01/MapServer/0/query"
MVUM_ENDPOINT = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_MVUM_01/MapServer/1/query"


def log(msg):
    print(f"[fs-roads] {msg}", flush=True)


def fetch_geojson(endpoint, out_fields, label):
    """Generic helper to query an ArcGIS REST endpoint and return GeoJSON."""
    params = {
        "where": "1=1",
        "geometry": ",".join(str(c) for c in BBOX),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "true",
        "geometryPrecision": "5",
        "f": "geojson",
    }
    log(f"Querying {label}...")
    r = requests.get(endpoint, params=params, timeout=180)
    r.raise_for_status()
    data = r.json()
    n = len(data.get("features", []))
    log(f"  {n} features")
    return data


def normalize_dates(s):
    """Convert MM/DD-MM/DD to a friendlier 'May 15 - Sep 30' style.
    Returns None if the input is empty / null / year-round (01/01-12/31).
    Year-round means 'no real seasonal restriction' so we drop it."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if s == "01/01-12/31":
        return None  # not a real restriction
    return s


def main():
    # Phase 1: road geometry + maintenance level
    roads = fetch_geojson(
        ROADS_ENDPOINT,
        out_fields="NAME,ID,OPER_MAINT_LEVEL,SURFACE_TYPE,JURISDICTION",
        label="EDW_RoadBasic (geometry + maintenance level)",
    )
    if not roads.get("features"):
        log("WARNING: 0 road features returned from RoadBasic. Endpoint may be down.")
        return 1

    # Phase 2: MVUM with season fields. We only need the properties — the
    # geometry comes from the basic roads layer. returnGeometry=false would
    # be cleaner but the geojson format requires it, so we just discard.
    mvum = fetch_geojson(
        MVUM_ENDPOINT,
        out_fields=(
            "ID,NAME,SEASONAL,"
            "PASSENGERVEHICLE_DATESOPEN,"
            "HIGHCLEARANCEVEHICLE_DATESOPEN,"
            "ATV_DATESOPEN,"
            "MOTORCYCLE_DATESOPEN"
        ),
        label="EDW_MVUM (seasonal use)",
    )

    # Build a lookup of MVUM properties by road ID. Some roads appear
    # multiple times in MVUM (one row per vehicle class category) — we
    # take whichever one has the most informative DATESOPEN field.
    mvum_by_id = {}
    for f in mvum.get("features", []):
        p = f.get("properties", {}) or {}
        rid = p.get("ID")
        if not rid:
            continue
        existing = mvum_by_id.get(rid)
        if not existing or (p.get("PASSENGERVEHICLE_DATESOPEN") and not existing.get("PASSENGERVEHICLE_DATESOPEN")):
            mvum_by_id[rid] = p

    log(f"  unique MVUM road IDs: {len(mvum_by_id)}")

    # Merge: enrich each road geometry feature with its MVUM season fields
    enriched = 0
    seasonal_real = 0
    for feat in roads["features"]:
        p = feat.setdefault("properties", {})
        rid = p.get("ID")
        if not rid:
            continue
        m = mvum_by_id.get(rid)
        if not m:
            continue
        enriched += 1
        # Normalize season strings — drop year-round (01/01-12/31) since
        # those aren't real restrictions, just a "yes this road is managed" flag.
        pv = normalize_dates(m.get("PASSENGERVEHICLE_DATESOPEN"))
        hc = normalize_dates(m.get("HIGHCLEARANCEVEHICLE_DATESOPEN"))
        if pv or hc:
            seasonal_real += 1
        p["passenger_dates"] = pv
        p["high_clearance_dates"] = hc
        # Also expose a single 'season' string for the most-restrictive entry
        # the frontend can use without having to know about the various
        # vehicle class fields.
        p["season"] = pv or hc or None

    log(f"  enriched {enriched}/{len(roads['features'])} roads with MVUM data")
    log(f"  {seasonal_real} roads have REAL seasonal restrictions (not year-round)")

    # Quick stats by maintenance level
    levels = {}
    for f in roads["features"]:
        ml = f.get("properties", {}).get("OPER_MAINT_LEVEL") or "unknown"
        levels[ml] = levels.get(ml, 0) + 1
    log(f"  maintenance levels: {levels}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(roads, f, separators=(",", ":"))
    size_kb = OUTPUT.stat().st_size // 1024
    log(f"Wrote {OUTPUT} ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
