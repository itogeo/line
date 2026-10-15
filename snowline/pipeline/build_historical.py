#!/usr/bin/env python3
"""
Build historical snow frequency rasters from MODIS MOD10A1 (500m, 2000-present).

For each 5-day period of the year, computes the % of years (2000-2025) where
each pixel had snow cover. Outputs WebP overlays that the site can display
as a "historical average" comparison layer.

Usage:
    python snowline/pipeline/build_historical.py
    python snowline/pipeline/build_historical.py --start-doy=1 --end-doy=365
    python snowline/pipeline/build_historical.py --doy=75  # single 5-day period

Output:
    site/data/historical/doy_001.webp  (Jan 1-5 average)
    site/data/historical/doy_006.webp  (Jan 6-10 average)
    ...
    site/data/historical/doy_361.webp  (Dec 27-31 average)
    site/data/historical/historical.json  (index + bounds)
"""

if __name__ == "__main__":
    # --help before the heavy imports below (and before anything runs).
    import argparse
    # parse_known_args: --help exits here; options like --out-dir are read in main().
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_known_args()

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pystac_client
import planetary_computer
import rasterio
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from rasterio.merge import merge
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))  # repo root, for `lib`
from lib.aoi import SNOWLINE  # noqa: E402

BBOX = SNOWLINE.bbox_list   # the snowline AOI (lib/aoi.py)
YEARS = list(range(2001, 2026))  # 25 years of MODIS
OUTPUT_DIR = Path(__file__).parent.parent / "site" / "data" / "historical"
MAX_DIM = 4000  # 500m source, so 4000px is plenty (~35m/px)


def log(msg):
    print(f"[historical] {msg}", flush=True)


def doy_to_date_range(doy, year):
    """Convert day-of-year to a (start, end) date string pair."""
    start = datetime(year, 1, 1) + timedelta(days=doy - 1)
    end = start + timedelta(days=4)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def fetch_modis_snow(bbox, start_date, end_date):
    """
    Fetch MODIS MOD10A1 snow cover for a date range.
    Returns a 2D array of NDSI_Snow_Cover (0-100 = snow %, 200+ = special values).
    """
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )

    search = catalog.search(
        collections=["modis-10A1-061"],
        bbox=bbox,
        datetime=f"{start_date}/{end_date}",
        max_items=20,
    )
    items = list(search.items())
    if not items:
        return None

    # Read and mosaic NDSI_Snow_Cover band
    datasets = []
    for item in items:
        signed = planetary_computer.sign(item)
        href = signed.assets["NDSI_Snow_Cover"].href
        datasets.append(rasterio.open(href))

    if len(datasets) == 1:
        src = datasets[0]
        bbox_proj = transform_bounds(CRS.from_epsg(4326), src.crs, *bbox)
        window = rasterio.windows.from_bounds(*bbox_proj, transform=src.transform)
        window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        data = src.read(1, window=window)
        tf = src.window_transform(window)
        crs = src.crs
        src.close()
    else:
        mosaic_arr, tf = merge(datasets)
        crs = datasets[0].crs
        for ds in datasets:
            ds.close()
        # Window to bbox
        bbox_proj = transform_bounds(CRS.from_epsg(4326), crs, *bbox)
        window = rasterio.windows.from_bounds(*bbox_proj, transform=tf)
        r0 = max(0, int(window.row_off))
        c0 = max(0, int(window.col_off))
        r1 = min(mosaic_arr.shape[1], int(window.row_off + window.height))
        c1 = min(mosaic_arr.shape[2], int(window.col_off + window.width))
        data = mosaic_arr[0, r0:r1, c0:c1]

    # MODIS snow cover values: 0-100 = NDSI snow cover %
    # Values > 100 are flags (200=missing, 201=no decision, 211=night, 237=inland water, 239=ocean, 250=cloud, 254=detector sat, 255=fill)
    snow_mask = data <= 100  # valid snow data
    is_snow = (data >= 10) & snow_mask  # NDSI >= 10% counts as snow

    return is_snow, snow_mask


def build_frequency_for_doy(doy):
    """Build a snow frequency raster for a 5-day period across all years."""
    log(f"DOY {doy:03d} ({datetime(2024,1,1) + timedelta(days=doy-1):%b %d})...")

    snow_count = None
    valid_count = None
    years_with_data = 0

    for year in YEARS:
        try:
            start, end = doy_to_date_range(doy, year)
        except ValueError:
            continue  # leap year edge case

        result = fetch_modis_snow(BBOX, start, end)
        if result is None:
            continue

        is_snow, valid = result

        if snow_count is None:
            snow_count = np.zeros_like(is_snow, dtype=np.int16)
            valid_count = np.zeros_like(is_snow, dtype=np.int16)

        # Align shapes (MODIS tiles can vary slightly)
        h = min(snow_count.shape[0], is_snow.shape[0])
        w = min(snow_count.shape[1], is_snow.shape[1])
        snow_count[:h, :w] += is_snow[:h, :w].astype(np.int16)
        valid_count[:h, :w] += valid[:h, :w].astype(np.int16)
        years_with_data += 1

    if snow_count is None or years_with_data < 5:
        log(f"  Skipping — only {years_with_data} years with data")
        return None

    # Compute frequency (0-100%)
    freq = np.where(valid_count > 0, (snow_count / valid_count * 100).astype(np.uint8), 0)
    log(f"  {years_with_data} years | Max freq: {freq.max()}% | Mean: {freq[freq>0].mean():.0f}%")

    return freq


def export_frequency(freq, doy, output_dir):
    """Export frequency raster as a WebP overlay with the same bounds as the main data."""
    west, south, east, north = BBOX
    aspect = (east - west) / (north - south)

    if aspect >= 1:
        dst_w = MAX_DIM
        dst_h = int(MAX_DIM / aspect)
    else:
        dst_h = MAX_DIM
        dst_w = int(MAX_DIM * aspect)

    # Resize the frequency array to target dimensions
    img_freq = Image.fromarray(freq)
    img_resized = img_freq.resize((dst_w, dst_h), Image.NEAREST)
    freq_resized = np.array(img_resized)

    # Color map: transparent where no snow history, orange-red gradient for frequency
    # 0% = transparent, 1-30% = faint, 30-60% = medium, 60-100% = strong
    rgba = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)

    # Use a warm orange palette for historical (distinct from current blue snow)
    mask = freq_resized > 5
    rgba[mask, 0] = 255  # R
    rgba[mask, 1] = np.clip(180 - freq_resized[mask], 80, 180).astype(np.uint8)  # G: orange to red
    rgba[mask, 2] = 50   # B
    rgba[mask, 3] = np.clip(freq_resized[mask] * 1.5 + 30, 30, 180).astype(np.uint8)  # alpha scales with freq

    img = Image.fromarray(rgba, 'RGBA')
    fname = f"doy_{doy:03d}.webp"
    img.save(output_dir / fname, 'WEBP', lossless=True)
    size_kb = os.path.getsize(output_dir / fname) // 1024
    log(f"  {fname}: {img.size} ({size_kb}KB)")
    return fname


def main():
    parser = argparse.ArgumentParser(description="Build MODIS historical snow frequency rasters")
    parser.add_argument("--doy", type=int, default=None, help="Single day-of-year to process")
    parser.add_argument("--start-doy", type=int, default=1, help="Start DOY")
    parser.add_argument("--end-doy", type=int, default=365, help="End DOY")
    parser.add_argument("--step", type=int, default=5, help="DOY step")
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR,
                        help="Where the WebPs and historical.json go (default site/data/historical)")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild periods whose WebP already exists in --out-dir (default: skip them)")
    args = parser.parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.doy:
        doys = [args.doy]
    else:
        doys = list(range(args.start_doy, args.end_doy + 1, args.step))

    # Only do snow season (Oct-Jun = DOY 274-365 + 1-181)
    snow_doys = [d for d in doys if d >= 274 or d <= 181]
    log(f"Processing {len(snow_doys)} 5-day periods across {len(YEARS)} years")

    index = {
        "bbox": BBOX,
        "bounds": {"west": BBOX[0], "south": BBOX[1], "east": BBOX[2], "north": BBOX[3]},
        "years": [YEARS[0], YEARS[-1]],
        "periods": {},
    }

    for doy in snow_doys:
        dt = datetime(2024, 1, 1) + timedelta(days=doy - 1)
        fname = f"doy_{doy:03d}.webp"
        # Resumable: a period already written in out_dir is kept as is.
        if not args.force and (out_dir / fname).exists():
            log(f"DOY {doy:03d}: already in {out_dir.name}, skipped")
        else:
            freq = build_frequency_for_doy(doy)
            if freq is None:
                continue
            fname = export_frequency(freq, doy, out_dir)
        index["periods"][str(doy)] = {
            "file": fname,
            "label": f"{dt:%b %d}",
            "month": dt.month,
            "day": dt.day,
        }

    with open(out_dir / "historical.json", 'w') as f:
        json.dump(index, f, indent=2)

    log(f"Done. {len(index['periods'])} periods in {out_dir}")


if __name__ == "__main__":
    main()
