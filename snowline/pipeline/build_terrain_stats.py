#!/usr/bin/env python3
"""
Snow cover by elevation and aspect, for each snow map.

Every pixel the satellite saw clearly (snow or bare ground; cloud and no-data
are left out) is looked up in the static terrain grid (build_terrain_grid.py:
elevation and slope direction on a 0.001-degree grid) and counted into
100 m elevation bands x 9 aspect classes (flat, N, NE, E, SE, S, SW, W, NW).
From the counts:

    snowline_m   the elevation above which every band is at least half
                 snow-covered (linear between band centres); null when snow
                 covers every band seen, or the highest band is mostly bare
    by_aspect    the same, for each of the 8 slope directions

Forest canopy hides snow from the satellite (it sees the treetops), so
forested slopes read as far less snowy than they are: on 2026-10-13 snow
cover fell to ~50 % between 2,000 and 2,600 m and rose to 100 % above
treeline. Counts are therefore split into open ground (grid cells under
OPEN_MAX % tree cover) and forested; the snowlines use open ground only.

Bands with fewer than MIN_BAND clear pixels (and band x aspect cells with
fewer than MIN_CELL) are not used for these lines; the raw counts are kept so
the site can show coverage.

The map's classes are read back from the published snow WebPs (alpha: 200
snow, 0 ground, 160/100 cloud, 120/60 no data), exactly what a visitor sees.

    change       snow gained and lost since the previous pass that saw the
                 same ground: both passes are summarised onto the terrain
                 grid (a cell is snow if at least half its clear pixels
                 are), and only cells clear on both dates (open ground)
                 are compared; counted by elevation band x aspect, with
                 the gap in days. An observation, not a model.

Writes site/data/terrain_stats.json: {"dates": {date: {...}}, ...}.

Usage:
    python snowline/pipeline/build_terrain_stats.py --date=2026-10-13
    python snowline/pipeline/build_terrain_stats.py --all            # every date with WebPs on disk
    python snowline/pipeline/build_terrain_stats.py --missing --fetch   # dates not summarised yet (CI)
    python snowline/pipeline/build_terrain_stats.py --date=2026-10-13 --fetch   # read WebPs from the live site
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_10M = REPO_ROOT / "site" / "data_10m"
GRID = REPO_ROOT / "pipeline" / "data" / "terrain_grid.npz"
OUT = REPO_ROOT / "site" / "data" / "terrain_stats.json"
LIVE = "https://line.itogeospatial.com/snow/api/tile"

BAND_M = 100
BAND_LO, BAND_HI = 1000, 4000          # metres; the area runs 1,037-3,853 m
NB = (BAND_HI - BAND_LO) // BAND_M
ASPECTS = ["flat", "N", "NE", "E", "SE", "S", "SW", "W", "NW"]
MIN_BAND = 2000    # clear pixels (~1.2 km2) for a band to count toward a snowline
MIN_CELL = 300     # clear pixels for a band x aspect cell
OPEN_MAX = 30      # % tree cover at or below which a cell counts as open ground
CHANGE_MAX_DAYS = 12    # look back at most this far for the previous pass
CHANGE_MIN_CELLS = 20000  # cells clear on both dates (~170 km2) to report a change


def log(msg):
    print(f"[terrain_stats] {msg}", flush=True)


def load_grid():
    z = np.load(GRID)
    meta = json.loads(bytes(z["meta"]).decode())
    # Fold forest into the aspect code: 0-8 open ground, 9-17 forested.
    code = z["aspect"] + np.where(z["forest"] > OPEN_MAX, 9, 0).astype(np.uint8)
    return z["elev_10m"], code, meta


def snow_images(date, fetch):
    """(alpha array, bounds) for each snow image of a date."""
    meta = json.loads((DATA_10M / date / "snowline.json").read_text())
    files = [(c["snow_file"], c["bounds"]) for c in meta.get("chunks") or []]
    files += [(t["file"], t["bounds"]) for t in meta.get("tiles") or [] if t.get("file")]
    for fname, b in files:
        p = DATA_10M / date / fname
        if p.exists():
            img = Image.open(p)
        elif fetch:
            r = requests.get(f"{LIVE}/{date}/{fname}", timeout=120)
            if r.status_code != 200:
                log(f"  {date}/{fname}: HTTP {r.status_code}")
                continue
            img = Image.open(io.BytesIO(r.content))
        else:
            continue
        yield np.asarray(img.getchannel("A")), b


def count(date, elev10, aspect, meta, fetch):
    snow = np.zeros(NB * 18, dtype=np.int64)
    clear = np.zeros(NB * 18, dtype=np.int64)
    seen = 0
    for a, b in snow_images(date, fetch):
        seen += 1
        h, w = a.shape
        lon = b["west"] + (np.arange(w) + 0.5) * (b["east"] - b["west"]) / w
        lat = b["north"] - (np.arange(h) + 0.5) * (b["north"] - b["south"]) / h
        gj = np.floor((lon - meta["west"]) / meta["res"]).astype(np.int64)
        gi = np.floor((meta["north"] - lat) / meta["res"]).astype(np.int64)
        okj = (gj >= 0) & (gj < elev10.shape[1])
        oki = (gi >= 0) & (gi < elev10.shape[0])
        a = a[oki][:, okj]
        gi, gj = gi[oki], gj[okj]
        is_snow = a == 200
        is_clear = is_snow | (a == 0)
        e = elev10[gi[:, None], gj[None, :]].astype(np.int64) * 10
        band = np.clip((e - BAND_LO) // BAND_M, 0, NB - 1)
        key = band * 18 + aspect[gi[:, None], gj[None, :]]
        snow += np.bincount(key[is_snow], minlength=NB * 18)
        clear += np.bincount(key[is_clear], minlength=NB * 18)
    return snow.reshape(NB, 2, 9), clear.reshape(NB, 2, 9), seen


def cell_counts(date, shape, meta, fetch):
    """Per terrain-grid cell: (snow pixels, clear pixels), flattened; None if no images."""
    n = shape[0] * shape[1]
    snow = np.zeros(n, dtype=np.int32)
    clear = np.zeros(n, dtype=np.int32)
    seen = 0
    for a, b in snow_images(date, fetch):
        seen += 1
        h, w = a.shape
        lon = b["west"] + (np.arange(w) + 0.5) * (b["east"] - b["west"]) / w
        lat = b["north"] - (np.arange(h) + 0.5) * (b["north"] - b["south"]) / h
        gj = np.floor((lon - meta["west"]) / meta["res"]).astype(np.int64)
        gi = np.floor((meta["north"] - lat) / meta["res"]).astype(np.int64)
        okj, oki = (gj >= 0) & (gj < shape[1]), (gi >= 0) & (gi < shape[0])
        a, gi, gj = a[oki][:, okj], gi[oki], gj[okj]
        idx = gi[:, None] * shape[1] + gj[None, :]
        is_snow = a == 200
        snow += np.bincount(idx[is_snow], minlength=n).astype(np.int32)
        clear += np.bincount(idx[is_snow | (a == 0)], minlength=n).astype(np.int32)
    return (snow, clear) if seen else None


def change_since(date, prev_dates, elev10, code, meta, fetch):
    """Snow gained / lost on open ground since the nearest earlier pass that saw it."""
    shape = elev10.shape
    now = cell_counts(date, shape, meta, fetch)
    if now is None:
        return None
    band = np.clip((elev10.ravel().astype(np.int64) * 10 - BAND_LO) // BAND_M, 0, NB - 1)
    asp = code.ravel()
    open_ = asp < 9
    for p in reversed(prev_dates):
        gap = (datetime.fromisoformat(date) - datetime.fromisoformat(p)).days
        if gap > CHANGE_MAX_DAYS:
            break
        before = cell_counts(p, shape, meta, fetch)
        if before is None:
            continue
        # A cell is judged when at least 4 of its pixels were clear on each date.
        both = open_ & (now[1] >= 4) & (before[1] >= 4)
        if both.sum() < CHANGE_MIN_CELLS:
            continue
        s_now = now[0] * 2 >= now[1]
        s_before = before[0] * 2 >= before[1]
        key = band * 9 + asp
        gained = np.bincount(key[both & s_now & ~s_before], minlength=NB * 9).reshape(NB, 9)
        lost = np.bincount(key[both & ~s_now & s_before], minlength=NB * 9).reshape(NB, 9)
        compared = np.bincount(key[both], minlength=NB * 9).reshape(NB, 9)
        return {"from": p, "days": gap, "cell_km2": round(meta["res"] ** 2 * 111.32 * 110.574 * np.cos(np.radians(45.5)), 5),
                "gained": gained.tolist(), "lost": lost.tolist(), "compared": compared.tolist(),
                "gained_cells": int(gained.sum()), "lost_cells": int(lost.sum()), "compared_cells": int(compared.sum())}
    return None


def snowline(snow, clear, min_n):
    """Elevation (m) above which every band is at least half snow-covered.

    Scans down from the top for the highest band under 50 % and interpolates
    to the band above it, so a stray patch of valley snow doesn't set the
    line. None if every band seen is mostly snow (snow below the lowest band)
    or the top band is mostly bare (no snowline in the area).
    """
    rows = [(BAND_LO + (i + 0.5) * BAND_M, snow[i] / clear[i]) for i in range(len(clear)) if clear[i] >= min_n]
    if len(rows) < 3:
        return None
    bare = [k for k, (_, f) in enumerate(rows) if f < 0.5]
    if not bare or bare[-1] == len(rows) - 1:
        return None
    (z0, f0), (z1, f1) = rows[bare[-1]], rows[bare[-1] + 1]
    return round(z0 + (0.5 - f0) / (f1 - f0) * (z1 - z0))


def summarise(snow, clear):
    """snow/clear: [band][0 open, 1 forested][aspect]."""
    so, co = snow[:, 0], clear[:, 0]
    used = np.nonzero(clear.sum((1, 2)))[0]
    lo, hi = (used[0], used[-1] + 1) if used.size else (0, 0)   # trim empty bands
    return {
        "bands_m": [BAND_LO + i * BAND_M for i in range(lo, hi)],
        "aspects": ASPECTS,
        "snow_open": so[lo:hi].tolist(),
        "clear_open": co[lo:hi].tolist(),
        "snow_forest": snow[lo:hi, 1].sum(1).tolist(),
        "clear_forest": clear[lo:hi, 1].sum(1).tolist(),
        "snowline_m": snowline(so.sum(1), co.sum(1), MIN_BAND),
        "by_aspect": {ASPECTS[k]: snowline(so[:, k], co[:, k], MIN_CELL) for k in range(1, 9)},
        "clear_px": int(clear.sum()),
        "snow_px": int(snow.sum()),
        "open_clear_px": int(co.sum()),
        "open_snow_px": int(so.sum()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--missing", action="store_true", help="every listed date not in the output yet")
    ap.add_argument("--fetch", action="store_true", help="read missing WebPs from the live site")
    args = ap.parse_args()
    if not (args.date or args.all or args.missing):
        ap.error("--date, --all or --missing")
    elev10, aspect, meta = load_grid()
    data = json.loads(OUT.read_text()) if OUT.exists() else {"dates": {}}
    if args.all or args.missing:
        dates = json.loads((DATA_10M / "dates.json").read_text())["dates"]
        dates = [d for d in dates if (DATA_10M / d / "snowline.json").exists()]
        if args.missing:
            dates = [d for d in dates if d not in data["dates"]]
        log(f"{len(dates)} dates to summarise")
    else:
        dates = [args.date]
    failed = 0
    for d in dates:
        if not (DATA_10M / d / "snowline.json").exists():
            log(f"{d}: no snowline.json")
            failed += 1
            continue
        snow, clear, seen = count(d, elev10, aspect, meta, args.fetch)
        if not seen:
            log(f"{d}: no snow images {'found' if args.fetch else 'on disk (use --fetch)'}")
            if not args.all:
                failed += 1
            continue
        data["dates"][d] = summarise(snow, clear)
        s = data["dates"][d]
        listed = json.loads((DATA_10M / "dates.json").read_text())["dates"]
        s["change"] = change_since(d, [x for x in listed if x < d], elev10, aspect, meta, args.fetch)
        if s["change"]:
            c = s["change"]
            log(f"  since {c['from']} ({c['days']} d): gained {c['gained_cells']:,} cells, lost {c['lost_cells']:,} of {c['compared_cells']:,}")
        log(f"{d}: {s['clear_px']:,} clear px, snow {100 * s['snow_px'] / max(1, s['clear_px']):.0f}%, "
            f"snowline {s['snowline_m']} m, by aspect {s['by_aspect']}")
    data["dates"] = dict(sorted(data["dates"].items()))
    data.update({"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "band_m": BAND_M, "min_band_px": MIN_BAND, "min_cell_px": MIN_CELL, "open_max_tree_pct": OPEN_MAX,
                 "terrain": meta["source"], "aspect_flat_deg": meta["flat_deg"]})
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(OUT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
