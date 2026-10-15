#!/usr/bin/env python3
"""
Classifier test bench: raw Sentinel-2 pixels at every ground station, with
that day's measured snow depth, for every pass that has a snow map.

For each date in dates.json and each SNOTEL (and, this season, Montana
Mesonet) station in the area, reads a 5x5 window of 20 m pixels around the
station from the same L2A scenes the map used (Element 84 Earth Search,
sentinel-2-c1-l2a; windowed COG reads, a few KB each, nothing saved):

    blue, green, red, nir, swir16 (B11)   surface reflectance (scale 1e-4, offset -0.1)
    scl                                   Sen2Cor scene classification
    cloud, snow                           Sen2Cor cloud / snow probability (0-100)

plus sun elevation, the station's elevation and tree cover, the measured
depth, and the truth label used by the agreement check (>= 2 in snow,
0 in bare, otherwise not scored). Any candidate classifier can then be
scored against the stations in seconds (classifier_eval.py), without
reprocessing imagery.

Writes snowline/pipeline/data/station_pixels.json.gz:
    {"rows": [{date, station, kind, name, elev_ft, forest_pct, depth_in, truth,
               scene, sun_elev, bands: {name: 5x5 list}}], ...}

Resumable: dates already in the file are skipped unless --redo.
Default is this season only (since Oct 1); --since=2025-10-01 adds last season.

Usage:
    python snowline/pipeline/build_station_pixels.py                    # this season (~2 min)
    python snowline/pipeline/build_station_pixels.py --date=2026-10-13  # one date
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date
from pathlib import Path

import numpy as np
import requests

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
import rasterio  # noqa: E402
from rasterio.warp import transform  # noqa: E402
from rasterio.windows import Window  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.aoi import SNOWLINE  # noqa: E402

SITE = ROOT / "snowline" / "site"
DATA_10M = SITE / "data_10m"
OUT = ROOT / "snowline" / "pipeline" / "data" / "station_pixels.json.gz"
GRID = ROOT / "snowline" / "pipeline" / "data" / "terrain_grid.npz"
STAC = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a/items/"
BANDS = {"blue": 10, "green": 10, "red": 10, "nir": 10, "swir16": 20, "scl": 20, "cloud": 20, "snow": 20}
HALF = 2            # 5x5 window of 20 m pixels
SNOW_IN, BARE_IN = 2, 0


def log(msg):
    print(f"[station_pixels] {msg}", flush=True)


def stations():
    """SNOTEL (both season files) + Mesonet, in the area, with daily depth by date."""
    w, s, e, n = SNOWLINE.bbox
    out = {}
    for f in sorted((SITE / "data").glob("snotel_season*.json")):
        for st in json.loads(f.read_text()).get("stations", []):
            if not (st.get("id", "").endswith(":SNTL") and st.get("lat") and w <= st["lon"] <= e and s <= st["lat"] <= n):
                continue
            o = out.setdefault(st["id"], {"kind": "SNOTEL", "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                                          "elev_ft": st.get("elevation_ft"), "depth": {}})
            o["depth"].update({h["date"]: h["depth_in"] for h in st.get("history", []) if h.get("depth_in") is not None})
    mes = SITE / "data" / "mesonet_snow.json"
    if mes.exists():
        for st in json.loads(mes.read_text())["stations"]:
            out["mesonet:" + st["id"]] = {"kind": "Mesonet", "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                                          "elev_ft": st["elevation_ft"], "depth": {h["date"]: h["depth_in"] for h in st["history"]}}
    return out


def forest_at(lat, lon, z, meta):
    i, j = int((meta["north"] - lat) / meta["res"]), int((lon - meta["west"]) / meta["res"])
    return int(z["forest"][i, j]) if 0 <= i < z["forest"].shape[0] and 0 <= j < z["forest"].shape[1] else None


def read_scene(scene_id, pts):
    """{station: bands} for stations inside this scene's tile (5x5 at 20 m)."""
    item = requests.get(STAC + scene_id, timeout=60).json()
    assets = item.get("assets") or {}
    if "scl" not in assets:
        return {}, None
    found = {}
    with rasterio.open(assets["scl"]["href"]) as scl:
        xs, ys = transform("EPSG:4326", scl.crs, [p[2] for p in pts], [p[1] for p in pts])
        for (sid, _, _), x, y in zip(pts, xs, ys):
            r, c = scl.index(x, y)
            if HALF <= r < scl.height - HALF and HALF <= c < scl.width - HALF:
                v = scl.read(1, window=Window(c - HALF, r - HALF, 2 * HALF + 1, 2 * HALF + 1))
                if (v > 0).any():
                    found[sid] = {"rc": (r, c), "bands": {"scl": v.tolist()}}
    if not found:
        return {}, None
    for b, res in BANDS.items():
        if b == "scl" or b not in assets:
            continue
        with rasterio.open(assets[b]["href"]) as src:
            k = 20 // res
            for sid, f in found.items():
                r, c = f["rc"]
                a = src.read(1, window=Window((c - HALF) * k, (r - HALF) * k, (2 * HALF + 1) * k, (2 * HALF + 1) * k)).astype(float)
                if k > 1:
                    a = a.reshape(2 * HALF + 1, k, 2 * HALF + 1, k).mean(axis=(1, 3))
                if b in ("cloud", "snow"):
                    f["bands"][b] = a.round().astype(int).tolist()
                else:
                    f["bands"][b] = (a * 1e-4 - 0.1).round(4).tolist()
    return found, item["properties"].get("view:sun_elevation")


def do_date(d, sts, z, meta):
    meta_d = json.loads((DATA_10M / d / "snowline.json").read_text())
    pts = [(sid, s["lat"], s["lon"]) for sid, s in sts.items()]
    rows, seen = [], set()
    for sc in meta_d.get("scenes") or []:
        todo = [p for p in pts if p[0] not in seen]
        if not todo:
            break
        try:
            found, sun = read_scene(sc["id"], todo)
        except Exception as e:
            log(f"  {d} {sc['id']}: {e.__class__.__name__}: {e}")
            continue
        for sid, f in found.items():
            seen.add(sid)
            s = sts[sid]
            depth = s["depth"].get(d)
            truth = None if depth is None else "snow" if depth >= SNOW_IN else "bare" if depth <= BARE_IN else None
            rows.append({"date": d, "station": sid, "kind": s["kind"], "name": s["name"], "elev_ft": s["elev_ft"],
                         "forest_pct": forest_at(s["lat"], s["lon"], z, meta), "depth_in": depth, "truth": truth,
                         "scene": sc["id"], "sun_elev": sun, "bands": f["bands"]})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date")
    ap.add_argument("--since", help="first date (default: this season's Oct 1)")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    data = json.loads(gzip.decompress(OUT.read_bytes())) if OUT.exists() else {"rows": []}
    have = {r["date"] for r in data["rows"]}
    dates = [args.date] if args.date else json.loads((DATA_10M / "dates.json").read_text())["dates"]
    today = Date.today()
    since = args.since or f"{today.year if today.month >= 10 else today.year - 1}-10-01"
    dates = [d for d in dates if (DATA_10M / d / "snowline.json").exists() and since <= d <= today.isoformat()]
    if not args.redo:
        dates = [d for d in dates if d not in have]
    sts = stations()
    z = np.load(GRID)
    meta = json.loads(bytes(z["meta"]).decode())
    log(f"{len(sts)} stations, {len(dates)} dates to read")
    with ThreadPoolExecutor(args.workers) as ex:
        for d, rows in zip(dates, ex.map(lambda d: do_date(d, sts, z, meta), dates)):
            data["rows"] = [r for r in data["rows"] if r["date"] != d] + rows
            n = sum(r["truth"] is not None for r in rows)
            log(f"{d}: {len(rows)} stations read, {n} with a truth label")
            # Save after every date, so an interrupted run resumes.
            data["rows"].sort(key=lambda r: (r["date"], r["station"]))
            tmp = OUT.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode()))
            tmp.replace(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
