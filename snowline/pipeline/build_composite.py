#!/usr/bin/env python3
"""
The "latest view": for every pixel, the most recent clear look.

A single Sentinel-2 pass rarely covers the whole Snowline area. Each orbit
images a strip, and clouds take bites out of it, so a one-day map is often
half hatched. This builds, for each map date D, a composite where every
pixel shows the newest clear observation (snow or ground) from any pass in
the WINDOW days up to and including D. Pixels with no clear look in that
window stay cloud (if the last look was cloudy) or no data.

Per date it writes, next to the single-pass files:

  data_10m/{D}/latest_r{row}c{col}.webp   map tile, same colours as snow_*.webp
  data_10m/{D}/latest_r{row}c{col}.tif    COG, band 1 class (0 ground, 1 snow,
                                           2 cloud, 3 nodata), band 2 age in
                                           days (255 = no clear look)
  snowline.json → "latest": {window_days, chunks, sources, coverage_pct,
                             snow_cover_pct, age_pct}

Sources are read from the single-pass snow WebPs on disk, or, when a date
isn't on this machine (CI only has the dates it processed), from the
published class COGs at line.itogeospatial.com.

Usage:
    python snowline/pipeline/build_composite.py                  # every listed date
    python snowline/pipeline/build_composite.py --date=2026-10-03
    python snowline/pipeline/build_composite.py --recent=12      # dates in the last 12 days (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_10M = REPO_ROOT / "site" / "data_10m"
SITE = "https://line.itogeospatial.com/snow"
WINDOW = 10                       # days of passes a pixel may come from
GROUND, SNOW, CLOUD, NODATA = 0, 1, 2, 3
# Same encoding as process_tiles.py: the class lives in the alpha channel.
ALPHA_TO_CLASS = {0: GROUND, 200: SNOW, 160: CLOUD, 100: CLOUD, 120: NODATA, 60: NODATA}


def log(msg):
    print(f"[latest] {msg}", flush=True)


def d(s):
    return date.fromisoformat(s)


def encode_rgba(cls):
    """Class array → RGBA exactly as process_tiles.py draws the snow map."""
    h, w = cls.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[cls == SNOW] = [100, 210, 255, 200]
    rgba[cls == CLOUD] = [100, 100, 110, 160]
    nod = cls == NODATA
    if nod.any():
        yy, xx = np.mgrid[:h, :w]
        stripe = ((yy + xx) % 16 < 3) & nod
        rgba[stripe] = [255, 190, 60, 120]
        rgba[nod & ~stripe] = [20, 20, 30, 60]
    return rgba


def read_class(date_str, chunk, shape):
    """Class raster of one single-pass chunk: local WebP, else published COG."""
    local = DATA_10M / date_str / chunk["snow_file"]
    if local.exists():
        a = np.asarray(Image.open(local).getchannel("A"))
        out = np.full(a.shape, NODATA, np.uint8)
        for alpha, c in ALPHA_TO_CLASS.items():
            out[a == alpha] = c
        return out
    if chunk.get("class_file"):
        try:
            import rasterio
            with rasterio.open(f"{SITE}/api/tile/{date_str}/{chunk['class_file']}") as src:
                return src.read(1)
        except Exception as e:  # noqa: BLE001
            log(f"  {date_str} {chunk['chunk_id']}: can't read published COG ({type(e).__name__})")
    return np.full(shape, NODATA, np.uint8)


def all_maps():
    """{date: snowline.json} for every single-pass map on disk, listed or not."""
    out = {}
    for p in sorted(DATA_10M.iterdir()):
        mp = p / "snowline.json"
        if p.is_dir() and mp.exists():
            m = json.loads(mp.read_text())
            if m.get("chunks"):
                out[p.name] = m
    return out


def same_bounds(a, b, tol=1e-6):
    """True when two chunk bounds dicts describe the same rectangle."""
    if not a or not b:
        return False
    return all(abs(a[k] - b[k]) <= tol for k in ("west", "south", "east", "north"))


def build(target, maps):
    meta = maps[target]
    t = d(target)
    sources = sorted((s for s in maps if t - timedelta(days=WINDOW) < d(s) <= t), reverse=True)
    skipped = set()   # (source date, chunk, reason): logged once per target
    chunks_out, totals = [], {"px": 0, "valid": 0, "snow": 0}
    age_px = {}
    for ch in meta["chunks"]:
        cid = ch["chunk_id"]
        ref = read_class(target, ch, None)
        shape = ref.shape
        cls = np.full(shape, NODATA, np.uint8)
        age = np.full(shape, 255, np.uint8)
        seen_cloud = np.zeros(shape, bool)
        for s in sources:
            # Only passes cut on the same grid: same chunk id AND same bounds
            # (an AOI change keeps ids r0c0..r1c2 but moves the edges).
            sch = next((c for c in maps[s]["chunks"] if c["chunk_id"] == cid), None)
            if sch is None or not same_bounds(sch.get("bounds"), ch.get("bounds")):
                skipped.add((s, cid, "grid differs"))
                continue
            src = ref if s == target else read_class(s, sch, shape)
            if src.shape != shape:
                skipped.add((s, cid, f"shape {src.shape} != {shape}"))
                continue
            clear = (src == SNOW) | (src == GROUND)
            take = clear & (age == 255)
            cls[take] = src[take]
            age[take] = (t - d(s)).days
            seen_cloud |= (src == CLOUD) & (age == 255)
            if not (age == 255).any():
                break
        cls[(age == 255) & seen_cloud] = CLOUD

        b = ch["bounds"]
        stem = f"latest_{cid}"
        Image.fromarray(encode_rgba(cls)).save(DATA_10M / target / f"{stem}.webp", "WEBP", lossless=True, method=4)
        import rasterio
        from rasterio.crs import CRS
        from rasterio.transform import from_bounds
        h, w = shape
        with rasterio.open(DATA_10M / target / f"{stem}.tif", "w", driver="COG", width=w, height=h, count=2,
                           dtype="uint8", crs=CRS.from_epsg(4326),
                           transform=from_bounds(b["west"], b["south"], b["east"], b["north"], w, h),
                           nodata=255, compress="deflate", blocksize=512, overview_resampling="nearest") as dst:
            dst.write(cls, 1)
            dst.write(age, 2)
            dst.update_tags(1, classes="0=ground,1=snow,2=cloud,3=nodata")
            dst.update_tags(2, meaning=f"days between this pixel's clear look and {target}; 255 = none in {WINDOW} days")
        valid = cls <= SNOW
        totals["px"] += cls.size
        totals["valid"] += int(valid.sum())
        totals["snow"] += int((cls == SNOW).sum())
        for a, n in zip(*np.unique(age[valid], return_counts=True)):
            age_px[int(a)] = age_px.get(int(a), 0) + int(n)
        chunks_out.append({"chunk_id": cid, "snow_file": f"{stem}.webp", "class_file": f"{stem}.tif", "bounds": b})

    for sd, cid, why in sorted(skipped):
        log(f"  {target}: skipped {sd} chunk {cid} ({why})")
    used = sorted({(t - timedelta(days=a)).isoformat() for a in age_px}, reverse=True)
    meta["latest"] = {
        "window_days": WINDOW,
        "chunks": chunks_out,
        "sources": [{"date": s, "pct_of_seen": round(age_px[(t - d(s)).days] / max(1, totals["valid"]) * 100, 1)}
                    for s in used],
        "coverage_pct": round(totals["valid"] / max(1, totals["px"]) * 100, 1),
        "snow_cover_pct": round(totals["snow"] / max(1, totals["valid"]) * 100, 1),
        "method": f"newest clear observation per pixel from passes in the {WINDOW} days up to {target}",
    }
    log(f"{target}: {meta['coverage_pct']}% → {meta['latest']['coverage_pct']}% of the area seen "
        f"(from {len(used)} pass{'es' if len(used) != 1 else ''}), {meta['latest']['snow_cover_pct']}% snow")
    return meta


def upload(target, meta):
    """Put this date's latest-view files in R2. True when all made it."""
    import os
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sync_r2
    acct, token = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not acct or not token:
        log("  CF_ACCOUNT_ID / CF_API_TOKEN not set — can't upload")
        return False
    for c in meta["latest"]["chunks"]:
        for f in (c["snow_file"], c["class_file"]):
            try:
                sync_r2.put(acct, token, f"tiles/{target}/{f}", DATA_10M / target / f)
            except Exception as e:  # noqa: BLE001
                log(f"  upload failed {target}/{f}: {e}")
                return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date")
    ap.add_argument("--recent", type=int, help="Rebuild every listed date in the last N days")
    ap.add_argument("--upload", action="store_true",
                    help="Upload each date's files to R2 and only then record them in snowline.json "
                         "(CI: the site never points at tiles that aren't there)")
    args = ap.parse_args()
    maps = all_maps()
    listed = json.loads((DATA_10M / "dates.json").read_text()).get("dates", [])
    # Dates listed but not on disk (CI): include their metadata so their
    # published COGs can be used as sources.
    for s in listed:
        if s not in maps:
            try:
                import urllib.request
                with urllib.request.urlopen(f"{SITE}/data_10m/{s}/snowline.json", timeout=30) as r:
                    m = json.load(r)
                if m.get("chunks"):
                    maps[s] = m
            except Exception:
                pass
    if args.date:
        targets = [args.date]
    elif args.recent:
        cut = (date.today() - timedelta(days=args.recent)).isoformat()
        targets = [s for s in listed if s >= cut]
    else:
        targets = listed
    failed = 0
    for s in targets:
        mp = DATA_10M / s / "snowline.json"
        if not mp.exists():
            continue
        meta = build(s, maps)
        if args.upload and not upload(s, meta):
            failed += 1
            continue  # leave snowline.json as it was: the map keeps the single-pass view
        mp.write_text(json.dumps(meta))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
