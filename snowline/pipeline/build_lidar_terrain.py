#!/usr/bin/env python3
"""
Lidar terrain shading for Snowline, from USGS 3DEP 1 m lidar elevation.

Snowline's snow pixels are ~24 m, but the lidar surface under them is
1 m. Shading that surface makes ridges, gullies, cliff bands and tree
lines readable under the snow layer, on any basemap. This script turns
the public 3DEP 1 m DEM tiles into web-map tiles:

  site/terrain/shade/{z}/{x}/{y}.webp   512 px tiles, z8–z13 (~6.7 m/px at z13)

Each tile is black with an alpha channel: transparent on flat or sunlit
ground, darker in shadow. It darkens whatever is below it and keeps the
snow layer above it bright.

Steps (each resumable):
  list     ask the USGS National Map API for every 1 m DEM tile over the AOI
  fetch    read each tile's 4 m overview (the COGs carry 2/4/8/16/32 m
           overviews) into cache/lidar/4m — ~4% of the 1 m data volume
  shade    hillshade each 4 m tile in its own UTM grid, seamless across
           neighbours → cache/lidar/shade
  tiles    reproject the shading into web-mercator tiles (newest survey
           wins where they overlap) and build the lower zooms

Newest wins: where two lidar projects overlap (e.g. the Montana statewide
collection and Yellowstone NP), the most recently flown survey is used
(year from the 3DEP project name; publication date breaks ties), so the
terrain always reflects the latest survey.

Usage:
  python snowline/pipeline/build_lidar_terrain.py list
  python snowline/pipeline/build_lidar_terrain.py fetch --workers=6
  python snowline/pipeline/build_lidar_terrain.py shade --workers=2
  python snowline/pipeline/build_lidar_terrain.py tiles
  python snowline/pipeline/build_lidar_terrain.py tiles --z=13 --only=1600,2900   # one tile, for a test
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))
from lib.aoi import SNOWLINE  # noqa: E402

CACHE = REPO_ROOT / "cache" / "lidar"
INDEX = CACHE / "index.json"
OUT = REPO_ROOT / "site" / "terrain" / "shade"
TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASET = "Digital Elevation Model (DEM) 1 meter"
OVERVIEW = 1            # index into the COG's overviews: [2, 4, 8, 16, 32] → 4 m
MAX_Z, MIN_Z = 13, 8
TILE = 512
NODATA = -999999.0

# Shading: classic 315° sun at 45° altitude, plus a softer 255° light so
# NW-facing slopes don't go flat. Flat ground shades to ~180 (= sin 45°).
SUN = [(315, 45, 0.7), (255, 50, 0.3)]
FLAT = 255 * math.sin(math.radians(45))
EXAGGERATION = 1.3      # visual z-factor
CONTRAST = 1.2          # alpha per shade level below flat
MAX_ALPHA = 160         # never fully black: it's context under the snow


def log(msg):
    print(f"[lidar] {msg}", flush=True)


# ── list ────────────────────────────────────────────────────────────────────
def cmd_list(_args):
    w, s, e, n = SNOWLINE.bbox
    items, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"datasets": DATASET, "bbox": f"{w},{s},{e},{n}",
                                    "max": 500, "offset": offset, "outputFormat": "JSON"})
        with urllib.request.urlopen(f"{TNM}?{q}", timeout=120) as r:
            page = json.load(r)
        batch = page.get("items", [])
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= page.get("total", 0):
            break
    rows = [{
        "title": i["title"],
        "url": i["downloadURL"],
        "published": i.get("publicationDate"),
        "bbox": [i["boundingBox"][k] for k in ("minX", "minY", "maxX", "maxY")],
        "bytes": i.get("sizeInBytes"),
    } for i in items if i.get("downloadURL", "").endswith(".tif")]
    CACHE.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(rows, indent=0))
    projects = {}
    for r in rows:
        p = r["url"].split("/Projects/")[1].split("/")[0]
        projects.setdefault(p, [0, r["published"]])[0] += 1
    log(f"{len(rows)} tiles, {sum(r['bytes'] or 0 for r in rows) / 1e9:.0f} GB at 1 m")
    for p, (k, d) in sorted(projects.items(), key=lambda x: -x[1][0]):
        log(f"  {p}: {k} tiles, published {d}")


# ── fetch ───────────────────────────────────────────────────────────────────
def local_path(row):
    return CACHE / "4m" / row["url"].rsplit("/", 1)[1]


def fetch_one(row):
    import rasterio
    out = local_path(row)
    if out.exists():
        return "cached"
    with rasterio.open(row["url"], OVERVIEW_LEVEL=OVERVIEW) as src:
        arr = src.read(1)
        prof = src.profile.copy()
        prof.update(width=arr.shape[1], height=arr.shape[0], transform=src.transform,
                    compress="deflate", predictor=3, tiled=True, blockxsize=512, blockysize=512)
    tmp = out.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr, 1)
    tmp.replace(out)
    return "ok"


def cmd_fetch(args):
    import os
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")
    rows = json.loads(INDEX.read_text())
    (CACHE / "4m").mkdir(parents=True, exist_ok=True)
    t0, done, failed = time.time(), 0, []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch_one, r): r for r in rows}
        for f in as_completed(futs):
            done += 1
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                failed.append(futs[f]["title"])
                log(f"  FAILED {futs[f]['title']}: {type(e).__name__}: {str(e)[:100]}")
            if done % 50 == 0:
                log(f"  {done}/{len(rows)} ({time.time() - t0:.0f}s)")
    log(f"fetched {done - len(failed)}/{len(rows)}; re-run to retry failures")
    return 1 if failed else 0


# ── tiles ───────────────────────────────────────────────────────────────────
def survey_year(row):
    """When the lidar was flown, from the 3DEP project name: an explicit year
    (MT_Statewide_Phase3_2021_B21 → 2021) or the work-unit suffix
    (MT_Statewide_Phase5_D23 → 2023). Publication dates lag collection by
    years and aren't in collection order, so they only break ties."""
    import re
    proj = row["url"].split("/Projects/")[1].split("/")[0]
    m = re.search(r"_(20\d\d)(?:_|$)", proj) or re.search(r"(?:^|_)(19\d\d|20\d\d)$", proj)
    if m:
        return int(m.group(1))
    m = re.search(r"_[A-Z](\d\d)$", proj)
    return 2000 + int(m.group(1)) if m else 0


def merc_bounds(z, x, y):
    n = 2 ** z
    def lon(xx): return xx / n * 360 - 180
    def lat(yy): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))
    return lon(x), lat(y + 1), lon(x + 1), lat(y)


def tile_range(z):
    w, s, e, n = SNOWLINE.bbox
    def tx(lon): return int((lon + 180) / 360 * 2 ** z)
    def ty(lat):
        r = math.radians(lat)
        return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z)
    return range(tx(w), tx(e) + 1), range(ty(n), ty(s) + 1)


def shade(dem, valid, res_m):
    """Horn-gradient hillshade of a DEM array; NaN where invalid."""
    import numpy as np
    z = np.where(valid, dem, np.nan) * EXAGGERATION
    p = np.pad(z, 1, mode="edge")
    dzdx = ((p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])) / (8 * res_m)
    dzdy = ((p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])) / (8 * res_m)
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(dzdy, -dzdx)
    out = np.zeros_like(z)
    for az, alt, wgt in SUN:
        zen = math.radians(90 - alt)
        azr = math.radians(360 - az + 90)
        out += wgt * 255 * (math.cos(zen) * np.cos(slope) + math.sin(zen) * np.sin(slope) * np.cos(azr - aspect))
    return np.clip(out, 0, 255)


def shade_path(row):
    return CACHE / "shade" / row["url"].rsplit("/", 1)[1]


def shade_one(row, rows_sorted):
    """Shade one 4 m lidar tile in its own UTM grid. The DEM is read with a
    few pixels of margin from neighbouring tiles (newest survey first) so
    shading is seamless across tile edges. Shading before reprojecting
    matters: slopes computed after resampling pick up aliasing stripes."""
    import numpy as np
    import rasterio
    from rasterio.merge import merge
    out = shade_path(row)
    if out.exists():
        return
    with rasterio.open(local_path(row)) as src:
        prof, crs, res = src.profile.copy(), src.crs, src.res[0]
        l, b_, r_, t = src.bounds
    m = 4 * res
    w, s, e, n = row["bbox"]
    neigh = [x for x in rows_sorted
             if x["bbox"][0] < e + 0.01 and x["bbox"][2] > w - 0.01 and x["bbox"][1] < n + 0.01 and x["bbox"][3] > s - 0.01]
    dsets = []
    for x in neigh:
        d = rasterio.open(local_path(x))
        if d.crs == crs and abs(d.res[0] - res) < 1e-6:
            dsets.append(d)
        else:
            d.close()
    dem, tf = merge(dsets, bounds=(l - m, b_ - m, r_ + m, t + m), res=res, nodata=NODATA, method="first")
    for d in dsets:
        d.close()
    dem = dem[0]
    valid = dem > -1000
    hs = shade(dem, valid, res)
    alpha = np.clip((FLAT - np.nan_to_num(hs, nan=FLAT)) * CONTRAST, 0, MAX_ALPHA).astype(np.uint8)
    alpha[~valid] = 255
    alpha = alpha[4:-4, 4:-4]
    prof.update(dtype="uint8", nodata=255, predictor=2, compress="deflate")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(alpha, 1)
    tmp.replace(out)


def cmd_shade(args):
    rows = [r for r in json.loads(INDEX.read_text()) if local_path(r).exists()]
    rows.sort(key=lambda r: (survey_year(r), r["published"] or ""), reverse=True)
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        for i, _ in enumerate(ex.map(lambda r: shade_one(r, rows), rows), 1):
            if i % 50 == 0:
                log(f"  {i}/{len(rows)} ({time.time() - t0:.0f}s)")
    log(f"shaded {len(rows)} tiles")


def render_z13(x, y, sources, rasterio, np):
    """Reproject the pre-shaded lidar into one z13 tile, newest survey first."""
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    w, s, e, n = merc_bounds(MAX_Z, x, y)
    pad = 0
    # Tile bounds in EPSG:3857 metres, padded by `pad` pixels for seamless edges.
    R = 6378137.0
    mx0, mx1 = math.radians(w) * R, math.radians(e) * R
    my0 = math.log(math.tan(math.pi / 4 + math.radians(s) / 2)) * R
    my1 = math.log(math.tan(math.pi / 4 + math.radians(n) / 2)) * R
    px = (mx1 - mx0) / TILE
    size = TILE + 2 * pad
    tf = from_bounds(mx0 - pad * px, my0 - pad * px, mx1 + pad * px, my1 + pad * px, size, size)
    alpha = np.full((size, size), 255, dtype=np.uint8)  # 255 = not yet filled
    for row in sources:  # newest first: only fill what is still empty
        if not shade_path(row).exists():
            continue
        with rasterio.open(shade_path(row)) as src, \
                WarpedVRT(src, crs="EPSG:3857", transform=tf, width=size, height=size,
                          resampling=Resampling.average, src_nodata=255, nodata=255) as vrt:
            a = vrt.read(1)
        fill = (alpha == 255) & (a != 255)
        alpha[fill] = a[fill]
        if not (alpha == 255).any():
            break
    if (alpha == 255).all():
        return None
    alpha[alpha == 255] = 0
    return alpha


def save(alpha, path, np):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros(alpha.shape + (4,), np.uint8)
    rgba[..., 3] = alpha
    Image.fromarray(rgba, "RGBA").save(path, "WEBP", quality=72, method=4)


def cmd_tiles(args):
    import numpy as np
    import rasterio
    from PIL import Image
    rows = [r for r in json.loads(INDEX.read_text()) if local_path(r).exists()]
    rows.sort(key=lambda r: (survey_year(r), r["published"] or ""), reverse=True)  # newest survey first
    xs, ys = tile_range(MAX_Z)
    jobs = [(x, y) for x in xs for y in ys]
    if args.only:
        ox, oy = map(int, args.only.split(","))
        jobs = [(ox, oy)]
    t0, made = time.time(), 0

    def work(xy):
        x, y = xy
        path = OUT / str(MAX_Z) / str(x) / f"{y}.webp"
        if path.exists() and not args.force:
            return True
        w, s, e, n = merc_bounds(MAX_Z, x, y)
        srcs = [r for r in rows if r["bbox"][0] < e and r["bbox"][2] > w and r["bbox"][1] < n and r["bbox"][3] > s]
        if not srcs:
            return False
        a = render_z13(x, y, srcs, rasterio, np)
        if a is None:
            return False
        save(a, path, np)
        return True

    with ThreadPoolExecutor(args.workers) as ex:
        for i, ok in enumerate(ex.map(work, jobs), 1):
            made += bool(ok)
            if i % 200 == 0:
                log(f"  z{MAX_Z}: {i}/{len(jobs)} ({time.time() - t0:.0f}s)")
    log(f"z{MAX_Z}: {made} tiles")
    if args.only:
        return 0

    # Lower zooms: average 2x2 children into each parent (alpha only).
    for z in range(MAX_Z - 1, MIN_Z - 1, -1):
        xs, ys = tile_range(z)
        n_out = 0
        for x in xs:
            for y in ys:
                quad = np.zeros((TILE * 2, TILE * 2), np.float32)
                any_child = False
                for dx in (0, 1):
                    for dy in (0, 1):
                        p = OUT / str(z + 1) / str(2 * x + dx) / f"{2 * y + dy}.webp"
                        if p.exists():
                            any_child = True
                            quad[dy * TILE:(dy + 1) * TILE, dx * TILE:(dx + 1) * TILE] = \
                                np.asarray(Image.open(p).getchannel("A"), np.float32)
                if not any_child:
                    continue
                parent = quad.reshape(TILE, 2, TILE, 2).mean(axis=(1, 3))
                save(np.clip(parent, 0, 255).astype(np.uint8), OUT / str(z) / str(x) / f"{y}.webp", np)
                n_out += 1
        log(f"z{z}: {n_out} tiles")

    files = list(OUT.rglob("*.webp"))
    (OUT.parent / "shade.json").write_text(json.dumps({
        "tiles": "terrain/shade/{z}/{x}/{y}.webp", "tileSize": TILE, "minzoom": MIN_Z, "maxzoom": MAX_Z,
        "bounds": list(SNOWLINE.bbox),
        "source": "USGS 3D Elevation Program (3DEP) 1 m lidar DEM, read at 4 m; newest survey wins where they overlap",
        "projects": sorted({r["url"].split("/Projects/")[1].split("/")[0] for r in rows}),
        "tile_count": len(files), "bytes": sum(f.stat().st_size for f in files),
    }, indent=1))
    log(f"done: {len(files)} tiles, {sum(f.stat().st_size for f in files) / 1e6:.0f} MB ({time.time() - t0:.0f}s)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sh = sub.add_parser("shade"); sh.add_argument("--workers", type=int, default=2)
    f = sub.add_parser("fetch"); f.add_argument("--workers", type=int, default=4)
    t = sub.add_parser("tiles"); t.add_argument("--workers", type=int, default=2)
    t.add_argument("--only", help="x,y of one z13 tile (test)"); t.add_argument("--force", action="store_true")
    args = ap.parse_args()
    return {"list": cmd_list, "fetch": cmd_fetch, "shade": cmd_shade, "tiles": cmd_tiles}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
