#!/usr/bin/env python3
"""
Publish Snowline's maps as a static STAC catalog, so any STAC client
(QGIS, pystac, stac-browser, Portolan) can browse and load them.

    site/stac/catalog.json
    site/stac/snowline-snow-cover/collection.json
    site/stac/snowline-snow-cover/{date}/{date}.json     one item per map

Each item has the per-chunk class COGs (export_cogs.py), the map WebPs and
snowline.json as assets, and links back to the Sentinel-2 scenes it was
made from. Static JSON only: served by Cloudflare Pages at
https://line.itogeospatial.com/snow/stac/catalog.json

Usage:
    python snowline/pipeline/build_stac.py
"""

from __future__ import annotations

if __name__ == "__main__":
    # --help before the heavy imports below (and before anything runs).
    import argparse
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()


import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))
from lib.aoi import SNOWLINE  # noqa: E402

SITE = "https://line.itogeospatial.com/snow"
DATA_10M = REPO_ROOT / "site" / "data_10m"
OUT = REPO_ROOT / "site" / "stac"
COLL = "snowline-snow-cover"
STAC = "1.1.0"
EXT = [
    "https://stac-extensions.github.io/classification/v2.0.0/schema.json",
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
]
CLASSES = [
    {"value": 0, "name": "ground", "description": "Imaged, not snow"},
    {"value": 1, "name": "snow", "description": "NDSI >= 0.4 or SCL snow (11), and not masked"},
    {"value": 2, "name": "cloud", "description": "SCL cloud, cloud shadow or cirrus"},
    {"value": 3, "name": "nodata", "description": "Not imaged that day"},
]


def log(msg):
    print(f"[stac] {msg}", flush=True)


def write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))


def date_bbox(meta):
    """The box this map was made on: snowline.json "bbox" (west, south, east,
    north). Older maps were made on an older AOI, so each item keeps its own."""
    if meta.get("bbox"):
        return [float(v) for v in meta["bbox"]]
    b = meta.get("bounds") or {}
    if b:
        return [b["west"], b["south"], b["east"], b["north"]]
    return list(SNOWLINE.bbox)


def main():
    # Only dates the site lists: a date is listed once its tiles are in R2,
    # so every asset URL below resolves.
    listed = set(json.loads((DATA_10M / "dates.json").read_text()).get("dates", []))
    items, boxes = [], []
    for d in sorted(p for p in DATA_10M.iterdir() if p.is_dir() and p.name in listed):
        mp = d / "snowline.json"
        if not mp.exists():
            continue
        meta = json.loads(mp.read_text())
        chunks = meta.get("chunks") or []
        if not any(c.get("class_file") for c in chunks):
            continue
        date = d.name
        w, s, e, n = date_bbox(meta)
        poly = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
        assets = {"metadata": {"href": f"{SITE}/data_10m/{date}/snowline.json", "type": "application/json",
                               "title": "Snowline map metadata (scenes, coverage)", "roles": ["metadata"]}}
        for c in chunks:
            b = c["bounds"]
            bbox = [b["west"], b["south"], b["east"], b["north"]]
            if c.get("class_file"):
                assets[f"class_{c['chunk_id']}"] = {
                    "href": f"{SITE}/api/tile/{date}/{c['class_file']}",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": f"Snow class raster, chunk {c['chunk_id']}",
                    "roles": ["data"],
                    "proj:code": "EPSG:4326", "proj:bbox": bbox,
                    "classification:classes": CLASSES,
                    "nodata": 255,
                }
            assets[f"preview_{c['chunk_id']}"] = {
                "href": f"{SITE}/api/tile/{date}/{c['snow_file']}", "type": "image/webp",
                "title": f"Map tile (RGBA), chunk {c['chunk_id']}", "roles": ["overview"],
            }
        sources = [{"rel": "derived_from", "type": "application/json", "title": sc["id"],
                    "href": f"https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/{sc['id']}"}
                   for sc in meta.get("scenes", [])]
        item = {
            "type": "Feature", "stac_version": STAC, "stac_extensions": EXT,
            "id": f"snowline-{date}", "collection": COLL,
            "geometry": poly, "bbox": [w, s, e, n],
            "properties": {
                # Real acquisition times from the scenes used; a nominal
                # local-noon time only for older maps that don't list them.
                **({"datetime": None,
                    "start_datetime": min(sc["datetime"] for sc in meta["scenes"]),
                    "end_datetime": max(sc["datetime"] for sc in meta["scenes"])}
                   if meta.get("scenes") else {"datetime": f"{date}T18:30:00Z"}),
                "title": f"Snowline snow cover {date}",
                "snowline:snow_cover_pct": meta.get("snow_cover_pct"),
                "snowline:coverage_pct": meta.get("coverage_pct"),
                "snowline:ndsi_threshold": meta.get("ndsi_threshold", 0.4),
            },
            "links": [
                {"rel": "collection", "href": "../collection.json", "type": "application/json"},
                {"rel": "parent", "href": "../collection.json", "type": "application/json"},
                {"rel": "root", "href": "../../catalog.json", "type": "application/json"},
                {"rel": "alternate", "href": f"{SITE}/#date={date}", "type": "text/html", "title": "Open on the map"},
                *sources,
            ],
            "assets": assets,
        }
        write(OUT / COLL / date / f"{date}.json", item)
        items.append(date)
        boxes.append([w, s, e, n])

    if not items:
        log("no maps with class COGs yet (run export_cogs.py)")
        return 1
    coll = {
        "type": "Collection", "stac_version": STAC, "stac_extensions": [EXT[0]],
        "id": COLL, "title": "Snowline snow cover, SW Montana",
        "description": "Daily snow / ground / cloud / no-data classification of SW Montana from Sentinel-2 "
                       "Collection 1 L2A (NDSI >= 0.4 or SCL snow, with the SCL cloud mask), on a 0.0003 degree grid. "
                       "Method: https://line.itogeospatial.com/snow/methods.html",
        "license": "other",
        "keywords": ["snow", "Sentinel-2", "Montana", "NDSI"],
        "providers": [
            {"name": "Ito Geospatial", "roles": ["processor", "host"], "url": "https://itogeospatial.com"},
            {"name": "ESA Copernicus", "roles": ["producer", "licensor"], "url": "https://sentinels.copernicus.eu"},
            {"name": "Taylor Geospatial / TGE Labs", "roles": ["host"], "url": "https://research.taylorgeospatial.org/s2-stac-geoparquet/"},
        ],
        "extent": {"spatial": {"bbox": [[min(b[0] for b in boxes), min(b[1] for b in boxes),
                                          max(b[2] for b in boxes), max(b[3] for b in boxes)]]},
                   "temporal": {"interval": [[f"{items[0]}T00:00:00Z", f"{items[-1]}T23:59:59Z"]]}},
        "summaries": {"classification:classes": CLASSES},
        "links": [
            {"rel": "root", "href": "../catalog.json", "type": "application/json"},
            {"rel": "parent", "href": "../catalog.json", "type": "application/json"},
            {"rel": "license", "href": "https://github.com/itogeo/line/blob/main/DATA_LICENSE.md", "type": "text/html",
             "title": "Contains modified Copernicus Sentinel data; see DATA_LICENSE.md"},
            *[{"rel": "item", "href": f"./{d}/{d}.json", "type": "application/geo+json"} for d in items],
        ],
    }
    write(OUT / COLL / "collection.json", coll)
    write(OUT / "catalog.json", {
        "type": "Catalog", "stac_version": STAC, "id": "line-network",
        "title": "Line Network open data",
        "description": "Open data published by the Line Network (Ito Geospatial). Code and method: https://github.com/itogeo/line",
        "links": [
            {"rel": "root", "href": "./catalog.json", "type": "application/json"},
            {"rel": "child", "href": f"./{COLL}/collection.json", "type": "application/json", "title": coll["title"]},
        ],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    log(f"{len(items)} items → {OUT.relative_to(REPO_ROOT)}/catalog.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
