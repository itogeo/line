#!/usr/bin/env python3
"""
Phase 1 of the snowline imagery pipeline: download band windows.

For one date, queries Element84 STAC for all Sentinel-2 tiles, then for
each tile downloads the AOI window of 5 bands (green, red, blue, swir16,
scl) and writes them as small GeoTIFFs to a cache directory:

    cache/{date}/{tile_id}/{band}.tif

This is the slow, network-bound, failure-prone half of the old monolithic
script. Splitting it out gives us:

  - Resumability: existing cache files are skipped on re-run, so a flaky
    network only costs you the bands that haven't downloaded yet.
  - Parallelism: bands within a tile are read concurrently.
  - Cheap re-encoding: process_tiles.py runs from local cache, no S3.

Usage:
    python pipeline/fetch_bands.py --date=2026-04-04
    python pipeline/fetch_bands.py --date=2026-04-04 --workers=8
    python pipeline/fetch_bands.py --date=2026-04-04 --force  # ignore cache
"""

import argparse
import os
import sys
import time
import traceback
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

# GDAL HTTP tuning — minimal set, conservative.
# An earlier version of this script set 9+ env vars for "performance" and
# broke reads on the venv's older GDAL build (residential connection +
# aggressive parallelism = TLS handshake failures with cryptic
# "Read failed" errors). Now we only set:
#   - GDAL_DISABLE_READDIR_ON_OPEN: skips a useless directory listing
#     when opening a single COG by URL (this one is universally safe).
#   - GDAL_HTTP_TIMEOUT: 60s per range request (default is 30s, sometimes
#     not enough for the larger center tiles).
# Everything else uses GDAL defaults — proven to work with run_pertile.py.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")

import numpy as np
import pystac_client
import rasterio
from rasterio.warp import transform_bounds
from rasterio.crs import CRS

REPO_ROOT = Path(__file__).parent.parent
CACHE_ROOT = REPO_ROOT / "cache"
BBOX = [-112.2, 44.9, -109.0, 46.5]
BANDS = ["green", "red", "blue", "swir16", "scl"]

# Sequential by default. The previous defaults (4 tiles x 4 bands = 16
# simultaneous S3 connections) were too aggressive for residential
# connections — Element84 / S3 throttled and TLS handshakes timed out
# with the cryptic "Read failed. See previous exception" error.
# If you want to try parallelism on a fast connection, pass --workers
# and --tile-parallelism on the command line.
DEFAULT_WORKERS = 1   # parallel BAND fetches per tile
TILE_PARALLELISM = 1  # parallel tiles
BAND_RETRY = 4
BAND_RETRY_DELAY = 5  # seconds


def log(msg):
    print(f"[fetch] {msg}", flush=True)


def parse_tile_id(item_id):
    """Element84 ID format: S2C_12TUQ_20260404_0_L2A → 'T12TUQ'"""
    for p in item_id.split("_"):
        if p.startswith("T") and len(p) == 6:
            return p
        if len(p) == 5 and p[0].isdigit():
            return "T" + p
    return item_id[:10]


def find_scenes(date_str):
    """Query Element84 for the EXACT date. Returns list of STAC items."""
    catalog = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
    center = datetime.strptime(date_str, "%Y-%m-%d")
    next_day = center + timedelta(days=1)
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=BBOX,
        datetime=f"{center:%Y-%m-%d}T00:00:00Z/{next_day:%Y-%m-%d}T00:00:00Z",
        max_items=50,
    )
    return list(search.items())


def fetch_band(href, out_path):
    """Read the AOI window from a remote COG and write it as a small GeoTIFF.
    Retries on transient errors. Raises after BAND_RETRY attempts."""
    last_exc = None
    for attempt in range(BAND_RETRY):
        try:
            with rasterio.open(href) as src:
                bp = transform_bounds(CRS.from_epsg(4326), src.crs, *BBOX)
                win = rasterio.windows.from_bounds(*bp, transform=src.transform)
                win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                if win.width < 1 or win.height < 1:
                    return False  # window outside tile
                arr = src.read(1, window=win)
                win_tf = src.window_transform(win)

                profile = {
                    "driver": "GTiff",
                    "height": int(win.height),
                    "width": int(win.width),
                    "count": 1,
                    "dtype": arr.dtype,
                    "crs": src.crs,
                    "transform": win_tf,
                    "compress": "deflate",
                    "tiled": True,
                    "blockxsize": 512,
                    "blockysize": 512,
                }
                tmp = out_path.with_suffix(out_path.suffix + ".tmp")
                with rasterio.open(tmp, "w", **profile) as dst:
                    dst.write(arr, 1)
                tmp.replace(out_path)
                return True
        except Exception as e:
            last_exc = e
            if attempt < BAND_RETRY - 1:
                msg = f"{type(e).__name__}: {str(e)[:120]}"
                log(f"    retry {attempt+1}/{BAND_RETRY} after {BAND_RETRY_DELAY}s: {msg}")
                time.sleep(BAND_RETRY_DELAY)
    # All retries exhausted — show the FULL traceback so the underlying
    # GDAL/SSL/HTTP error is visible instead of just "Read failed".
    log(f"    FINAL FAILURE for {href}:")
    log(traceback.format_exc())
    raise last_exc


def write_tile_meta(item, tile_dir):
    """Record the STAC item's canonical tile bbox (WGS84) — per the STAC
    spec, item.bbox for S2 L2A is the MGRS tile footprint, fixed per
    tile_id and independent of any single observation or the COG's
    internal transform."""
    meta_path = tile_dir / "meta.json"
    if meta_path.exists():
        return
    try:
        bbox = list(item.bbox) if item.bbox else None
        if not bbox:
            return
        meta_path.write_text(json.dumps({
            "tile_id": parse_tile_id(item.id),
            "native_bounds_4326": bbox,
            "source": "stac_item.bbox",
        }))
    except Exception as e:
        log(f"  {parse_tile_id(item.id)}: meta.json write failed: {type(e).__name__}: {str(e)[:120]}")


def fetch_tile(item, tile_dir, force, workers):
    """Download all 5 bands for one tile in parallel. Skips bands that
    already exist on disk unless --force was passed. Returns (tile_id,
    success_count, error)."""
    tile_id = parse_tile_id(item.id)
    tile_dir.mkdir(parents=True, exist_ok=True)
    write_tile_meta(item, tile_dir)
    todo = []
    skipped = 0
    for band in BANDS:
        href = item.assets[band].href
        out = tile_dir / f"{band}.tif"
        if out.exists() and not force:
            skipped += 1
            continue
        todo.append((band, href, out))

    if not todo:
        log(f"  {tile_id}: cached ({skipped}/{len(BANDS)} bands)")
        return (tile_id, len(BANDS), None)

    log(f"  {tile_id}: fetching {len(todo)} bands ({skipped} cached)")
    success = skipped
    err = None
    # Bands within a tile run in parallel — they're independent reads.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_band, href, out): band for band, href, out in todo}
        for fut in as_completed(futs):
            band = futs[fut]
            try:
                ok = fut.result()
                if ok or ok is False:  # False means window-outside, still "done"
                    success += 1
            except Exception as e:
                err = f"{band}: {type(e).__name__}: {str(e)[:120]}"
                log(f"  {tile_id}: FAILED on {band} — {err}")
    return (tile_id, success, err)


def main():
    parser = argparse.ArgumentParser(description="Phase 1: download Sentinel-2 band windows for one date")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="Parallel band reads per tile (default 4)")
    parser.add_argument("--tile-parallelism", type=int, default=TILE_PARALLELISM,
                        help="Parallel tiles in flight (default 4)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download bands even if cached on disk")
    args = parser.parse_args()

    date_dir = CACHE_ROOT / args.date
    log(f"Cache dir: {date_dir}")
    log(f"Querying Element84 for {args.date}...")
    items = find_scenes(args.date)
    if not items:
        log(f"No Sentinel-2 scenes for {args.date}")
        return 1
    log(f"Found {len(items)} S2 items for {args.date}")

    # Sort items so the smallest (cheapest) tiles run first — gets early
    # wins on the screen and parallel slots free up sooner.
    # We don't know the windowed size yet so just stable-sort by id.
    items_sorted = sorted(items, key=lambda i: parse_tile_id(i.id))

    started = time.time()
    failures = []
    completed = 0

    with ThreadPoolExecutor(max_workers=args.tile_parallelism) as ex:
        futs = {}
        for item in items_sorted:
            tile_id = parse_tile_id(item.id)
            tile_dir = date_dir / tile_id
            futs[ex.submit(fetch_tile, item, tile_dir, args.force, args.workers)] = tile_id

        for fut in as_completed(futs):
            tile_id = futs[fut]
            try:
                _id, n_ok, err = fut.result()
                completed += 1
                elapsed = int(time.time() - started)
                log(f"[{completed}/{len(items_sorted)}] {tile_id}: {n_ok}/{len(BANDS)} bands ok ({elapsed}s elapsed)")
                if err:
                    failures.append((tile_id, err))
            except Exception as e:
                failures.append((tile_id, f"{type(e).__name__}: {e}"))
                log(f"[{completed}/{len(items_sorted)}] {tile_id}: CRASHED — {e}")

    elapsed = int(time.time() - started)
    log(f"Done in {elapsed}s. {completed} tiles, {len(failures)} failures.")
    if failures:
        log("Failures (re-run the same command to retry):")
        for tid, err in failures:
            log(f"  {tid}: {err}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
