#!/usr/bin/env python3
"""
Wind for the Snowline area: a 48-hour wind map and 7 days of station wind.

1. Wind map (grid_48h.json): NOAA's Real-Time Mesoscale Analysis (RTMA,
   2.5 km, hourly; public domain, noaa-rtma-pds on AWS Open Data). Each hour's
   national file is ~80 MB, but its .idx gives byte offsets, so only the
   10 m wind direction, speed and gust fields are read (~16 MB), cut to the
   area and resampled to a 0.05 deg display grid. Direction is NOAA's WDIR
   (true north); speed and gust in mph. Keeps the newest 48 hours: each run
   reads the published file back, adds the hours it lacks, drops older ones.

2. Stations (stations_7d.json): hourly wind speed, gust and direction for the
   last 7 days from three free, keyless sources, merged (a station within
   500 m of one already taken is skipped, in this order):
     - Montana Mesonet (Montana Climate Office): valley and foothill stations,
       sensors at 10 m or 8 ft.
     - NRCS SNOTEL/SCAN (AWDB REST API): the SNOTEL sites with a wind sensor.
     - NWS (api.weather.gov): every station at or above 1,700 m that reported
       wind in the last day: fire-weather RAWS, ski-area and road-weather
       stations relayed through the NWS. Readings are 5-60 min; kept as the
       last reading in each hour with the hour's highest gust.

Writes both to snowline/site/data/wind/ and, with --upload, to R2 under
wind/ (served at /snow/api/wind/<file>). Run hourly by snowline-wind.yml.

Needs pygrib (pip install pygrib), numpy, requests.

Usage:
    python snowline/pipeline/fetch_wind.py            # build locally
    python snowline/pipeline/fetch_wind.py --upload   # and put in R2 (CI)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.aoi import SNOWLINE  # noqa: E402

OUT = ROOT / "snowline" / "site" / "data" / "wind"
LIVE = "https://line.itogeospatial.com/snow/api/wind"
RTMA = "https://noaa-rtma-pds.s3.amazonaws.com"
MESONET = "https://mesonet.climate.umt.edu/api/v2"
AWDB = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
NWS = "https://api.weather.gov"
NWS_MIN_ELEV_M = 1700                    # mountain stations; the Mesonet covers the valleys
KMH_TO_MPH = 0.621371
HEADERS = {"User-Agent": "snowline (line.itogeospatial.com/snow; itogeospatial@gmail.com)"}
FIELDS = ("WDIR", "WIND", "GUST")       # 10 m above ground
HOURS = 48
STATION_DAYS = 7
RES = 0.05                               # display grid, degrees
MS_TO_MPH = 2.23694


def log(msg):
    print(f"[wind] {msg}", flush=True)


def grid_spec():
    w, s, e, n = SNOWLINE.bbox
    nx, ny = round((e - w) / RES), round((n - s) / RES)
    return {"west": w, "south": s, "east": e, "north": n, "res": RES, "nx": nx, "ny": ny}


def rtma_url(t):
    return f"{RTMA}/rtma2p5.{t:%Y%m%d}/rtma2p5.t{t:%H}z.2dvaranl_ndfd.grb2_wexp"


def read_hour(t, nearest):
    """{field: values on the display grid} for one RTMA hour, or None if not out yet."""
    import pygrib
    r = requests.get(rtma_url(t) + ".idx", timeout=60)
    if r.status_code != 200:
        return None
    rows = [ln.split(":") for ln in r.text.strip().splitlines()]
    offs = [(int(x[1]), x[3], x[4]) for x in rows]
    out = {}
    for k, (o, var, level) in enumerate(offs):
        if var not in FIELDS or level != "10 m above ground":
            continue
        end = offs[k + 1][0] - 1 if k + 1 < len(offs) else ""
        b = requests.get(rtma_url(t), headers={"Range": f"bytes={o}-{end}"}, timeout=180).content
        with tempfile.NamedTemporaryFile(suffix=".grb2") as f:
            f.write(b)
            f.flush()
            g = pygrib.open(f.name).message(1)
            if nearest[0] is None:
                nearest[0] = nearest_index(*g.latlons())
            out[var] = np.asarray(g.values, float).ravel()[nearest[0]]
    return out if len(out) == len(FIELDS) else None


def nearest_index(lats, lons):
    """For each display-grid cell centre, the flat index of the nearest RTMA cell."""
    gs = grid_spec()
    lat_c = gs["north"] - (np.arange(gs["ny"]) + 0.5) * RES
    lon_c = gs["west"] + (np.arange(gs["nx"]) + 0.5) * RES
    tlat, tlon = np.meshgrid(lat_c, lon_c, indexing="ij")
    pad = 0.1
    m = ((lats >= gs["south"] - pad) & (lats <= gs["north"] + pad)
         & (lons >= gs["west"] - pad) & (lons <= gs["east"] + pad))
    src = np.flatnonzero(m.ravel())
    sla, slo = lats.ravel()[src], lons.ravel()[src]
    k = np.cos(np.radians(45.5))
    idx = np.empty(tlat.size, int)
    for i, (a, o) in enumerate(zip(tlat.ravel(), tlon.ravel())):
        idx[i] = src[np.argmin((sla - a) ** 2 + ((slo - o) * k) ** 2)]
    return idx


def b64(a):
    return base64.b64encode(np.asarray(a, np.uint8).tobytes()).decode()


def encode(fields):
    spd = np.clip(np.round(fields["WIND"] * MS_TO_MPH), 0, 255)
    gst = np.clip(np.round(fields["GUST"] * MS_TO_MPH), 0, 255)
    dr = np.round(fields["WDIR"] / 2) % 180          # 2-degree steps
    return {"spd": b64(spd), "gst": b64(gst), "dir": b64(dr)}


def build_grid():
    gs = grid_spec()
    old = {}
    try:
        r = requests.get(f"{LIVE}/grid_48h.json", timeout=60)
        if r.ok and r.json().get("grid") == gs:
            old = {h["t"]: h for h in r.json()["hours"]}
    except (requests.RequestException, ValueError):
        pass
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    want = [now - timedelta(hours=h) for h in range(HOURS + 3)]   # RTMA runs ~1 h behind
    nearest, hours, added = [None], dict(old), 0
    for t in want:
        key = f"{t:%Y-%m-%dT%H}:00Z"
        if key in hours:
            continue
        try:
            f = read_hour(t, nearest)
        except Exception as e:  # noqa: BLE001
            log(f"  {key}: {e.__class__.__name__}: {e}")
            continue
        if f is None:
            continue
        hours[key] = {"t": key, **encode(f)}
        added += 1
    keys = sorted(hours)[-HOURS:]
    log(f"wind map: {added} new hours, {len(keys)} kept ({keys[0] if keys else '-'} to {keys[-1] if keys else '-'})")
    return {
        "grid": gs,
        "units": {"spd": "mph", "gst": "mph", "dir": "degrees / 2, direction the wind blows FROM (true north)"},
        "hours": [hours[k] for k in keys],
        "source": "NOAA Real-Time Mesoscale Analysis (RTMA) 2.5 km, 10 m wind; resampled to 0.05 deg",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def mesonet_stations(start):
    w, s, e, n = SNOWLINE.bbox
    sts = requests.get(f"{MESONET}/stations/", params={"type": "json"}, headers=HEADERS, timeout=60).json()
    here = [x for x in sts if w <= x["longitude"] <= e and s <= x["latitude"] <= n]
    end = datetime.now(timezone.utc)
    out, failed = [], 0
    for st in here:
        try:
            r = requests.get(f"{MESONET}/observations/hourly/", headers=HEADERS, timeout=120, params={
                "type": "json", "stations": st["station"], "elements": "wind_spd,wind_dir,windgust",
                "start_time": start.strftime("%Y-%m-%d"), "end_time": (end + timedelta(days=1)).strftime("%Y-%m-%d")})
            if 400 <= r.status_code < 500:      # no wind sensor
                continue
            r.raise_for_status()
            rows = r.json()
        except (requests.RequestException, ValueError) as ex:
            log(f"  {st['station']}: {ex.__class__.__name__}")
            failed += 1
            continue
        obs, height = [], None
        for row in rows:
            # Prefer the 10 m sensor; some stations only have one at 8 ft.
            for h in ("10 m", "8 ft"):
                spd = next((v for k, v in row.items() if k.startswith(f"Wind Speed @ {h}")), None)
                if spd is not None:
                    break
            if spd is None:
                continue
            height = height or h
            gst = next((v for k, v in row.items() if k.startswith(f"Gust Speed @ {h}")), None)
            dr = next((v for k, v in row.items() if k.startswith(f"Wind Direction @ {h}")), None)
            t = datetime.fromtimestamp(row["datetime"] / 1000, tz=timezone.utc)
            if t < start:
                continue
            obs.append([t.strftime("%Y-%m-%dT%H:00Z"), round(spd, 1),
                        None if gst is None else round(gst, 1), None if dr is None else round(dr)])
        if obs:
            out.append({"id": st["station"], "name": st["name"], "lat": st["latitude"], "lon": st["longitude"],
                        "elevation_ft": round(st["elevation"] * 3.28084), "sensor_height": height,
                        "source": "Montana Mesonet", "obs": sorted(obs)})
    log(f"Mesonet: {len(here)} stations in the area, {len(out)} with wind, {failed} not reached")
    return out


def snotel_stations(start):
    """SNOTEL/SCAN sites in the area with hourly wind (WSPDV average, WSPDX max, WDIRV; mph)."""
    w, s, e, n = SNOWLINE.bbox
    sts = requests.get(f"{AWDB}/stations", timeout=60, params={
        "stateCds": "MT,WY", "networkCds": "SNTL,SCAN", "elements": "WSPDV"}).json()
    here = {x["stationTriplet"]: x for x in sts if w <= x["longitude"] <= e and s <= x["latitude"] <= n}
    if not here:
        return []
    end = datetime.now(timezone.utc) + timedelta(days=1)
    data = requests.get(f"{AWDB}/data", timeout=120, params={
        "stationTriplets": ",".join(here), "elements": "WSPDV,WSPDX,WDIRV", "duration": "HOURLY",
        "beginDate": start.strftime("%Y-%m-%d %H:00"), "endDate": end.strftime("%Y-%m-%d %H:00")}).json()
    out = []
    for d in data:
        st = here[d["stationTriplet"]]
        # AWDB hourly times are in the station's dataTimeZone (NRCS keeps PST, -8, year round).
        tz = timezone(timedelta(hours=st.get("dataTimeZone", -8)))
        by = {}
        for el in d.get("data", []):
            code = el["stationElement"]["elementCode"]
            for v in el.get("values", []):
                if v.get("value") is None:
                    continue
                t = datetime.strptime(v["date"], "%Y-%m-%d %H:%M").replace(tzinfo=tz).astimezone(timezone.utc)
                by.setdefault(t, {})[code] = v["value"]
        obs = [[t.strftime("%Y-%m-%dT%H:00Z"), round(v["WSPDV"], 1),
                None if v.get("WSPDX") is None else round(v["WSPDX"], 1),
                None if v.get("WDIRV") is None else round(v["WDIRV"])]
               for t, v in sorted(by.items()) if t >= start and "WSPDV" in v]
        if obs:
            out.append({"id": st["stationTriplet"], "name": f"{st['name']} SNOTEL", "lat": st["latitude"],
                        "lon": st["longitude"], "elevation_ft": round(st["elevation"]), "sensor_height": None,
                        "source": "NRCS SNOTEL", "obs": obs})
    log(f"SNOTEL: {len(here)} sites list wind, {len(out)} with readings")
    return out


def nws_obs(sid, start):
    """Hourly [time, mph, gust mph, dir] from api.weather.gov, following the cursor pages."""
    h = {**HEADERS, "Accept": "application/geo+json"}
    url, params, feats = f"{NWS}/stations/{sid}/observations", {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ")}, []
    for _ in range(20):
        j = requests.get(url, params=params, headers=h, timeout=60).json()
        page = j.get("features", [])
        feats += page
        url, params = (j.get("pagination") or {}).get("next"), None
        if not page or not url:
            break

    def mph(q):
        if not q or q.get("value") is None:
            return None
        return q["value"] * (KMH_TO_MPH if q["unitCode"].endswith("km_h-1") else MS_TO_MPH)

    hours = {}
    for f in sorted(feats, key=lambda f: f["properties"]["timestamp"]):
        p = f["properties"]
        spd = mph(p.get("windSpeed"))
        if spd is None:
            continue
        key = p["timestamp"][:13] + ":00Z"
        gst = mph(p.get("windGust"))
        prev = hours.get(key)
        g = max([x for x in (gst, prev and prev[2]) if x is not None], default=None)
        dr = (p.get("windDirection") or {}).get("value")
        hours[key] = [key, round(spd, 1), None if g is None else round(g, 1), None if dr is None else round(dr)]
    return [hours[k] for k in sorted(hours)]


def nws_stations(start):
    w, s, e, n = SNOWLINE.bbox
    h = {**HEADERS, "Accept": "application/geo+json"}
    cands = []
    for state in ("MT", "WY"):
        url = f"{NWS}/stations?state={state}&limit=500"
        while url:
            j = requests.get(url, headers=h, timeout=60).json()
            fs = j.get("features", [])
            for f in fs:
                lon, lat = f["geometry"]["coordinates"][:2]
                p = f["properties"]
                el = (p.get("elevation") or {}).get("value") or 0
                if w <= lon <= e and s <= lat <= n and el >= NWS_MIN_ELEV_M:
                    name = p["name"].strip()
                    cands.append({"id": p["stationIdentifier"], "name": name.title() if name.isupper() else name, "lat": lat, "lon": lon,
                                  "elevation_ft": round(el * 3.28084)})
            url = (j.get("pagination") or {}).get("next") if fs else None

    def one(st):
        try:
            return st, nws_obs(st["id"], start)
        except (requests.RequestException, ValueError, KeyError):
            return st, None

    out, failed = [], 0
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H")
    with ThreadPoolExecutor(6) as ex:
        for st, obs in ex.map(one, cands):
            if obs is None:
                failed += 1
            elif obs and obs[-1][0] >= recent:
                out.append({**st, "sensor_height": None, "source": "NWS", "obs": obs})
    log(f"NWS: {len(cands)} stations at {NWS_MIN_ELEV_M}+ m, {len(out)} with wind in the last day, {failed} not reached")
    return out


def km_apart(a, b):
    k = math.cos(math.radians(a["lat"]))
    return 111.2 * math.hypot(a["lat"] - b["lat"], (a["lon"] - b["lon"]) * k)


def build_stations():
    start = datetime.now(timezone.utc) - timedelta(days=STATION_DAYS)
    out = []
    for name, fn in (("Mesonet", mesonet_stations), ("SNOTEL", snotel_stations), ("NWS", nws_stations)):
        try:
            got = fn(start)
        except (requests.RequestException, ValueError) as ex:
            log(f"{name}: {ex.__class__.__name__}: {ex}")
            continue
        for st in got:
            if all(km_apart(st, o) > 0.5 for o in out):
                out.append(st)
    log(f"stations: {len(out)} with wind")
    return {
        "columns": ["time (UTC, hour)", "speed mph", "gust mph", "direction deg (from, true)"],
        "stations": out,
        "source": ("Montana Mesonet (Montana Climate Office, University of Montana); NRCS SNOTEL (AWDB); "
                   "NWS observations (api.weather.gov): RAWS, ski-area and road-weather stations"),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    files = []
    grid = build_grid()
    if grid["hours"]:
        p = OUT / "grid_48h.json"
        p.write_text(json.dumps(grid, separators=(",", ":")))
        files.append(p)
    else:
        log("ERROR: no RTMA hours read; not writing the wind map")
    stations = build_stations()
    if stations["stations"]:
        p = OUT / "stations_7d.json"
        p.write_text(json.dumps(stations, separators=(",", ":")))
        files.append(p)
    else:
        log("ERROR: no station wind; not writing stations")
    for p in files:
        log(f"  {p.name}: {p.stat().st_size // 1024} KB")
    if args.upload:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import sync_r2
        acct, token = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
        if not acct or not token:
            log("CF_ACCOUNT_ID / CF_API_TOKEN not set")
            return 1
        for p in files:
            sync_r2.put(acct, token, f"wind/{p.name}", p)
        log(f"uploaded {len(files)} files to R2 wind/")
    return 0 if len(files) == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
