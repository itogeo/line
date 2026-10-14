#!/usr/bin/env python3
"""
Phase 2: merge all cached S2 bands into fixed geographic chunks and encode WebPs.

Instead of per-MGRS-tile outputs with complex territory logic, this produces a
3-column × 2-row grid of pure lat/lon rectangles covering the AOI. Each chunk
is already in WGS84 — no UTM boundary staircases, no territory-overlap algorithm.

Usage:
    python snowline/pipeline/process_tiles.py --date=2026-04-19
    python snowline/pipeline/process_tiles.py --date=2026-04-19 --quality=65
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
from PIL import Image

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))  # repo root, for `lib`
from lib.aoi import SNOWLINE  # noqa: E402

CACHE_ROOT = REPO_ROOT / "cache"
SITE_DIR = REPO_ROOT / "site" / "data_10m"
BBOX = SNOWLINE.bbox_list   # west, south, east, north
NDSI_THRESHOLD = 0.4
SCL_SNOW = 11          # Sentinel-2 scene classification: snow / ice
METHOD = "NDSI >= 0.4 or SCL = 11, excluding SCL 0/3/8/9/10"
PIXEL_SIZE = 0.0003   # degrees/pixel — ~24 m horizontal, ~33 m vertical at 45°N
DST_CRS = CRS.from_epsg(4326)
MIN_LIST_COVERAGE = 10.0  # % of the AOI a pass must image (clouds included) to appear on the timeline
MAX_WEBP_BYTES = 24 * 1024 * 1024  # warn if over 24 MiB (Cloudflare Pages cap is 25 MiB)

# Fixed 3-column × 2-row grid over the AOI. Pure lat/lon rectangles so
# Mapbox type:'image' sources display them without any UTM projection artifact.
_w, _s, _e, _n = BBOX
_cw = (_e - _w) / 3   # column width ≈ 1.0667°
_rh = (_n - _s) / 2   # row height = 0.8°
CHUNKS = [
    {
        'id': f'r{r}c{c}',
        'west':  _w + c * _cw,
        'south': _s + r * _rh,
        'east':  _w + (c + 1) * _cw,
        'north': _s + (r + 1) * _rh,
    }
    for r in range(2) for c in range(3)
]


def log(msg):
    print(f"[process] {msg}", flush=True)


def merge_band(tile_dirs, band_name, bounds, resampling):
    """Reproject each tile band into a fixed WGS84 grid and mosaic (first-wins)."""
    w, s, e, n = bounds
    dst_w = round((e - w) / PIXEL_SIZE)
    dst_h = round((n - s) / PIXEL_SIZE)
    dst_tf = from_bounds(w, s, e, n, dst_w, dst_h)
    mosaic = np.zeros((dst_h, dst_w), dtype=np.float32)

    any_data = False
    for d in tile_dirs:
        p = d / f"{band_name}.tif"
        if not p.exists():
            continue
        try:
            with rasterio.open(p) as src:
                # Skip tiles that don't reach this chunk: reprojecting a
                # full band only to throw it away is most of the runtime.
                tb = transform_bounds(src.crs, DST_CRS, *src.bounds)
                if tb[0] >= e or tb[2] <= w or tb[1] >= n or tb[3] <= s:
                    continue
                tile_out = np.zeros((dst_h, dst_w), dtype=np.float32)
                reproject(
                    src.read(1).astype(np.float32),
                    tile_out,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=dst_tf,
                    dst_crs=DST_CRS,
                    resampling=resampling,
                    src_nodata=0,
                    dst_nodata=0,
                )
                # Only fill pixels where mosaic has no data yet
                fill = (mosaic == 0) & (tile_out > 0)
                mosaic[fill] = tile_out[fill]
                any_data = True
        except Exception:
            pass
    return mosaic if any_data else None


def process_chunk(chunk, tile_dirs, output_dir, quality):
    """Merge all bands for one geographic chunk, classify, save snow + truecolor WebPs."""
    cid = chunk['id']
    w, s, e, n = chunk['west'], chunk['south'], chunk['east'], chunk['north']
    bounds = (w, s, e, n)

    green = merge_band(tile_dirs, 'green',  bounds, Resampling.bilinear)
    if green is None:
        log(f"  {cid}: no green band data — skip")
        return None
    red  = merge_band(tile_dirs, 'red',    bounds, Resampling.bilinear)
    blue = merge_band(tile_dirs, 'blue',   bounds, Resampling.bilinear)
    swir = merge_band(tile_dirs, 'swir16', bounds, Resampling.bilinear)
    scl  = merge_band(tile_dirs, 'scl',    bounds, Resampling.nearest)

    dst_h, dst_w = green.shape

    has_data = (green > 0) | (red > 0) | (blue > 0) | (swir > 0)
    denom = green + swir
    with np.errstate(divide='ignore', invalid='ignore'):
        ndsi = np.where(denom > 0, (green - swir) / denom, 0.0)
    cloud = np.isin(scl.astype(int), [0, 3, 8, 9, 10]) | ~has_data
    valid = has_data & ~cloud
    # Snow if the NDSI test passes OR ESA's scene classifier calls it snow
    # (SCL 11). Sen2Cor's snow test handles terrain shadow, where green
    # reflectance is too low for NDSI: in midwinter it recovered about a
    # third of the SNOTEL stations NDSI alone missed, with no new false
    # snow (snowline/site/methods.html, "Checking it against SNOTEL").
    snow  = ((ndsi >= NDSI_THRESHOLD) | (scl.astype(int) == SCL_SNOW)) & valid

    # cls: 0=ground 1=snow 2=cloud 3=nodata
    cls = np.full((dst_h, dst_w), 3, dtype=np.uint8)
    cls[valid & ~snow]    = 0
    cls[snow]             = 1
    cls[cloud & has_data] = 2

    # ── Snow RGBA (lossless) ──
    rgba_snow = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    rgba_snow[cls == 1] = [100, 210, 255, 200]  # snow — cyan
    rgba_snow[cls == 2] = [100, 100, 110, 160]  # cloud — grey
    nodata_mask = cls == 3
    if np.any(nodata_mask):
        yy, xx = np.mgrid[:dst_h, :dst_w]
        stripe = ((yy + xx) % 16 < 3) & nodata_mask
        fill   = nodata_mask & ~stripe
        rgba_snow[stripe] = [255, 190, 60, 120]
        rgba_snow[fill]   = [20, 20, 30, 60]

    snow_fname = f"snow_{cid}.webp"
    Image.fromarray(rgba_snow).save(output_dir / snow_fname, 'WEBP', lossless=True, method=4)
    snow_kb = os.path.getsize(output_dir / snow_fname) // 1024

    # ── Truecolor RGBA ──
    rgb = np.stack([
        np.clip(red   / 3000 * 255, 0, 255),
        np.clip(green / 3000 * 255, 0, 255),
        np.clip(blue  / 3000 * 255, 0, 255),
    ], axis=-1).astype(np.uint8)

    rgba_tc = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    rgba_tc[:, :, :3] = rgb
    rgba_tc[cls != 3, 3] = 255  # nodata stays alpha=0 (transparent)

    tc_fname = f"truecolor_{cid}.webp"
    Image.fromarray(rgba_tc).save(output_dir / tc_fname, 'WEBP', quality=quality, method=4)
    tc_bytes = os.path.getsize(output_dir / tc_fname)
    tc_kb = tc_bytes // 1024
    if tc_bytes > MAX_WEBP_BYTES:
        log(f"  WARNING: {tc_fname} = {tc_bytes // 1024 // 1024}MB — may hit Cloudflare 25MB cap")

    snow_px  = int(np.sum(snow))
    valid_px = int(np.sum(valid))
    log(f"  {cid}: {dst_w}x{dst_h} snow={snow_kb}KB tc={tc_kb}KB snow_px={snow_px}")

    return {
        'chunk_id': cid,
        'snow_file': snow_fname,
        'truecolor_file': tc_fname,
        'bounds': {'west': w, 'south': s, 'east': e, 'north': n},
        'snow_pixels': snow_px,
        'valid_pixels': valid_px,
        'imaged_pixels': int(np.sum(has_data)),
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 2: cached bands → geographic-chunk WebPs")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--quality", type=int, default=65,
                        help="WebP quality for truecolor (default 65)")
    args = parser.parse_args()

    date_cache = CACHE_ROOT / args.date
    if not date_cache.exists():
        log(f"FATAL: cache dir not found: {date_cache}")
        log(f"Run: python snowline/pipeline/fetch_bands.py --date={args.date}")
        return 1

    output_dir = SITE_DIR / args.date
    output_dir.mkdir(parents=True, exist_ok=True)

    tile_dirs = sorted([d for d in date_cache.iterdir() if d.is_dir()])
    if not tile_dirs:
        log(f"FATAL: no tile dirs in {date_cache}")
        return 1

    log(f"Processing {len(tile_dirs)} source tiles for {args.date} → "
        f"{len(CHUNKS)} chunks at {PIXEL_SIZE}°/px (quality={args.quality})")
    started = time.time()

    chunks_meta = []
    for chunk in CHUNKS:
        meta = process_chunk(chunk, tile_dirs, output_dir, args.quality)
        if meta:
            chunks_meta.append(meta)

    if not chunks_meta:
        log("No chunks produced.")
        return 1

    chunk_px = round(_cw / PIXEL_SIZE) * round(_rh / PIXEL_SIZE)
    total_aoi_px   = chunk_px * len(CHUNKS)
    total_valid_px = sum(m['valid_pixels'] for m in chunks_meta)
    total_snow_px  = sum(m['snow_pixels']  for m in chunks_meta)
    coverage_pct = round(total_valid_px / max(1, total_aoi_px)   * 100, 1)
    # Share of the area the pass imaged at all, clouds included.
    imaged_pct   = round(sum(m.get('imaged_pixels', 0) for m in chunks_meta) / max(1, total_aoi_px) * 100, 1)
    snow_pct     = round(total_snow_px  / max(1, total_valid_px) * 100, 1)

    # Provenance: which Sentinel-2 scenes went into this map. Written by
    # fetch_bands.py into each tile's meta.json; surfaced on the site so every
    # pixel traces back to a COG anyone can open.
    scenes = []
    for d in tile_dirs:
        mp = d / "meta.json"
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text())
        except Exception:
            continue
        if m.get("scene_id"):
            scenes.append({
                "id": m["scene_id"],
                "tile": m.get("tile_id", d.name).lstrip("T"),
                "datetime": m.get("datetime"),
                "cloud": m.get("cloud"),
                "nodata": m.get("nodata"),
                "baseline": m.get("processing_baseline"),
            })

    out_meta = {
        'scene_date': args.date,
        'source': 'Sentinel-2 C1 L2A via s2-stac-geoparquet (Taylor Geospatial / TGE Labs)' if scenes else 'Sentinel-2 L2A (Earth Search)',
        'scenes': scenes,
        'ndsi_threshold': NDSI_THRESHOLD,
        'method': METHOD,
        'bbox': BBOX,
        'bounds': {'west': BBOX[0], 'south': BBOX[1], 'east': BBOX[2], 'north': BBOX[3]},
        'snow_cover_pct': snow_pct,
        'coverage_pct': coverage_pct,
        'imaged_pct': imaged_pct,
        'chunks': chunks_meta,
    }
    with open(output_dir / 'snowline.json', 'w') as f:
        json.dump(out_meta, f)

    dates_path = SITE_DIR / "dates.json"
    existing_dates = []
    if dates_path.exists():
        try:
            existing_dates = json.load(open(dates_path)).get("dates", [])
        except Exception:
            pass
    # A pass that imaged almost none of the area (an orbit edge) clutters the
    # timeline without telling anyone anything; keep the files, don't list it.
    # Cloudy passes are listed: their imagery shows what the sky was doing.
    if imaged_pct < MIN_LIST_COVERAGE:
        log(f"Only {imaged_pct}% of the area imaged (< {MIN_LIST_COVERAGE}%) — not listing {args.date} in dates.json")
        existing_dates = [d for d in existing_dates if d != args.date]
    elif args.date not in existing_dates:
        existing_dates.append(args.date)
    existing_dates = sorted(set(existing_dates))
    with open(dates_path, "w") as f:
        json.dump({"dates": existing_dates, "latest": existing_dates[-1]}, f)

    elapsed = int(time.time() - started)
    log(f"Done in {elapsed}s. {snow_pct}% snow, {coverage_pct}% AOI coverage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
