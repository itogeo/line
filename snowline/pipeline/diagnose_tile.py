#!/usr/bin/env python3
"""Print every bounds value we read or derive for a single date+tile.
Tells us exactly where the sliver is introduced — STAC, COG, or our code.

Usage:  python pipeline/diagnose_tile.py 2026-04-19 T12TVR
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")

import pystac_client
import rasterio
from rasterio.warp import transform_bounds
from rasterio.crs import CRS
import rasterio.windows as rwin

BBOX = [-112.2, 44.9, -109.0, 46.5]

def main():
    if len(sys.argv) < 3:
        print("usage: python pipeline/diagnose_tile.py YYYY-MM-DD TILE_ID")
        sys.exit(1)
    date_str, target_tile = sys.argv[1], sys.argv[2]

    print(f"\n=== DIAGNOSING {target_tile} on {date_str} ===\n")

    # 1. Query STAC
    cat = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
    center = datetime.strptime(date_str, "%Y-%m-%d")
    search = cat.search(
        collections=["sentinel-2-l2a"],
        bbox=BBOX,
        datetime=f"{center:%Y-%m-%d}T00:00:00Z/{center + timedelta(days=1):%Y-%m-%d}T00:00:00Z",
        max_items=50,
    )
    items = [it for it in search.items() if target_tile[1:] in it.id]
    print(f"STAC items matching {target_tile}: {len(items)}")
    for it in items:
        print(f"  id={it.id}")
        print(f"  item.bbox (WGS84) = {it.bbox}  ← canonical per STAC spec")
        width = it.bbox[2] - it.bbox[0]
        print(f"  item.bbox width = {width:.4f}°  (expect ~1.0–1.4° for a full MGRS tile)")
        gt = it.properties.get("proj:transform")
        shp = it.properties.get("proj:shape")
        proj_bbox = it.properties.get("proj:bbox")
        epsg = it.properties.get("proj:epsg")
        print(f"  proj:epsg = {epsg}")
        print(f"  proj:shape = {shp}   (expect [10980,10980] for full tile)")
        print(f"  proj:transform = {gt}")
        print(f"  proj:bbox = {proj_bbox}")

    if not items:
        print("No STAC items matched. Exiting.")
        return

    # 2. Open the COG and check its actual native bounds
    item = items[0]
    href = item.assets["green"].href
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
