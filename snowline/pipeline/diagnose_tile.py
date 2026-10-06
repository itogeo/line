#!/usr/bin/env python3
"""Print every bounds value we read or derive for a single date+tile.
Tells us exactly where a sliver is introduced — the index, the COG, or our code.

Usage:  python snowline/pipeline/diagnose_tile.py 2026-04-19 T12TVR
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")

import rasterio
from rasterio.warp import transform_bounds
from rasterio.crs import CRS
import rasterio.windows as rwin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
from lib import s2index  # noqa: E402
from lib.aoi import SNOWLINE  # noqa: E402

BBOX = SNOWLINE.bbox_list

def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("tile", help="MGRS tile, e.g. T12TVR or 12TVR")
    args = ap.parse_args()
    date_str = args.date
    target_tile = "T" + s2index.norm_tile(args.tile)

    print(f"\n=== DIAGNOSING {target_tile} on {date_str} ===\n")

    # 1. Look the scene up in the S2 GeoParquet index
    items = s2index.scenes([target_tile], date_str, date_str, dedupe_daily=False)
    print(f"Index rows matching {target_tile}: {len(items)}")
    for it in items:
        print(f"  id={it['id']}  datetime={it['datetime']}")
        print(f"  bbox (WGS84) = {it['bbox']}  ← scene footprint")
        print(f"  proj:epsg = {it['epsg']}  baseline={it['baseline']}  "
              f"cloud={it['cloud']}  nodata={it['nodata']}")
        print(f"  green scale/offset = {s2index.scale_offset(it, 'green')}")

    if not items:
        print("No scenes matched. Exiting.")
        return

    # 2. Open the COG and check its actual native bounds
    item = items[0]
    href = s2index.asset_href(item, "green")
    print(f"\nOpening green COG: {href}\n")
    with rasterio.open(href) as src:
        print(f"  src.crs       = {src.crs}")
        print(f"  src.width     = {src.width}   (expect 10980 for full tile)")
        print(f"  src.height    = {src.height}")
        print(f"  src.transform = {src.transform}")
        print(f"  src.bounds    = {src.bounds}")
        native_4326 = transform_bounds(src.crs, CRS.from_epsg(4326),
                                       src.bounds.left, src.bounds.bottom,
                                       src.bounds.right, src.bounds.top)
        print(f"  transform_bounds -> WGS84 = {native_4326}")
        print(f"  native width in WGS84 = {native_4326[2]-native_4326[0]:.4f}°")

        # 3. Compute the fetch window our pipeline would use
        bp = transform_bounds(CRS.from_epsg(4326), src.crs, *BBOX)
        print(f"\n  AOI in source CRS: {bp}")
        win = rwin.from_bounds(*bp, transform=src.transform)
        print(f"  window from_bounds: col_off={win.col_off:.1f} row_off={win.row_off:.1f} "
              f"w={win.width:.1f} h={win.height:.1f}")
        clipped = win.intersection(rwin.Window(0, 0, src.width, src.height))
        print(f"  clipped to src:     col_off={clipped.col_off:.1f} row_off={clipped.row_off:.1f} "
              f"w={clipped.width:.1f} h={clipped.height:.1f}")
        win_tf = src.window_transform(clipped)
        print(f"  window_transform   = {win_tf}")
        win_bounds_utm = rasterio.transform.array_bounds(
            int(clipped.height), int(clipped.width), win_tf)
        win_bounds_4326 = transform_bounds(src.crs, CRS.from_epsg(4326), *win_bounds_utm)
        print(f"  => window bounds in WGS84: {win_bounds_4326}")
        print(f"  => window width WGS84: {win_bounds_4326[2]-win_bounds_4326[0]:.4f}°")

    # 4. Read the CACHED green.tif (what process_tiles actually sees)
    cache_p = Path(__file__).parent.parent / "cache" / date_str / target_tile / "green.tif"
    if cache_p.exists():
        print(f"\nCached green.tif: {cache_p}")
        with rasterio.open(cache_p) as src:
            print(f"  cached src.crs       = {src.crs}")
            print(f"  cached src.width     = {src.width}")
            print(f"  cached src.height    = {src.height}")
            print(f"  cached src.transform = {src.transform}")
            print(f"  cached src.bounds    = {src.bounds}")
            cached_4326 = transform_bounds(src.crs, CRS.from_epsg(4326),
                                           *src.bounds)
            print(f"  cached bounds WGS84  = {cached_4326}")
            print(f"  cached width WGS84   = {cached_4326[2]-cached_4326[0]:.4f}°")
    else:
        print(f"\nNo cached green.tif at {cache_p} (run fetch_bands first for this date).")


if __name__ == "__main__":
    main()
