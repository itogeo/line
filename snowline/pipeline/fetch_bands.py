#!/usr/bin/env python3
"""
Phase 1 of the snowline imagery pipeline: download band windows.

For one date, finds every Sentinel-2 Collection 1 L2A scene over the AOI
in the Taylor Geospatial S2 STAC GeoParquet index (lib/s2index.py — one
DuckDB query, no STAC API), then for each tile downloads the AOI window of
5 bands (green, red, blue, swir16, scl) and writes them as small GeoTIFFs
to a cache directory:

    cache/{date}/{tile_id}/{band}.tif

Reflectance bands are written as DN = 10000 * surface reflectance, i.e. the
Collection 1 offset (raster:bands offset -0.1, a +1000 DN shift from
processing baseline 04.00 on) is removed at download time. That matches
what the older Earth Search `sentinel-2-l2a` COGs stored, so the cache —
and everything downstream of it — is identical to before the switch
(checked pixel-for-pixel on 12TVR 2026-04-19; see snowline/PLAN.md).

This is the slow, network-bound, failure-prone half of the old monolithic
script. Splitting it out gives us:

  - Resumability: existing cache files are skipped on re-run, so a flaky
    network only costs you the bands that haven't downloaded yet.
  - Parallelism: bands within a tile are read concurrently.
  - Cheap re-encoding: process_tiles.py runs from local cache, no S3.

Usage:
    python snowline/pipeline/fetch_bands.py --date=2026-04-04
    python snowline/pipeline/fetch_bands.py --date=2026-04-04 --workers=8
    python snowline/pipeline/fetch_bands.py --date=2026-04-04 --force  # ignore cache
    python snowline/pipeline/fetch_bands.py --date=2026-04-04 --tiles=12TVR  # smoke test, one tile
"""

import argparse
import os
import sys
import time
import traceback
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
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
import rasterio
from rasterio.warp import transform_bounds
from rasterio.crs import CRS

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))  # repo root, for `lib`
from lib import s2index  # noqa: E402
from lib.aoi import SNOWLINE  # noqa: E402

CACHE_ROOT = REPO_ROOT / "cache"
BBOX = SNOWLINE.bbox_list
BANDS = ["green", "red", "blue", "swir16", "scl"]
REFLECTANCE_BANDS = {"green", "red", "blue", "swir16"}

# Sequential by default. The previous defaults (4 tiles x 4 bands = 16
# simultaneous S3 connections) were too aggressive for residential
# connections — S3 throttled and TLS handshakes timed out
# with the cryptic "Read failed. See previous exception" error.
# If you want to try parallelism on a fast connection, pass --workers
# and --tile-parallelism on the command line.
DEFAULT_WORKERS = 1   # parallel BAND fetches per tile
TILE_PARALLELISM = 1  # parallel tiles
BAND_RETRY = 4
BAND_RETRY_DELAY = 5  # seconds


def log(msg):
    print(f"[fetch] {msg}", flush=True)


def tile_label(row):
    """'12TVR' -> 'T12TVR' (the cache directory name)."""
    return "T" + row["tile"]


def find_scenes(date_str):
    """Every C1 L2A scene over the AOI tiles on this UTC date, one per tile
    (the least-nodata copy when a tile was imaged twice)."""
    return s2index.scenes(SNOWLINE.tiles, date_str, date_str)


def harmonize(arr, scale, offset):
    """C1 DN -> 10000 * reflectance, keeping 0 as nodata. Valid pixels that
    would land at or below 0 (very dark, e.g. shadowed water) are clipped
    to 1 so they aren't mistaken for nodata."""
    if scale == 1.0 and offset == 0.0:
        return arr
    if abs(scale * 10000.0 - 1.0) < 1e-9 and float(offset * 10000.0).is_integer():
        # The usual case (scale 0.0001, offset -0.1): an integer shift.
        # Done in uint16 to keep memory flat on 10980x10980 bands.
        k = int(round(-offset * 10000.0))  # e.g. 1000
        out = np.zeros_like(arr)
        above = arr > k
        out[above] = arr[above] - k
        out[(arr != 0) & ~above] = 1
        return out
    nodata = arr == 0
    refl = arr.astype(np.float32) * (scale * 10000.0) + offset * 10000.0
    out = np.clip(np.rint(refl), 1, 65535).astype(np.uint16)
    out[nodata] = 0
    return out


def fetch_band(href, out_path, scale=1.0, offset=0.0):
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
                # Snap to whole pixels. read() rounds a fractional window to
                # the nearest pixel, so the transform must use the same
                # rounded window or the output shifts by a fraction of a pixel.
                win = rasterio.windows.Window(
                    round(win.col_off), round(win.row_off), round(win.width), round(win.height),
                ).intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                arr = harmonize(src.read(1, window=win), scale, offset)
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


def write_tile_meta(row, tile_dir):
    """Record where this tile's pixels came from: the scene id, the MGRS
    tile footprint (WGS84 bbox from the index) and the offsets applied."""
    meta_path = tile_dir / "meta.json"
    if meta_path.exists():
        return
    meta_path.write_text(json.dumps({
        "tile_id": tile_label(row),
        "scene_id": row["id"],
        "datetime": row["datetime"].isoformat(),
        "cloud": row["cloud"],
        "nodata": row["nodata"],
        "processing_baseline": row["baseline"],
        "native_bounds_4326": list(row["bbox"]) if row.get("bbox") else None,
        "hrefs": {b: s2index.asset_href(row, b) for b in BANDS},
        "harmonized": {b: s2index.scale_offset(row, b) for b in REFLECTANCE_BANDS},
        "source": "s2-stac-geoparquet/sentinel-2-c1-l2a",
    }))


def fetch_tile(row, tile_dir, force, workers):
    """Download all 5 bands for one tile in parallel. Skips bands that
    already exist on disk unless --force was passed. Returns (tile_id,
    success_count, error)."""
    tile_id = tile_label(row)
    tile_dir.mkdir(parents=True, exist_ok=True)
    meta_p = tile_dir / "meta.json"
    if meta_p.exists() and not force:
        # The cache is keyed by tile and date, but the best scene for that
        # tile-day can change (a reprocessed scene, a better datatake). Never
        # mix bands from two scenes: start the tile over if the id changed.
        try:
            cached_id = json.loads(meta_p.read_text()).get("scene_id")
        except Exception:
            cached_id = None
        if cached_id != row["id"]:
            log(f"  {tile_id}: cached scene {cached_id} != {row['id']}; re-fetching")
            force = True
    if force:
        for f in tile_dir.glob("*"):
            f.unlink()
    write_tile_meta(row, tile_dir)
    todo = []
    skipped = 0
    for band in BANDS:
        href = s2index.asset_href(row, band)
        out = tile_dir / f"{band}.tif"
        if out.exists() and not force:
            skipped += 1
            continue
        scale, offset = s2index.scale_offset(row, band) if band in REFLECTANCE_BANDS else (1.0, 0.0)
        todo.append((band, href, out, scale, offset))

    if not todo:
        log(f"  {tile_id}: cached ({skipped}/{len(BANDS)} bands)")
        return (tile_id, len(BANDS), None)

    log(f"  {tile_id}: fetching {len(todo)} bands ({skipped} cached)")
    success = skipped
    err = None
    # Bands within a tile run in parallel — they're independent reads.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_band, href, out, sc, off): band for band, href, out, sc, off in todo}
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


# Exit code for "the index has no usable scene for this date" (all cloud, or
# orbit-edge slivers). Not a failure: update_date.sh passes it on, and the
# imagery workflow skips the date without failing the job. Any other
# non-zero exit is a real failure.
NO_SCENES_EXIT = 3


def main():
    parser = argparse.ArgumentParser(description="Phase 1: download Sentinel-2 band windows for one date")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Parallel band reads per tile (default {DEFAULT_WORKERS})")
    parser.add_argument("--tile-parallelism", type=int, default=TILE_PARALLELISM,
                        help=f"Parallel tiles in flight (default {TILE_PARALLELISM})")
    parser.add_argument("--force", action="store_true",
                        help="Re-download bands even if cached on disk")
    parser.add_argument("--max-cloud", type=float, default=90,
                        help="Skip tiles with more scene cloud than this (default 90: they add only cloud)")
    parser.add_argument("--tiles", default="",
                        help="Comma-separated subset of tiles, e.g. 12TVR,12TWR (default: all AOI tiles)")
    args = parser.parse_args()

    date_dir = CACHE_ROOT / args.date
    log(f"Cache dir: {date_dir}")
    log(f"Searching the S2 GeoParquet index for {args.date}...")
    items = find_scenes(args.date)
    if args.tiles:
        keep = {s2index.norm_tile(t) for t in args.tiles.split(",")}
        items = [r for r in items if r["tile"] in keep]
    n_all = len(items)
    # Skip orbit-edge slivers and tiles that are (almost) all cloud: they add
    # nothing to the map or to the latest view but take the same download.
    items = [r for r in items
             if (r["cloud"] if r["cloud"] is not None else 100) <= args.max_cloud
             and (r["nodata"] or 0) < 95]
    if not items:
        log(f"No usable Sentinel-2 scenes for {args.date} ({n_all} all cloud or slivers)")
        return NO_SCENES_EXIT
    log(f"Found {len(items)} usable S2 scenes for {args.date} (skipped {n_all - len(items)} cloudy/sliver)")
    items_sorted = sorted(items, key=lambda r: r["tile"])

    started = time.time()
    failures = []
    completed = 0

    with ThreadPoolExecutor(max_workers=args.tile_parallelism) as ex:
        futs = {}
        for item in items_sorted:
            tile_id = tile_label(item)
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
