#!/usr/bin/env python3
"""
Satellite vs. ground: does the snow map agree with SNOTEL?

For every date that has a snow map, look up the map's class at each SNOTEL
station (a 3x3 pixel neighbourhood, ~70 m) and compare it with the snow
depth the station measured that day:

    depth >= 2 in  and map says snow    -> agree (snow)
    depth == 0     and map says ground  -> agree (bare)
    depth >= 2 in  and map says ground  -> miss   (often forest canopy)
    depth == 0     and map says snow    -> false snow
    cloud / no data at the station, or depth of 1 in -> not counted

The map's class is read back from the published snow WebPs, i.e. exactly
what a visitor sees. Station depths come from site/data/snotel_season.json
when it covers the date, otherwise from the NRCS AWDB API.

Writes site/data/snotel_agreement.json.

Usage:
    python pipeline/build_snotel_agreement.py              # every date with tiles on disk
    python pipeline/build_snotel_agreement.py --date=2026-10-03
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # legacy per-tile WebPs are ~13k x 10k

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_10M = REPO_ROOT / "site" / "data_10m"
SEASON_JSON = REPO_ROOT / "site" / "data" / "snotel_season.json"
OUT = REPO_ROOT / "site" / "data" / "snotel_agreement.json"
NRCS = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"

SNOW_IN = 2      # depth at or above this counts as snow on the ground
WINDOW = 1       # pixels each side of the station pixel (3x3)

# Classes are encoded in the snow WebP's alpha channel by process_tiles.py
# (and by the older per-tile pipeline): 200 snow, 160/100 cloud, 120/60
# nodata (striped), 0 ground.
SNOW_A, CLOUD_A, NODATA_A = {200}, {160, 100}, {120, 60}


def log(msg):
    print(f"[agreement] {msg}", flush=True)


def images_for(meta):
    """(file, bounds) for each snow image of a date, any pipeline version."""
    out = []
    for c in meta.get("chunks") or []:
        out.append((c["snow_file"], c["bounds"]))
    for t in meta.get("tiles") or []:
        if t.get("file"):
            out.append((t["file"], t["bounds"]))
    return out


def classify_at(date_dir, images, lat, lon, cache):
    """'snow' | 'ground' | 'cloud' | 'nodata' | None (outside every image)."""
    for fname, b in images:
        if not (b["west"] <= lon <= b["east"] and b["south"] <= lat <= b["north"]):
            continue
        key = (date_dir.name, fname)
        if key not in cache:
            p = date_dir / fname
            if not p.exists():
                cache[key] = None
            else:
                cache[key] = np.asarray(Image.open(p).getchannel("A"))
        a = cache[key]
        if a is None:
            continue
        h, w = a.shape
        col = int((lon - b["west"]) / (b["east"] - b["west"]) * w)
        row = int((b["north"] - lat) / (b["north"] - b["south"]) * h)
        win = a[max(0, row - WINDOW):row + WINDOW + 1, max(0, col - WINDOW):col + WINDOW + 1].ravel()
        if win.size == 0:
            continue
        n_snow = sum(int(v) in SNOW_A for v in win)
        n_ground = sum(int(v) == 0 for v in win)
        n_cloud = sum(int(v) in CLOUD_A for v in win)
        if n_snow + n_ground == 0:
            if n_cloud:
                return "cloud"
            continue  # nodata here; a neighbouring image may cover it
        return "snow" if n_snow >= n_ground else "ground"
    return None


def load_depths(stations, dates):
    """{date: {station_id: depth_in}} from snotel_season.json, then NRCS for gaps."""
    depths = defaultdict(dict)
    if SEASON_JSON.exists():
        season = json.loads(SEASON_JSON.read_text())
        for s in season.get("stations", []):
            for h in s.get("history", []):
                if h.get("date") in dates and h.get("depth_in") is not None:
                    depths[h["date"]][s["id"]] = h["depth_in"]
    missing = sorted(d for d in dates if len(depths.get(d, {})) < len(stations) // 2)
    if missing:
        log(f"fetching NRCS depths for {len(missing)} date(s) not in snotel_season.json")
        ids = [s["id"] for s in stations]
        for i in range(0, len(ids), 40):
            batch = ids[i:i + 40]
            try:
                r = requests.get(NRCS, params={
                    "stationTriplets": ",".join(batch), "elements": "SNWD", "duration": "DAILY",
                    "beginDate": missing[0], "endDate": missing[-1],
                }, timeout=90)
                r.raise_for_status()
                for st in r.json():
                    for el in st.get("data", []):
                        for v in el.get("values", []):
                            if v.get("date") in missing and v.get("value") is not None:
                                depths[v["date"]][st["stationTriplet"]] = v["value"]
            except Exception as e:  # noqa: BLE001 - flaky API; partial is fine
                log(f"  NRCS batch failed: {type(e).__name__}: {str(e)[:120]}")
            time.sleep(0.5)
    return depths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Only this date (merged into the existing file)")
    args = ap.parse_args()

    season = json.loads(SEASON_JSON.read_text()) if SEASON_JSON.exists() else {"stations": []}
    stations = [s for s in season["stations"] if s["id"].endswith(":SNTL")]
    if not stations:
        log("no SNOTEL stations (run build_snotel_season.py first)")
        return 1

    all_dates = json.loads((DATA_10M / "dates.json").read_text()).get("dates", [])
    dates = [args.date] if args.date else all_dates
    dates = [d for d in dates if (DATA_10M / d / "snowline.json").exists() and any((DATA_10M / d).glob("snow_*.webp"))]
    if not dates:
        log("no dates with snow tiles on disk")
        return 1

    depths = load_depths(stations, set(dates))
    result = json.loads(OUT.read_text()).get("dates", {}) if (args.date and OUT.exists()) else {}
    for d in dates:
        meta = json.loads((DATA_10M / d / "snowline.json").read_text())
        images = images_for(meta)
        cache = {}
        counts = {"snow_agree": 0, "bare_agree": 0, "miss": 0, "false_snow": 0, "cloud": 0, "skipped": 0}
        rows = []
        for s in stations:
            depth = depths.get(d, {}).get(s["id"])
            cls = classify_at(DATA_10M / d, images, s["lat"], s["lon"], cache)
            if cls is None or depth is None:
                continue
            if cls in ("cloud", "nodata"):
                counts["cloud"] += 1
                verdict = "cloud"
            elif depth >= SNOW_IN:
                verdict = "snow_agree" if cls == "snow" else "miss"
            elif depth == 0:
                verdict = "bare_agree" if cls == "ground" else "false_snow"
            else:
                verdict = "skipped"
            if verdict not in ("cloud",):
                counts[verdict] += 1
            rows.append([s["id"], s["name"], depth, cls, verdict])
        evaluated = counts["snow_agree"] + counts["bare_agree"] + counts["miss"] + counts["false_snow"]
        agree = counts["snow_agree"] + counts["bare_agree"]
        result[d] = {
            "evaluated": evaluated,
            "agree": agree,
            "pct": round(agree / evaluated * 100) if evaluated else None,
            **counts,
            "stations": rows,
        }
        log(f"{d}: {agree}/{evaluated} agree"
            + (f" ({result[d]['pct']}%)" if evaluated else "")
            + f" · miss {counts['miss']} · false snow {counts['false_snow']} · cloud {counts['cloud']}")

    OUT.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": {
            "snow_depth_in": SNOW_IN,
            "window_px": 2 * WINDOW + 1,
            "columns": ["station", "name", "depth_in", "map_class", "verdict"],
            "note": "Map class is the majority of snow vs ground pixels in a 3x3 window at the station. "
                    "Depth of 1 in is not counted. Cloud or no data at the station is not counted.",
        },
        "source": "USDA NRCS SNOTEL (depth), Snowline snow map (class)",
        "dates": dict(sorted(result.items())),
    }, separators=(",", ":")))
    tot_e = sum(v["evaluated"] for v in result.values())
    tot_a = sum(v["agree"] for v in result.values())
    if tot_e:
        log(f"All dates: {tot_a}/{tot_e} station-days agree ({tot_a / tot_e * 100:.0f}%) → {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
