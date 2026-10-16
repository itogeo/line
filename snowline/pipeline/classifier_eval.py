#!/usr/bin/env python3
"""
Score candidate snow classifiers against ground stations, offline.

Reads snowline/pipeline/data/station_pixels.json.gz (build_station_pixels.py)
and applies each rule below to the 5x5 window at every station-date that has
a truth label (>= 2 in snow, 0 in bare). The centre 3x3 is classed and the
majority (snow / ground / cloud) is the call, like the map's 3x3 smoothing.

For each rule: how many labelled station-dates it calls snow, ground or
cloud, accuracy on the ones it calls, missed snow (said ground) and false
snow (said snow on bare), split by tree cover and by elevation.
A rule is only worth shipping if missed snow falls by more than false snow
rises, across 10+ dates.

Usage:
    python snowline/pipeline/classifier_eval.py
    python snowline/pipeline/classifier_eval.py --rows   # every station-date, v1 vs each rule
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "snowline" / "pipeline" / "data" / "station_pixels.json.gz"
SNOW, GROUND, CLOUD = "snow", "ground", "cloud"
EXCLUDE = (0, 3, 8, 9, 10)          # SCL: nodata, shadow, cloud med/high, cirrus


def ndsi(b):
    return (b["green"] - b["swir16"]) / np.maximum(b["green"] + b["swir16"], 1e-6)


def v1(b):
    """The map today: NDSI >= 0.4 or SCL snow; SCL cloud/shadow excluded."""
    snow = (ndsi(b) >= 0.4) | (b["scl"] == 11)
    return np.where(np.isin(b["scl"], EXCLUDE) & (b["scl"] != 11), CLOUD, np.where(snow, SNOW, GROUND))


def bright_bare_is_cloud(b):
    """v1, but 'ground' that is bright in green and SWIR is thin cloud, not ground."""
    out = v1(b)
    return np.where((out == GROUND) & (b["green"] > 0.35) & (b["swir16"] > 0.3), CLOUD, out)


def dark_cloud_rescue(b):
    """v1, but Sen2Cor cloud with high NDSI and dark SWIR is snow (LIS-style)."""
    out = bright_bare_is_cloud(b)
    return np.where((out == CLOUD) & (ndsi(b) >= 0.4) & (b["swir16"] < 0.15) & (b["red"] > 0.2), SNOW, out)


def loose_forest(b):
    """dark_cloud_rescue, plus a lower NDSI (0.2) with a red floor where it isn't cloud,
    for snow under canopy and in shade (LIS pass 2 without the DEM gate)."""
    out = dark_cloud_rescue(b)
    return np.where((out == GROUND) & (ndsi(b) >= 0.2) & (b["red"] > 0.08), SNOW, out)


def forest_dark(b):
    """dark_cloud_rescue, plus snow under canopy: 'ground' with NDSI >= -0.1 and
    B11 <= 0.10 (snow under trees is dark but still absorbs SWIR). Applied only to
    forest pixels near or above the day's snow line (see GATED)."""
    out = dark_cloud_rescue(b)
    return np.where((out == GROUND) & (ndsi(b) >= -0.1) & (b["swir16"] <= 0.10), SNOW, out)


def ndfsi_forest(b):
    """dark_cloud_rescue, plus the published forest snow index: NDFSI =
    (NIR - B11) / (NIR + B11) >= 0.39 (Wang et al. 2015, Remote Sens. 7:15882;
    Sentinel-2 woodland thresholds 0.28-0.39, ISPRS Archives XLIII-B3-2022-771).
    The bench stores B08, standing in for B8A. Forest above the snow line only."""
    out = dark_cloud_rescue(b)
    v = (b["nir"] - b["swir16"]) / np.maximum(b["nir"] + b["swir16"], 1e-6)
    return np.where((out == GROUND) & (v >= 0.39), SNOW, out)


RULES = {"v1": v1, "bright_bare_is_cloud": bright_bare_is_cloud,
         "dark_cloud_rescue": dark_cloud_rescue, "loose_forest": loose_forest,
         "forest_dark_gated": forest_dark, "ndfsi_forest_gated": ndfsi_forest}
# Rules used only on forest (>30 % trees) within GATED[name] m below the day's snow line
# (terrain_stats.json snowline_m, from open ground); elsewhere dark_cloud_rescue.
GATED = {"forest_dark_gated": 300, "ndfsi_forest_gated": 0}   # rule: metres below the snow line it may reach
STATS = ROOT / "snowline" / "site" / "data" / "terrain_stats.json"
SNOWLINE_M = {d: v.get("snowline_m") for d, v in json.loads(STATS.read_text())["dates"].items()} if STATS.exists() else {}


def rule_for(name, r):
    if name not in GATED:
        return RULES[name]
    sl = SNOWLINE_M.get(r["date"])
    if (r["forest_pct"] or 0) > 30 and sl is not None and (r["elev_ft"] or 0) * 0.3048 >= sl - GATED[name]:
        return RULES[name]
    return dark_cloud_rescue


def call(rule, bands):
    b = {k: np.asarray(v, float)[1:4, 1:4] for k, v in bands.items()}
    c = Counter(rule(b).ravel().tolist())
    return c.most_common(1)[0][0]


def score(rows, name):
    t = Counter()
    for r in rows:
        t[(r["truth"], call(rule_for(name, r), r["bands"]))] += 1
    seen = t[("snow", SNOW)] + t[("snow", GROUND)] + t[("bare", SNOW)] + t[("bare", GROUND)]
    right = t[("snow", SNOW)] + t[("bare", GROUND)]
    return {"n": len(rows), "called": seen, "cloud": t[("snow", CLOUD)] + t[("bare", CLOUD)],
            "acc": right / seen if seen else None, "missed_snow": t[("snow", GROUND)], "false_snow": t[("bare", SNOW)]}


def fmt(s):
    acc = f"{s['acc']:.0%}" if s["acc"] is not None else "-"
    return f"n={s['n']:4} called={s['called']:4} cloud={s['cloud']:4} acc={acc:>4} missed={s['missed_snow']:3} false={s['false_snow']:3}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rows", action="store_true")
    args = ap.parse_args()
    rows = [r for r in json.loads(gzip.decompress(SRC.read_bytes()))["rows"]
            if r["truth"] and all(k in r["bands"] for k in ("green", "red", "swir16", "scl"))]
    dates = sorted({r["date"] for r in rows})
    print(f"{len(rows)} labelled station-dates over {len(dates)} dates ({dates[0]} to {dates[-1]})\n")
    groups = {
        "all": rows,
        "open (<=30% trees)": [r for r in rows if (r["forest_pct"] or 0) <= 30],
        "forest (>30%)": [r for r in rows if (r["forest_pct"] or 0) > 30],
        "below 6,000 ft": [r for r in rows if (r["elev_ft"] or 0) < 6000],
        "6,000-8,000 ft": [r for r in rows if 6000 <= (r["elev_ft"] or 0) < 8000],
        "8,000 ft and up": [r for r in rows if (r["elev_ft"] or 0) >= 8000],
    }
    for g, rs in groups.items():
        if not rs:
            continue
        print(g)
        for name in RULES:
            print(f"  {name:22} {fmt(score(rs, name))}")
    if args.rows:
        print()
        for r in rows:
            calls = " ".join(f"{call(rule_for(n, r), r['bands']):6}" for n in RULES)
            print(f"{r['date']} {r['name'][:18]:18} {r['truth']:4} {calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
