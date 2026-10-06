#!/usr/bin/env python3
"""
A decade of snow cover per Sentinel-2 tile, from metadata alone.

Every Sentinel-2 L2A scene carries ESA's scene-classification summary,
including ``s2:snow_ice_percentage``: the share of the tile its classifier
labelled snow or ice. The S2 GeoParquet index has that number for every
scene since 2015, so we can chart snow cover through every winter for every
AOI tile without downloading a single pixel.

Writes site/data/snow_timeline.json:

    {"generated": ..., "tiles": {"12TVR": [["2018-01-03", snow, cloud], ...]}, ...}

Only scenes with cloud <= MAX_CLOUD and nodata < MAX_NODATA are kept, because
snow under cloud is invisible to the classifier and an orbit-edge sliver
says little about the tile.

Caveat (from the index's AGENTS.md): the Collection 1 reprocessing has not
finished 2015–2017 and covers only a fraction of 2022, so those years are
thin in the index, not in reality.

Usage:
    python pipeline/build_snow_timeline.py              # 2015 → today
    python pipeline/build_snow_timeline.py --start=2024 # quick smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT.parent))  # repo root, for `lib`
from lib import s2index  # noqa: E402
from lib.aoi import SNOWLINE  # noqa: E402

OUT = REPO_ROOT / "site" / "data" / "snow_timeline.json"
MAX_CLOUD = 20
MAX_NODATA = 50


def log(msg):
    print(f"[timeline] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2015, help="First year (default 2015)")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    tiles = {t: [] for t in SNOWLINE.tiles}
    years = {}
    t0 = time.time()
    for year in range(args.start, today.year + 1):
        rows = s2index.scenes(SNOWLINE.tiles, f"{year}-01-01", f"{year}-12-31", max_cloud=MAX_CLOUD)
        kept = 0
        for r in sorted(rows, key=lambda r: r["date"]):
            if r["nodata"] is not None and r["nodata"] >= MAX_NODATA:
                continue
            tiles[r["tile"]].append([r["date"], r["snow"], r["cloud"]])
            kept += 1
        years[year] = kept
        log(f"{year}: {kept} clear scenes ({time.time() - t0:.0f}s)")

    for t in tiles:
        tiles[t].sort()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "name": "s2:snow_ice_percentage from Sentinel-2 C1 L2A scene metadata",
            "index": s2index.BASE,
            "docs": f"{s2index.BASE}/AGENTS.md",
        },
        "filter": {"max_cloud_pct": MAX_CLOUD, "max_nodata_pct": MAX_NODATA},
        "caveat": "2015–2017 and 2022 are thin because ESA's Collection 1 reprocessing "
                  "has not reached them yet, not because Sentinel-2 wasn't imaging.",
        "columns": ["date", "snow_pct", "cloud_pct"],
        "scenes_per_year": years,
        "tiles": tiles,
    }, separators=(",", ":")))
    total = sum(len(v) for v in tiles.values())
    log(f"Done: {total} scenes → {OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
