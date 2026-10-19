#!/usr/bin/env python3
"""
Static terrain grid for Snowline's elevation and aspect statistics.

One fixed 0.001-degree grid (about 80 m east-west by 111 m north-south)
over the union of the current and previous mapped areas, holding for each
cell:
    elev_10m int16   mean elevation in tens of metres (Copernicus GLO-30 DEM)
    aspect   uint8   0 = flat (slope < 5 deg), 1..8 = N, NE, E, SE, S, SW, W, NW
                     (45-degree sectors centred on each compass point)
    forest   uint8   % of the cell that is tree cover (ESA WorldCover 2021,
                     class 10), read at its 4x overview (~40 m); the
                     satellite sees canopy, not the snow under it

build_terrain_stats.py looks every snow-map pixel up in this grid (by its
lon/lat), so the snow grid and this grid don't have to line up.

Source: Copernicus DEM GLO-30 (public COGs on AWS, copernicus-dem-30m),
read at its 2x overview (~60 m), averaged onto the grid. Licence: free use
with attribution ("produced using Copernicus WorldDEM-30 (c) DLR e.V.
2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under
COPERNICUS by the European Union and ESA; all rights reserved").

WorldCover: ESA WorldCover 10 m 2021 v200 (CC BY 4.0), public COGs on AWS.

About 16 windowed overview reads (tens of MB in all); run once, and again only
if the area grows. Output (committed, about 5 MB):
    snowline/pipeline/data/terrain_grid.npz

Also writes the grid as an image for the terrain page's map, so a click on
a slope direction or elevation band can light up every matching place:
    snowline/site/data/terrain_classes.webp   lossless; R = 100 m elevation
        band from 1,000 m (0-29), G = aspect (0 flat, 1-8 N..NW),
        B = range id << 4 | tree cover in tens of % (0-10), A = 255.
        Range: the GNFAC avalanche forecast zone the cell falls in
        (site/data/gnfac_zones.geojson, id 1-7); 0 = outside every zone. Rows are spaced evenly in
        Web Mercator (resampled from the lat/lon grid) so it can be laid on
        the map as one image without north-south drift.
    snowline/site/data/terrain_classes.json   corners + encoding

Usage:
    python snowline/pipeline/build_terrain_grid.py
    python snowline/pipeline/build_terrain_grid.py --image   # only redo the image from the saved grid
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "snowline" / "pipeline" / "data" / "terrain_grid.npz"
RES = 0.001
# Union of the current box (lib/aoi.py) and the one used through 2026-10-13
# (-112.2, 44.9, -109.0, 46.5), so every stored date can be summarised.
WEST, SOUTH, EAST, NORTH = -112.6, 44.55, -109.0, 46.5
URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
       "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM/"
       "Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM.tif")
FLAT_DEG = 5.0
WC_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
          "ESA_WorldCover_10m_2021_v200_N{lat:02d}W{lon:03d}_Map.tif")


def log(msg):
    print(f"[terrain_grid] {msg}", flush=True)


def read_dem():
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from rasterio.transform import from_origin

    w = round((EAST - WEST) / RES)
    h = round((NORTH - SOUTH) / RES)
    dst = from_origin(WEST, NORTH, RES, RES)
    total = np.zeros((h, w), dtype=np.float64)
    count = np.zeros((h, w), dtype=np.float64)
    for lat in range(math.floor(SOUTH), math.ceil(NORTH)):
        for lon in range(math.floor(-EAST), math.ceil(-WEST) + 1):   # W lon of each 1x1 tile's west edge
            url = URL.format(lat=lat, lon=lon)
            try:
                src = rasterio.open(url, overview_level=0)   # 2x overview, ~60 m
            except Exception as e:
                log(f"  N{lat} W{lon}: not read ({e.__class__.__name__})")
                continue
            with src, WarpedVRT(src, crs="EPSG:4326", transform=dst, width=w, height=h,
                                resampling=Resampling.average, nodata=-32768) as vrt:
                a = vrt.read(1).astype(np.float64)
            ok = a > -1000
            total[ok] += a[ok]
            count[ok] += 1
            log(f"  N{lat} W{lon}: {ok.sum():,} cells")
    elev = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return elev


def read_forest():
    """% tree cover per grid cell: WorldCover class 10, sampled 4x4 per cell."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from rasterio.transform import from_origin

    k = 4
    w, h = round((EAST - WEST) / RES), round((NORTH - SOUTH) / RES)
    dst = from_origin(WEST, NORTH, RES / k, RES / k)
    trees = np.zeros((h * k, w * k), dtype=bool)
    seen = np.zeros((h * k, w * k), dtype=bool)
    # 3x3-degree tiles named by their south-west corner.
    for lat in range(math.floor(SOUTH / 3) * 3, math.ceil(NORTH / 3) * 3, 3):
        for lon in range(math.floor(-EAST / 3) * 3 + 3, math.ceil(-WEST / 3) * 3 + 1, 3):
            url = WC_URL.format(lat=lat, lon=lon)
            try:
                src = rasterio.open(url, overview_level=1)   # 4x overview, ~40 m
            except Exception as e:
                log(f"  WorldCover N{lat} W{lon}: not read ({e.__class__.__name__})")
                continue
            with src, WarpedVRT(src, crs="EPSG:4326", transform=dst, width=w * k, height=h * k,
                                resampling=Resampling.nearest, nodata=0) as vrt:
                a = vrt.read(1)
            trees |= a == 10
            seen |= a > 0
            log(f"  WorldCover N{lat} W{lon}: {(a > 0).sum():,} samples")
    if seen.mean() < 0.99:
        raise RuntimeError(f"WorldCover covers only {seen.mean() * 100:.1f}% of the grid")
    return (trees.reshape(h, k, w, k).mean(axis=(1, 3)) * 100).round().astype(np.uint8)


def slope_aspect(elev):
    # Metric spacing of a 0.001-degree cell at each row's latitude.
    lats = NORTH - (np.arange(elev.shape[0]) + 0.5) * RES
    dy = RES * 110_574.0
    dx = (RES * 111_320.0 * np.cos(np.radians(lats)))[:, None]
    gy, gx = np.gradient(elev)          # per cell; rows run north -> south
    dzdx = gx / dx                      # + = rising to the east
    dzdn = -gy / dy                     # + = rising to the north
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdn)))
    # Aspect = the compass direction the slope faces (downhill), 0 = north.
    asp = (np.degrees(np.arctan2(-dzdx, -dzdn)) + 360.0) % 360.0
    sector = (np.floor((asp + 22.5) / 45.0) % 8 + 1).astype(np.uint8)
    sector[~(slope >= FLAT_DEG)] = 0
    return slope, sector


IMG = ROOT / "snowline" / "site" / "data" / "terrain_classes.webp"
ZONES = ROOT / "snowline" / "site" / "data" / "gnfac_zones.geojson"


def range_grid(shape, elev10=None):
    """Zone id per grid cell (GNFAC forecast zones; 0 = outside), and the names."""
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    fc = json.loads(ZONES.read_text())["features"]
    rid = rasterize([(f["geometry"], f["properties"]["id"]) for f in fc], out_shape=shape,
                    transform=from_origin(WEST, NORTH, RES, RES), fill=0, dtype="uint8")
    names = [f["properties"]["name"] for f in sorted(fc, key=lambda f: f["properties"]["id"])]
    return rid, names


def write_image():
    from PIL import Image
    z = np.load(OUT)
    elev10, aspect, forest = z["elev_10m"], z["aspect"], z["forest"]
    h, w = elev10.shape
    rid, range_names = range_grid((h, w), elev10)
    merc = lambda lat: np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    y0, y1 = merc(NORTH), merc(SOUTH)
    rows = round(h * (y0 - y1) / np.radians(NORTH - SOUTH))   # keep the cell aspect ratio
    ys = y0 + (np.arange(rows) + 0.5) / rows * (y1 - y0)
    lat = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    src = np.clip(((NORTH - lat) / RES).astype(int), 0, h - 1)   # nearest lat/lon row
    band = np.clip((elev10[src].astype(int) * 10 - 1000) // 100, 0, 29).astype(np.uint8)
    packed = (rid[src] << 4) | np.minimum(forest[src] // 10, 10).astype(np.uint8)
    rgba = np.dstack([band, aspect[src], packed, np.full(band.shape, 255, np.uint8)])
    tmp = IMG.with_suffix(".tmp.webp")
    Image.fromarray(rgba, "RGBA").save(tmp, "WEBP", lossless=True, quality=100, method=6)
    tmp.replace(IMG)
    IMG.with_suffix(".json").write_text(json.dumps({
        "coordinates": [[WEST, NORTH], [EAST, NORTH], [EAST, SOUTH], [WEST, SOUTH]],
        "width": w, "height": rows, "band_m": 100, "band_lo_m": 1000,
        "aspects": ["flat", "N", "NE", "E", "SE", "S", "SW", "W", "NW"],
        "ranges": [""] + range_names, "range_source": "GNFAC forecast zones (site/data/gnfac_zones.geojson)",
        "encoding": "R band (0 = 1,000-1,100 m), G aspect, B = zone id << 4 | tree cover / 10, rows even in Web Mercator",
    }, indent=1))
    log(f"wrote {IMG.relative_to(ROOT)} ({IMG.stat().st_size / 1e6:.1f} MB, {w}x{rows})")


def main():
    if "--image" in sys.argv:
        write_image()
        return 0
    elev = read_dem()
    missing = np.isnan(elev).mean() * 100
    log(f"grid {elev.shape[1]}x{elev.shape[0]}, {missing:.2f}% without DEM")
    if missing > 1:
        log("ERROR: more than 1% of the grid has no elevation; not writing")
        return 1
    slope, sector = slope_aspect(np.nan_to_num(elev, nan=float(np.nanmean(elev))))
    forest = read_forest()
    log(f"forest: {(forest >= 50).mean() * 100:.0f}% of cells at least half tree cover")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, elev_10m=(elev / 10).round().astype(np.int16), aspect=sector, forest=forest,
                        meta=np.frombuffer(json.dumps({
                            "west": WEST, "south": SOUTH, "east": EAST, "north": NORTH, "res": RES,
                            "aspect": ["flat", "N", "NE", "E", "SE", "S", "SW", "W", "NW"], "flat_deg": FLAT_DEG,
                            "source": "Copernicus DEM GLO-30, 2x overview, averaged",
                            "forest_source": "ESA WorldCover 2021 v200 class 10, 4x overview"}).encode(), dtype=np.uint8))
    tmp.replace(OUT)
    e = elev[~np.isnan(elev)]
    log(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB); "
        f"elevation {e.min():.0f}-{e.max():.0f} m; flat {(sector == 0).mean() * 100:.0f}%")
    write_image()
    return 0


if __name__ == "__main__":
    sys.exit(main())
