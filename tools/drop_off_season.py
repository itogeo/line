#!/usr/bin/env python3
"""
Remove off-season Snowline dates (June 1 to Sept 30) from the site's files.

The season is Oct 1 to May 31 (lib/aoi.py in_season). This drops every
other date from:
    snowline/site/data_10m/{date}/            (map metadata)
    snowline/site/data_10m/dates.json
    snowline/site/stac/snowline-snow-cover/   (items + collection links)
    snowline/site/data/terrain_stats.json, snotel_agreement.json

R2 objects for those dates are deleted by prune_r2.py in the imagery job.
Safe to re-run. Prints what it removed; commit the result yourself.

Usage:
    python tools/drop_off_season.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.aoi import in_season  # noqa: E402

SITE = ROOT / "snowline" / "site"
DATA_10M = SITE / "data_10m"
STAC = SITE / "stac" / "snowline-snow-cover"


def is_date(name):
    return len(name) == 10 and name[4] == "-" and name[7] == "-"


def main():
    gone = set()
    for d in sorted(p for p in DATA_10M.iterdir() if p.is_dir() and is_date(p.name)):
        if not in_season(d.name):
            shutil.rmtree(d)
            gone.add(d.name)
    for d in sorted(p for p in STAC.iterdir() if p.is_dir() and is_date(p.name)):
        if not in_season(d.name):
            shutil.rmtree(d)
            gone.add(d.name)

    dp = DATA_10M / "dates.json"
    idx = json.loads(dp.read_text())
    dates = idx["dates"]
    keep = [d for d in dates if in_season(d)]
    gone |= set(dates) - set(keep)
    idx.update(dates=keep, latest=keep[-1], stats={d: v for d, v in idx.get("stats", {}).items() if d in keep})
    dp.write_text(json.dumps(idx))

    col = STAC / "collection.json"
    c = json.loads(col.read_text())
    c["links"] = [l for l in c["links"]
                  if not (l.get("rel") == "item" and not in_season(l["href"].split("/")[1]))]
    col.write_text(json.dumps(c, indent=1))

    for name in ("terrain_stats.json", "snotel_agreement.json"):
        p = SITE / "data" / name
        j = json.loads(p.read_text())
        before = len(j["dates"])
        j["dates"] = {d: v for d, v in j["dates"].items() if in_season(d)}
        if len(j["dates"]) != before:
            p.write_text(json.dumps(j, separators=(",", ":")))

    print(f"removed {len(gone)} off-season dates: {', '.join(sorted(gone)) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
