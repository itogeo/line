#!/usr/bin/env python3
"""
Is Snowline live and healthy? Checks the public site the way a visitor
would and prints PASS/FAIL per item. Exit code 0 only if everything passes.

    python tools/release_check.py                     # production
    python tools/release_check.py --base http://localhost:8787   # dev_server

Standard library only, so it runs anywhere (CI, a laptop, an agent loop).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "snowline-release-check/1.0"}


def get(url, want_json=False):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return r.status, (json.loads(body) if want_json else body), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, None, dict(e.headers or {})
    except Exception as e:  # network, JSON
        return 0, str(e), {}


def age_days(iso_or_date):
    s = str(iso_or_date).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s if "T" in s else s + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="https://line.itogeospatial.com")
    ap.add_argument("--max-pass-age", type=float, default=3,
                    help="days the newest map may lag the newest pass that imaged >=10%% of the AOI (default 3)")
    a = ap.parse_args()
    B = a.base.rstrip("/") + "/snow"
    results = []

    def check(name, ok, detail=""):
        results.append((ok, name, detail))

    # Pages a visitor opens
    for path in ["/", "/metadata.html", "/methods.html", "/stac/catalog.json", "/terrain/shade.json"]:
        st, _, _ = get(B + path)
        check(f"page {path}", st == 200, f"HTTP {st}")

    # Newest map: listed, has tiles in R2, has a latest view
    st, dates, _ = get(B + "/data_10m/dates.json", True)
    newest = None
    if st == 200 and isinstance(dates, dict) and dates.get("dates"):
        newest = dates["dates"][-1]
        check("dates.json", True, f"{len(dates['dates'])} maps, newest {newest}")
    else:
        check("dates.json", False, f"HTTP {st}")
    if newest:
        st, meta, _ = get(f"{B}/data_10m/{newest}/snowline.json", True)
        check("newest snowline.json", st == 200 and isinstance(meta, dict), f"HTTP {st}")
        if isinstance(meta, dict):
            chunks = meta.get("chunks") or []
            check("newest map uses current pipeline", bool(chunks) and bool(meta.get("scenes")),
                  "chunks+scenes" if chunks else "old per-tile format")
            f = chunks[0]["snow_file"] if chunks else "snow_r0c0.webp"
            st, _, h = get(f"{B}/api/tile/{newest}/{f}")
            check("newest snow tile from R2", st == 200, f"HTTP {st} {h.get('x-tile-source', '')}".strip())
            lat = meta.get("latest") or {}
            if lat.get("chunks"):
                st, _, _ = get(f"{B}/api/tile/{newest}/{lat['chunks'][0]['file'] if 'file' in lat['chunks'][0] else 'latest_r0c0.webp'}")
                check("newest latest-view tile", st == 200, f"HTTP {st}")
            else:
                check("newest latest-view tile", False, "no 'latest' block")

    # Terrain
    st, _, _ = get(B + "/api/terrain/shade/10/195/364.webp")
    check("lidar terrain tile", st == 200, f"HTTP {st}")

    # Freshness of the daily data
    st, sat, _ = get(B + "/data/sat_availability.json", True)
    if st == 200 and isinstance(sat, dict):
        rows = sat.get("rows") or []
        ga = sat.get("generated_at") or sat.get("generated")
        check("sat_availability fresh (<36 h)", bool(ga) and age_days(ga) < 1.5, f"generated {ga}")
        # Every pass is mapped now, cloudy ones too, so the newest pass that
        # imaged at least 10% of the AOI is the one the map must keep up with.
        # aoi_cover_pct is only on recent rows; older rows fall back to s2aoi.
        def cover(r):
            c = r.get("aoi_cover_pct")
            return c if c is not None else (r.get("s2aoi") or 0)
        covering = [r["dt"] for r in rows if cover(r) >= 10]
        if covering and newest:
            lag = (datetime.fromisoformat(max(covering)) - datetime.fromisoformat(newest)).days
            check(f"newest map within {a.max_pass_age:g} d of newest pass over 10% of AOI", lag <= a.max_pass_age,
                  f"newest pass {max(covering)}, newest map {newest}")
        elif newest:
            check("newest pass over 10% of AOI", False, "no pass in sat_availability.json covers 10% of the AOI")
    else:
        check("sat_availability", False, f"HTTP {st}")

    now = datetime.now(timezone.utc)
    last_season = (now.year if now.month >= 10 else now.year - 1) - 1
    for name in ["snotel_season.json", f"snotel_season_{last_season}.json",
                 "snotel_normals.json", "snotel_agreement.json"]:
        st, d, _ = get(f"{B}/data/{name}", True)
        ok = st == 200 and isinstance(d, dict)
        detail = f"HTTP {st}"
        if ok and name == "snotel_season.json":
            ok = age_days(d.get("generated_at", "1970-01-01")) < 1.5 and len(d.get("stations", [])) > 100
            detail = f"{len(d.get('stations', []))} stations, generated {d.get('generated_at')}"
        check(f"data/{name}", ok, detail)

    width = max(len(n) for _, n, _ in results)
    for ok, n, d in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(width)}  {d}")
    fails = sum(1 for ok, _, _ in results if not ok)
    print(f"\n{len(results) - fails}/{len(results)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
