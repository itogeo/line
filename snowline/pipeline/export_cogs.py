#!/usr/bin/env python3
"""
Export each Snowline map as Cloud-Optimized GeoTIFFs: the open-data form of
the snow map, for GIS users who want the classes rather than a picture.

One single-band uint8 COG per chunk, EPSG:4326, same 0.0003° grid as the
WebPs, read back from the lossless snow WebP so it matches the map exactly:

    0 = ground (imaged, not snow)   1 = snow   2 = cloud   3 = no data
    nodata value: 255 (outside the chunk; never written)

Writes site/data_10m/{date}/snow_r{row}c{col}.tif and records each file as
`class_file` in that date's snowline.json. The files go to R2 with the
tiles (sync_r2.py) and are served at /snow/api/tile/{date}/{file}.

Usage:
    python snowline/pipeline/export_cogs.py --date=2026-10-03
    python snowline/pipeline/export_cogs.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds

DATA_10M = Path(__file__).resolve().parent.parent / "site" / "data_10m"
CLASSES = {"ground": 0, "snow": 1, "cloud": 2, "nodata": 3}


def log(msg):
    print(f"[cogs] {msg}", flush=True)


def alpha_to_class(alpha: np.ndarray) -> np.ndarray:
    """The class is encoded in the WebP alpha by process_tiles.py."""
    out = np.full(alpha.shape, CLASSES["nodata"], dtype=np.uint8)
    out[alpha == 0] = CLASSES["ground"]
    out[alpha == 200] = CLASSES["snow"]
    out[alpha == 160] = CLASSES["cloud"]
    return out


def export_date(date: str) -> int:
    d = DATA_10M / date
    meta_p = d / "snowline.json"
    if not meta_p.exists():
        log(f"{date}: no snowline.json")
        return 0
    meta = json.loads(meta_p.read_text())
    chunks = meta.get("chunks") or []
    if not chunks:
        log(f"{date}: older per-tile map, skipped (reprocess it to get COGs)")
        return 0
    n = 0
    for c in chunks:
        webp = d / c["snow_file"]
        if not webp.exists():
            continue
        cls = alpha_to_class(np.asarray(Image.open(webp).getchannel("A")))
        b = c["bounds"]
        h, w = cls.shape
        tif = d / c["snow_file"].replace(".webp", ".tif")
        profile = {
            "driver": "COG", "width": w, "height": h, "count": 1, "dtype": "uint8",
            "crs": CRS.from_epsg(4326), "transform": from_bounds(b["west"], b["south"], b["east"], b["north"], w, h),
            "nodata": 255, "compress": "deflate", "blocksize": 512, "overview_resampling": "nearest",
        }
        with rasterio.open(tif, "w", **profile) as dst:
            dst.write(cls, 1)
            dst.update_tags(1, classes="0=ground,1=snow,2=cloud,3=nodata", date=date,
                            source="Snowline (github.com/itogeo/line); contains modified Copernicus Sentinel data")
        c["class_file"] = tif.name
        n += 1
    meta_p.write_text(json.dumps(meta))
    log(f"{date}: {n} COGs ({sum((d / c['class_file']).stat().st_size for c in chunks if c.get('class_file')) // 1024} KB)")
    return n


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--date")
    g.add_argument("--all", action="store_true")
    args = ap.parse_args()
    dates = [args.date] if args.date else sorted(p.name for p in DATA_10M.iterdir() if p.is_dir())
    total = sum(export_date(x) for x in dates)
    log(f"done: {total} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
