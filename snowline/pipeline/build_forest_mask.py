#!/usr/bin/env python3
"""
Build a forest canopy mask from ESA WorldCover 2021 (10 m) land cover.
Outputs a WebP overlay showing forested areas where NDSI snow detection
is unreliable due to canopy cover.

Reads ESA WorldCover from Microsoft Planetary Computer; class 10 = tree cover.
Needs requirements-assets.txt (pystac-client, planetary-computer).

Usage:
    python pipeline/build_forest_mask.py

Output:
    site/data/forest_mask.webp
    site/data/forest_mask.json  (bounds metadata)
"""

import json
import os
from pathlib import Path

import numpy as np
import pystac_client
import planetary_computer
import rasterio
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from rasterio.merge import merge
from rasterio.io import MemoryFile
from PIL import Image

BBOX = [-112.2, 45.0, -110.5, 46.2]
OUTPUT_DIR = Path(__file__).parent.parent / "site" / "data"
MAX_DIM = 4000  # 30m source, 4000px is ~33m — near native


def log(msg):
    print(f"[forest] {msg}", flush=True)


def main():
    log("Searching for ESA WorldCover on Planetary Computer...")

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )

    # Search for ESA WorldCover (10m land cover)
    search = catalog.search(
        collections=["esa-worldcover"],
        bbox=BBOX,
        max_items=10,
    )
    items = list(search.items())

    if not items:
        log("ERROR: No ESA WorldCover data found")
        return

    item = items[0]
    log(f"Using: {item.id} ({len(items)} tiles)")

    # May need to mosaic multiple tiles
    all_signed = [planetary_computer.sign(i) for i in items]

    href = all_signed[0].assets["map"].href
    log(f"Reading land cover from {href[:80]}...")

    # Read and mosaic tiles
    datasets = []
    for s in all_signed:
        datasets.append(rasterio.open(s.assets["map"].href))

    if len(datasets) == 1:
        src = datasets[0]
        bbox_proj = transform_bounds(CRS.from_epsg(4326), src.crs, *BBOX)
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
        data = mosaic_arr[0]

    log(f"WorldCover: {data.shape}, unique values: {np.unique(data)[:15]}")

    # ESA WorldCover classes: 10=Tree cover
    forest = (data == 10).astype(np.uint8)
    forest_pct = np.sum(forest) / forest.size * 100
    log(f"Forest coverage: {forest_pct:.1f}%")

    # Reproject to 4326 with exact bbox bounds
    west, south, east, north = BBOX
    dst_crs = CRS.from_epsg(4326)
    aspect = (east - west) / (north - south)
    if aspect >= 1:
        dst_w = MAX_DIM
        dst_h = int(MAX_DIM / aspect)
    else:
        dst_h = MAX_DIM
        dst_w = int(MAX_DIM * aspect)

    dst_tf = from_bounds(west, south, east, north, dst_w, dst_h)

    forest_4326 = np.empty((dst_h, dst_w), dtype=np.uint8)
    reproject(forest, forest_4326, src_transform=tf, src_crs=crs,
              dst_transform=dst_tf, dst_crs=dst_crs, resampling=Resampling.nearest)

    # Create RGBA overlay — subtle green hatching for forest
    rgba = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    forest_mask = forest_4326 == 1

    # Diagonal stripe pattern to indicate "unreliable data area"
    for y in range(dst_h):
        for x in range(dst_w):
            if forest_mask[y, x] and (y + x) % 8 < 3:
                rgba[y, x] = [40, 80, 40, 60]  # dark green stripes, very subtle

    img = Image.fromarray(rgba, 'RGBA')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT_DIR / 'forest_mask.webp', 'WEBP', lossless=True)
    size_kb = os.path.getsize(OUTPUT_DIR / 'forest_mask.webp') // 1024
    log(f"forest_mask.webp: {img.size} ({size_kb}KB)")

    meta = {
        'bounds': {'west': west, 'south': south, 'east': east, 'north': north},
        'forest_pct': round(forest_pct, 1),
        'source': 'ESA WorldCover 2021 (10m)',
    }
    with open(OUTPUT_DIR / 'forest_mask.json', 'w') as f:
        json.dump(meta, f, indent=2)

    log("Done.")


if __name__ == "__main__":
    main()
