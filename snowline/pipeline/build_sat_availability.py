#!/usr/bin/env python3
"""
Pre-compute satellite availability table as a static JSON.
Run once, serve instantly — no live STAC API calls from the browser.

Queries TWO STAC providers:
  - Element84 Earth Search (AWS, no auth):
      sentinel-2-l2a  (native S2 L2A, 10m)
      landsat-c2-l2   (native Landsat 8/9 L2, 30m)
  - Microsoft Planetary Computer (signed URLs):
      hls2-s30  (NASA HLS Sentinel-2, 30m harmonized)
      hls2-l30  (NASA HLS Landsat, 30m harmonized)

Why two providers? On 2026-04-07 we discovered Element84 had 4 dates of
native Sentinel-2 (April 1, 2, 4, 6) that Microsoft hadn't yet ingested.
Element84 is currently the FRESHEST source for native Sentinel-2/Landsat.
HLS is only available through Microsoft (NASA partnership), so we still
query PC for those harmonized collections.

For each date, the row records counts and cloud stats from each source.
A "best source" field picks whichever source has the most clear tiles
so the metadata page can show a single quality verdict.

A plain-language `why` field explains the verdict for non-technical users.

Usage:
    python pipeline/build_sat_availability.py

Output:
    site/data/sat_availability.json
"""

import json
from collections import defaultdict
from pathlib import Path
import pystac_client
import planetary_computer

E84_URL = "https://earth-search.aws.element84.com/v1"
PC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

BBOX = [-112.2, 44.9, -109.0, 46.5]
TOTAL_TILES = 12
OUTPUT = Path(__file__).parent.parent / "site" / "data" / "sat_availability.json"

# Date range: a bit over a season's worth, walks back ~7 months
DATE_RANGE = "2025-10-01/2026-06-01"


def log(msg):
    print(f"[sat] {msg}", flush=True)


def parse_native_s2_tile(item_id):
    """Native S2 ID format: S2A_MSIL2A_20260328T182951_R027_T12TVS_..."""
    # Find the part starting with T followed by 5 chars
    for part in item_id.split("_"):
        if len(part) == 6 and part.startswith("T"):
            return part
    return ""


def parse_native_landsat_tile(item_id):
    """Native Landsat ID format: LC09_L2SP_038029_20260402_02_T1
    The 3rd underscored field (e.g. '038029') is WRS path/row."""
    parts = item_id.split("_")
    return parts[2] if len(parts) > 2 else ""


def parse_hls_tile(item_id):
    """HLS ID format: HLS.S30.T12TVR.2026094T181921.v2.0"""
    parts = item_id.split(".")
    return parts[2] if len(parts) > 2 else ""


def fetch_collection(catalog, collection, parse_tile_fn, label):
    log(f"  {label}...")
    search = catalog.search(
        collections=[collection], bbox=BBOX,
        datetime=DATE_RANGE, max_items=2000,
    )
    items = list(search.items())
    log(f"    {len(items)} items")

    by_date = defaultdict(list)
    for it in items:
        dt = it.properties["datetime"][:10]
        cc = it.properties.get("eo:cloud_cover", 999)
        tile = parse_tile_fn(it.id)
        by_date[dt].append({"tile": tile, "cloud": cc})
    return by_date, len(items)


def parse_e84_landsat_tile(item_id):
    """Element84 Landsat ID format: LC09_L2SP_038029_20260402_02_T1
    Same as PC format. Extract WRS path/row (3rd field)."""
    parts = item_id.split("_")
    return parts[2] if len(parts) > 2 else ""


def parse_e84_s2_tile(item_id):
    """Element84 Sentinel-2 ID format: S2C_12TUQ_20260404_0_L2A
    The 2nd underscored field (e.g. '12TUQ') is the MGRS tile minus the
    leading T. Add the T back for consistency with native PC format."""
    parts = item_id.split("_")
    if len(parts) >= 2:
        return "T" + parts[1]
    return ""


def summarize(items):
    """Return (n_items, n_clear, avg_cloud, n_unique_tiles, aoi_pct)."""
    if not items:
        return 0, 0, 0, 0, 0
    n = len(items)
    clear = sum(1 for t in items if t["cloud"] < 30)
    avg = sum(t["cloud"] for t in items) / n
    uniq = len(set(t["tile"] for t in items if t["tile"]))
    aoi = round(uniq / TOTAL_TILES * 100)
    return n, clear, round(avg, 1), uniq, aoi


def explain(s2, ls, hls_s, hls_l, q):
    """Generate a plain-English explanation of why this date got this verdict."""
    parts = []

    # Total clear tiles across all sources (deduped roughly by satellite type)
    s2_best_clr = max(s2[1], hls_s[1])  # Sentinel-2 best
    ls_best_clr = max(ls[1], hls_l[1])  # Landsat best

    if q == "excellent":
        return f"Clear day! {s2_best_clr} clear Sentinel-2 tiles cover most of the area."
    if q == "good":
        return f"Mostly clear — {s2_best_clr} clear Sentinel-2 tiles processable for snow."
    if q == "partial":
        bits = []
        if s2_best_clr > 0:
            bits.append(f"{s2_best_clr} partial Sentinel-2 tiles")
        if ls_best_clr > 0:
            bits.append(f"{ls_best_clr} Landsat tiles")
        return "Some imagery available — " + " and ".join(bits) + ", not enough for a full map."
    # cloudy
    s2_total = max(s2[0], hls_s[0])
    ls_total = max(ls[0], hls_l[0])
    if s2_total == 0 and ls_total == 0:
        return "No satellite passed over today."
    sources = []
    if s2_total:
        sources.append(f"Sentinel-2 ({max(s2[2], hls_s[2])}% cloud)")
    if ls_total:
        sources.append(f"Landsat ({max(ls[2], hls_l[2])}% cloud)")
    return "Too cloudy — " + " and ".join(sources) + ". Snow obscured by clouds."


def main():
    log("Querying Element84 (AWS) for native S2 + Landsat...")
    e84 = pystac_client.Client.open(E84_URL)
    s2_by, s2_total = fetch_collection(
        e84, "sentinel-2-l2a", parse_e84_s2_tile, "Sentinel-2 L2A (native, Element84)")
    ls_by, ls_total = fetch_collection(
        e84, "landsat-c2-l2", parse_e84_landsat_tile, "Landsat C2 L2 (native, Element84)")

    log("Querying Microsoft Planetary Computer for HLS...")
    pc = pystac_client.Client.open(PC_URL, modifier=planetary_computer.sign_inplace)
    hls_s_by, hls_s_total = fetch_collection(
        pc, "hls2-s30", parse_hls_tile, "HLS Sentinel-2 (harmonized, PC)")
    hls_l_by, hls_l_total = fetch_collection(
        pc, "hls2-l30", parse_hls_tile, "HLS Landsat (harmonized, PC)")

    all_dates = sorted(set(
        list(s2_by.keys()) + list(ls_by.keys()) +
        list(hls_s_by.keys()) + list(hls_l_by.keys())
    ), reverse=True)

    rows = []
    stats = {
        "total": 0,
        "s2_scenes": s2_total, "ls_scenes": ls_total,
        "hls_s_scenes": hls_s_total, "hls_l_scenes": hls_l_total,
        "excellent": 0, "good": 0, "partial": 0, "cloudy": 0,
    }

    for dt in all_dates:
        s2 = summarize(s2_by.get(dt, []))      # native S2
        ls = summarize(ls_by.get(dt, []))      # native Landsat
        hls_s = summarize(hls_s_by.get(dt, []))  # HLS S2
        hls_l = summarize(hls_l_by.get(dt, []))  # HLS Landsat

        # Best Sentinel-2-equivalent (native or HLS, whichever has more clear tiles)
        s2_best = s2 if s2[1] >= hls_s[1] else hls_s
        s2_n, s2_clr, s2_cc, s2_uniq, s2_aoi = s2_best

        # Best Landsat-equivalent
        ls_best = ls if ls[1] >= hls_l[1] else hls_l
        ls_n, ls_clr, ls_cc, ls_uniq, ls_aoi = ls_best

        # Combined coverage: union of clear S2 + Landsat tile coverage
        # (roughly — we approximate by taking the max instead of doing real
        # geometric union, which would require WKT parsing per tile)
        comb = max(s2_aoi, ls_aoi)

        # Quality classification
        if s2_clr >= 10 and s2_cc < 20:
            q = "excellent"
        elif s2_clr >= 5:
            q = "good"
        elif s2_clr >= 2 or (ls_n and ls_cc < 30):
            q = "partial"
        else:
            q = "cloudy"
        stats[q] += 1

        why = explain(s2, ls, hls_s, hls_l, q)

        rows.append({
            "dt": dt,
            "s2n": s2_n, "s2clr": s2_clr, "s2cc": s2_cc, "s2aoi": s2_aoi,
            "lsn": ls_n, "lscc": ls_cc, "lsaoi": ls_aoi,
            "hls_s_n": hls_s[0], "hls_s_clr": hls_s[1], "hls_s_cc": hls_s[2],
            "hls_l_n": hls_l[0], "hls_l_clr": hls_l[1], "hls_l_cc": hls_l[2],
            "comb": comb,
            "q": q,
            "why": why,
            # Note: s2n/s2clr/s2cc/s2aoi are now "best Sentinel-2-equivalent" —
            # i.e. they fall back to HLS-S30 when native S2 is empty. This is
            # how we remain fresh when Microsoft lags ingesting native L2A.
            "s2_source": "native" if s2[1] >= hls_s[1] and s2[0] > 0 else "hls",
            "ls_source": "native" if ls[1] >= hls_l[1] and ls[0] > 0 else "hls",
        })
        stats["total"] += 1

    # Per-satellite tables: ONE row per date, not one per source.
    #
    # IMPORTANT: native L2A and HLS-S30 are the same observation processed
    # differently — both derived from the same Sentinel-2 satellite pass.
    # Showing them as two rows would suggest "two passes happened" when
    # really it's one pass with two product versions. Same for native
    # Landsat C2 vs HLS-L30.
    #
    # Strategy: prefer native (10m for S2, 30m for Landsat) and fall back
    # to HLS only when native is absent (Microsoft ingestion lag). The
    # "products" field records which product versions exist for that day
    # so a small badge can be shown in the UI.
    def date_table(by_date_native, by_date_hls):
        out = []
        all_dates = sorted(set(list(by_date_native.keys()) + list(by_date_hls.keys())), reverse=True)
        for dt in all_dates:
            native = by_date_native.get(dt, [])
            hls = by_date_hls.get(dt, [])
            # Pick the source for the displayed numbers — native preferred.
            chosen = native if native else hls
            chosen_src = "native" if native else "hls"
            n = len(chosen)
            clr = sum(1 for t in chosen if t["cloud"] < 30)
            cc = round(sum(t["cloud"] for t in chosen) / n, 1) if n else 0
            uniq = len(set(t["tile"] for t in chosen if t["tile"]))
            aoi = round(uniq / TOTAL_TILES * 100) if n else 0

            products = []
            if native: products.append("native")
            if hls: products.append("hls")

            out.append({
                "dt": dt,
                "src": chosen_src,       # which source these numbers came from
                "products": products,    # all product versions available for this date
                "n": n,
                "clr": clr,
                "cc": cc,
                "aoi": aoi,
            })
        return out

    s2_table = date_table(s2_by, hls_s_by)
    ls_table = date_table(ls_by, hls_l_by)
    log(f"  Per-date tables: {len(s2_table)} Sentinel-2 dates, {len(ls_table)} Landsat dates")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump({
            "stats": stats,
            "rows": rows,           # aggregated by date with quality verdict (existing)
            "s2_table": s2_table,   # one row per date+source for Sentinel-2 family
            "ls_table": ls_table,   # one row per date+source for Landsat family
        }, f)

    size_kb = OUTPUT.stat().st_size // 1024
    log(f"Done: {len(rows)} dates, {size_kb}KB")
    log(f"  Excellent: {stats['excellent']}, Good: {stats['good']}, Partial: {stats['partial']}, Cloudy: {stats['cloudy']}")
    log(f"  Sources: {s2_total} native S2, {ls_total} native Landsat, {hls_s_total} HLS-S30, {hls_l_total} HLS-L30")


if __name__ == "__main__":
    main()
