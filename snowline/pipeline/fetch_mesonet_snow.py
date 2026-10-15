#!/usr/bin/env python3
"""
Valley snow depth from the Montana Mesonet (Montana Climate Office, UM).

SNOTEL stations in the mapped area all sit between 6,310 and 9,420 ft. The
Mesonet's HydroMet stations measure snow depth (sonic sensor) on the valley
floors, 4,000-5,300 ft, where SNOTEL has nothing. This pulls the daily snow
depth for every Mesonet station in the area that reports it, from the
season start (Oct 1) to today, via the open API (no key):
    https://mesonet.climate.umt.edu/api/v2/

Writes site/data/mesonet_snow.json:
    {"stations": [{"id", "name", "lat", "lon", "elevation_ft",
                   "history": [{"date", "depth_in"}]}], "generated", "source"}

A station with no snow-depth reading this season is left out. Daily values
are the API's daily summary; the date is the Montana calendar day.

Usage:
    python snowline/pipeline/fetch_mesonet_snow.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.aoi import SNOWLINE  # noqa: E402

OUT = ROOT / "snowline" / "site" / "data" / "mesonet_snow.json"
API = "https://mesonet.climate.umt.edu/api/v2"
HEADERS = {"User-Agent": "snowline (line.itogeospatial.com/snow; itogeospatial@gmail.com)"}
MT = timezone(timedelta(hours=-7))   # daily summaries start at local midnight (MST)


def log(msg):
    print(f"[mesonet] {msg}", flush=True)


def main():
    w, s, e, n = SNOWLINE.bbox
    stations = requests.get(f"{API}/stations/", params={"type": "json"}, headers=HEADERS, timeout=60).json()
    here = [st for st in stations if w <= st["longitude"] <= e and s <= st["latitude"] <= n]
    today = date.today()
    start = date(today.year if today.month >= 10 else today.year - 1, 10, 1)
    # One request per station: a single request for all of them times out.
    hist, failed, no_sensor = {}, 0, 0
    for st in here:
        try:
            r = requests.get(f"{API}/observations/daily/", headers=HEADERS, timeout=60, params={
                "type": "json", "elements": "snow_depth", "stations": st["station"],
                "start_time": start.isoformat(), "end_time": (today + timedelta(days=1)).isoformat()})
            if 400 <= r.status_code < 500:   # station has no snow-depth sensor
                no_sensor += 1
                continue
            r.raise_for_status()
            rows = r.json()
        except (requests.RequestException, ValueError) as e:
            log(f"  {st['station']}: {e.__class__.__name__}")
            failed += 1
            continue
        for row in rows:
            v = row.get("Snow Depth [in]")
            if v is None:
                continue
            d = datetime.fromtimestamp(row["datetime"] / 1000, tz=MT).date().isoformat()
            hist.setdefault(row["station"], []).append({"date": d, "depth_in": round(max(0.0, v), 1)})
    out = []
    for st in here:
        h = sorted(hist.get(st["station"], []), key=lambda x: x["date"])
        if not h:
            continue
        out.append({"id": st["station"], "name": st["name"], "lat": st["latitude"], "lon": st["longitude"],
                    "elevation_ft": round(st["elevation"] * 3.28084), "history": h})
    log(f"{len(here)} stations in the area, {len(out)} with snow depth since {start}, {no_sensor} without a snow sensor, {failed} not reached")
    if not out:
        log("ERROR: no station returned snow depth; keeping the old file")
        return 1
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "stations": out,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Montana Mesonet, Montana Climate Office, University of Montana (climate.umt.edu/mesonet)",
    }, separators=(",", ":")))
    tmp.replace(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
