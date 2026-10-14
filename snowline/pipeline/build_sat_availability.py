#!/usr/bin/env python3
"""
Build the satellite pass tables from the S2 STAC GeoParquet index.

Metadata only — no pixels are downloaded. One DuckDB query against the
Taylor Geospatial / TGE Labs mirror of Earth Search (see lib/s2index.py)
returns every Sentinel-2 Collection 1 L2A scene over the AOI tiles. From
those rows this writes:

  site/data/sat_availability.json   one row per pass date with a quality
                                    verdict and a plain-English "why"
                                    (read by the map, the data page and
                                    check_new_clear_pass.py)
  site/data/scenes.json             one row per tile per date — the Data
                                    page's scene table. Every row carries
                                    the scene id and the COG/thumbnail
                                    URLs straight from the index.

Usage:
    python snowline/pipeline/build_sat_availability.py               # last 400 days
    python snowline/pipeline/build_sat_availability.py --days=30     # quick run
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))  # repo root, for `lib`
from lib import s2index  # noqa: E402
from lib.aoi import SNOWLINE  # noqa: E402

DATA_DIR = REPO_ROOT / "site" / "data"
OUT_AVAIL = DATA_DIR / "sat_availability.json"
OUT_SCENES = DATA_DIR / "scenes.json"
TOTAL_TILES = len(SNOWLINE.tiles)

CLEAR_CLOUD = 30      # a tile is "clear" below this scene cloud %
SLIVER_NODATA = 95    # a tile this empty is an orbit-edge sliver; not counted at all
CLEAR_NODATA = 50     # a "clear" tile must also be at least half imaged


def log(msg):
    print(f"[sat] {msg}", flush=True)


def classify(n_clear, mean_cloud):
    # Counts are of tiles under CLEAR_CLOUD cloud and at least half imaged;
    # one orbit fully images about 6-9 of the 12 tiles.
    if n_clear >= 8 and mean_cloud < 20:
        return "excellent"
    if n_clear >= 4:
        return "good"
    if n_clear >= 2:
        return "partial"
    return "cloudy"


def explain(q, n_tiles, n_clear, mean_cloud, snow):
    if n_tiles == 0:
        return "No Sentinel-2 pass over the area today."
    snow_txt = f" ESA's scene classifier flags {snow:.0f}% of the imaged area as snow." if snow is not None else ""
    if q == "excellent":
        return f"Clear day — {n_clear} of {TOTAL_TILES} tiles under {CLEAR_CLOUD}% cloud.{snow_txt}"
    if q == "good":
        return f"Mostly clear — {n_clear} clear tiles, enough for a useful snow map.{snow_txt}"
    if q == "partial":
        return f"Partial — {n_clear} clear tiles; the rest of the area is cloudy or outside this orbit."
    if mean_cloud < CLEAR_CLOUD:
        return f"Edge of the swath — {n_tiles} tiles only partly imaged; too little of the area for a map."
    return f"Too cloudy — {n_tiles} tiles imaged, average {mean_cloud:.0f}% cloud. Snow hidden by clouds."


FOOTPRINT_DAYS = 40   # recent passes get their imaged strip; the map draws
                      # them and predicts the next ones (same track 10 days on)


def add_footprints(avail_rows, today):
    """Put each recent pass's imaged area ("footprint", GeoJSON geometry,
    clipped 1.5° beyond the AOI and simplified to ~500 m) and the share of the AOI
    it covers ("aoi_cover_pct") on its row. Optional: if
    the query or shapely fails, rows go out without it."""
    try:
        from shapely import wkb as shp_wkb
        from shapely.geometry import box, mapping
        from shapely.ops import unary_union
        by_date = s2index.footprints(SNOWLINE.tiles, today - timedelta(days=FOOTPRINT_DAYS), today)
    except Exception as e:  # noqa: BLE001
        log(f"  footprints skipped ({type(e).__name__}: {e})")
        return
    w, s, e_, n = SNOWLINE.bbox_list
    near = box(w - 1.5, s - 1.5, e_ + 1.5, n + 1.5)   # strips run past the AOI (to Jackson)
    aoi = box(w, s, e_, n)
    rnd = lambda c: [round(c[0], 3), round(c[1], 3)]
    def round_geom(g):
        m = mapping(g)
        if m["type"] == "Polygon":
            return {"type": "Polygon", "coordinates": [[rnd(c) for c in ring] for ring in m["coordinates"]]}
        return {"type": "MultiPolygon", "coordinates": [[[rnd(c) for c in ring] for ring in poly] for poly in m["coordinates"]]}
    done = 0
    for row in avail_rows:
        polys = by_date.get(row["dt"])
        if not polys:
            continue
        full = unary_union([shp_wkb.loads(b) for b in polys])
        # Share of the AOI inside the imaged strip (cloud or not).
        row["aoi_cover_pct"] = round(full.intersection(aoi).area / aoi.area * 100, 1)
        g = full.intersection(near).simplify(0.005)
        if not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon"):
            row["footprint"] = round_geom(g)
            done += 1
    log(f"  footprints for {done} recent passes")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=400, help="How far back to look (default 400)")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=args.days)
    log(f"Querying S2 GeoParquet for {TOTAL_TILES} tiles, {start} → {today}...")
    rows = s2index.scenes(SNOWLINE.tiles, start, today)
    log(f"  {len(rows)} tile-days")

    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)

    avail_rows, s2_table = [], []
    stats = {"total": 0, "s2_scenes": len(rows), "excellent": 0, "good": 0, "partial": 0, "cloudy": 0}
    for dt in sorted(by_date, reverse=True):
        tiles = [r for r in by_date[dt] if (r["nodata"] or 0) < SLIVER_NODATA]
        if not tiles:
            continue
        n = len(tiles)
        clear = [r for r in tiles
                 if (r["cloud"] if r["cloud"] is not None else 100) < CLEAR_CLOUD
                 and (r["nodata"] or 0) < CLEAR_NODATA]
        mean_cloud = round(sum((r["cloud"] or 0) for r in tiles) / n, 1)
        # Area-weighted by valid (non-nodata) share of each tile.
        w = [(100 - (r["nodata"] or 0)) for r in tiles]
        snow_vals = [(r["snow"] or 0) for r in tiles]
        snow = round(sum(a * b for a, b in zip(w, snow_vals)) / max(1e-9, sum(w)), 1)
        nodata = round(sum((r["nodata"] or 0) for r in tiles) / n, 1)
        aoi = round(n / TOTAL_TILES * 100)
        q = classify(len(clear), mean_cloud)
        stats[q] += 1
        stats["total"] += 1
        avail_rows.append({
            "dt": dt,
            "s2n": n, "s2clr": len(clear), "s2cc": mean_cloud, "s2aoi": aoi,
            "snow_pct": snow, "nodata_pct": nodata,
            "tiles": sorted(r["tile"] for r in tiles),
            "clear_tiles": sorted(r["tile"] for r in clear),
            "comb": aoi,
            "q": q,
            "why": explain(q, n, len(clear), mean_cloud, snow),
        })
        s2_table.append({"dt": dt, "src": "c1", "products": ["L2A C1"], "n": n,
                         "clr": len(clear), "cc": mean_cloud, "aoi": aoi, "snow": snow})

    # Compact per-scene table for the Data page. Arrays, not objects, to
    # keep the file small; the column order is in "columns". Every asset of
    # a scene sits in one directory, so we store that directory once per row
    # and the file name per asset key once per file — both read from the
    # actual hrefs in the index, and checked: a scene whose hrefs don't fit
    # that pattern gets its full URLs in "extra".
    asset_keys = ["thumbnail", "visual", "green", "swir16", "scl"]
    files = {}
    for r in rows:
        for k in asset_keys:
            href = r["assets"].get(k, {}).get("href")
            if href:
                files.setdefault(k, href.rsplit("/", 1)[1])
    columns = ["date", "tile", "id", "cloud", "snow", "nodata", "baseline", "dir", "extra"]
    scene_rows = []
    for r in rows:
        hrefs = {k: r["assets"].get(k, {}).get("href") for k in asset_keys}
        dirs = {h.rsplit("/", 1)[0] for h in hrefs.values() if h}
        fits = len(dirs) == 1 and all(h is None or h.rsplit("/", 1)[1] == files.get(k) for k, h in hrefs.items())
        scene_rows.append([
            r["date"], r["tile"], r["id"], r["cloud"], r["snow"], r["nodata"], r["baseline"],
            dirs.pop() + "/" if fits else None,
            None if fits else hrefs,
        ])

    add_footprints(avail_rows, today)

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = {
        "name": "Sentinel-2 C1 L2A via s2-stac-geoparquet",
        "index": s2index.BASE,
        "explorer": s2index.EXPLORER_URL,
        "credit": "Taylor Geospatial / TGE Labs (index), Element 84 Earth Search (STAC), ESA Copernicus (imagery)",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_AVAIL.write_text(json.dumps({
        "generated": generated,
        "source": source,
        "aoi": {"bbox": SNOWLINE.bbox_list, "tiles": list(SNOWLINE.tiles)},
        "thresholds": {"clear_cloud_pct": CLEAR_CLOUD, "clear_nodata_pct": CLEAR_NODATA, "sliver_nodata_pct": SLIVER_NODATA},
        "stats": stats,
        "rows": avail_rows,
        "s2_table": s2_table,
    }, separators=(",", ":")))
    OUT_SCENES.write_text(json.dumps({
        "generated": generated,
        "source": source,
        "columns": columns,
        "files": files,
        "note": "asset URL = dir + files[key], or extra[key] when dir is null",
        "rows": scene_rows,
    }, separators=(",", ":")))

    log(f"Done: {len(avail_rows)} pass dates → {OUT_AVAIL.name} ({OUT_AVAIL.stat().st_size // 1024} KB), "
        f"{len(scene_rows)} scenes → {OUT_SCENES.name} ({OUT_SCENES.stat().st_size // 1024} KB)")
    log(f"  Excellent {stats['excellent']} · Good {stats['good']} · Partial {stats['partial']} · Cloudy {stats['cloudy']}")
    if avail_rows:
        log(f"  Latest pass: {avail_rows[0]['dt']} — {avail_rows[0]['why']}")


if __name__ == "__main__":
    main()
